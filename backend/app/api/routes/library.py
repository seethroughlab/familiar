"""Library management endpoints."""

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import Float, String, func, select

from app.api.deps import DbSession
from app.api.exceptions import sanitize_error_for_client
from app.api.ratelimit import SCAN_RATE_LIMIT, limiter
from app.config import settings
from app.db.models import AlbumType, Track, TrackAnalysis, TrackStatus
from app.services.import_service import ImportService, MusicImportError, save_upload_to_temp
from app.services.scanner import LibraryScanner
from app.services.tasks import get_sync_progress

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/library", tags=["library"])


class LibraryStats(BaseModel):
    """Library statistics."""

    total_tracks: int
    total_albums: int
    total_artists: int
    albums: int
    compilations: int
    soundtracks: int
    analyzed_tracks: int
    pending_analysis: int


# ============================================================================
# Unified Sync Models
# ============================================================================


class SyncProgress(BaseModel):
    """Unified sync progress covering discovery, reading, and analysis."""

    phase: str = "idle"  # "discovering", "reading", "analyzing", "complete", "error"
    phase_message: str = ""

    # Discovery/scan metrics
    files_discovered: int = 0
    files_processed: int = 0
    files_total: int = 0
    new_tracks: int = 0
    updated_tracks: int = 0
    unchanged_tracks: int = 0
    relocated_tracks: int = 0
    marked_missing: int = 0
    recovered: int = 0

    # Analysis metrics
    tracks_analyzed: int = 0
    tracks_pending_analysis: int = 0
    tracks_total: int = 0
    analysis_percent: float = 0.0

    # Overall
    started_at: str | None = None
    current_item: str | None = None
    last_heartbeat: str | None = None
    errors: list[str] = []


class SyncStatus(BaseModel):
    """Unified sync status response."""

    status: str  # "idle", "running", "completed", "error"
    message: str
    progress: SyncProgress | None = None


# ============================================================================
# Artist & Album Browsing
# ============================================================================


class ArtistSummary(BaseModel):
    """Artist with aggregated stats."""

    name: str
    track_count: int
    album_count: int
    first_track_id: str  # For artwork lookup


class ArtistListResponse(BaseModel):
    """Paginated list of artists."""

    items: list[ArtistSummary]
    total: int
    page: int
    page_size: int


@router.get("/artists", response_model=ArtistListResponse)
async def list_artists(
    db: DbSession,
    search: str | None = None,
    sort_by: str = "name",  # name, track_count, album_count
    page: int = 1,
    page_size: int = 100,
    has_embeddings: bool = False,
) -> ArtistListResponse:
    """Get distinct artists with aggregated stats.

    Returns artists sorted by name (default), track count, or album count.
    Includes first_track_id for artwork lookup.

    Args:
        has_embeddings: If True, only include artists that have at least one
            track with an embedding (for use in similarity-based features).
    """
    from sqlalchemy import cast, desc, literal_column
    from sqlalchemy.dialects.postgresql import TEXT

    # Base query: group by normalized (lowercase) artist, count tracks and albums
    # Use max(artist) to pick a canonical display name for each group
    # Cast UUID to text for min() since PostgreSQL doesn't support min(uuid)
    base_query = (
        select(
            func.max(Track.artist).label("name"),  # Pick one display name per group
            func.lower(Track.artist).label("artist_normalized"),
            func.count(Track.id).label("track_count"),
            func.count(func.distinct(Track.album)).label("album_count"),
            func.min(cast(Track.id, TEXT)).label("first_track_id"),  # Cast to text for min()
        )
        .where(
            Track.artist.isnot(None),
            Track.artist != "",
            Track.status == TrackStatus.ACTIVE,
        )
        .group_by(func.lower(Track.artist))
    )

    # Filter to only artists with embeddings if requested
    if has_embeddings:
        # Subquery to get track IDs that have embeddings
        tracks_with_embeddings = (
            select(TrackAnalysis.track_id)
            .where(TrackAnalysis.embedding.isnot(None))
            .distinct()
            .subquery()
        )
        base_query = base_query.where(Track.id.in_(select(tracks_with_embeddings)))

    # Apply search filter
    if search:
        base_query = base_query.having(func.lower(Track.artist).contains(search.lower()))

    # Get total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply sorting (use artist_normalized for consistent case-insensitive ordering)
    if sort_by == "track_count":
        base_query = base_query.order_by(desc(literal_column("track_count")), literal_column("artist_normalized"))
    elif sort_by == "album_count":
        base_query = base_query.order_by(desc(literal_column("album_count")), literal_column("artist_normalized"))
    else:
        base_query = base_query.order_by(literal_column("artist_normalized"))

    # Apply pagination
    offset = (page - 1) * page_size
    base_query = base_query.offset(offset).limit(page_size)

    result = await db.execute(base_query)
    rows = result.all()

    items = [
        ArtistSummary(
            name=row.name,
            track_count=row.track_count,
            album_count=row.album_count,
            first_track_id=str(row.first_track_id),
        )
        for row in rows
    ]

    return ArtistListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ============================================================================
# Artist Detail
# ============================================================================


class ArtistAlbum(BaseModel):
    """Album belonging to an artist in the library."""

    name: str
    year: int | None
    track_count: int
    first_track_id: str


class ArtistTrack(BaseModel):
    """Track belonging to an artist."""

    id: str
    title: str | None
    album: str | None
    track_number: int | None
    duration_seconds: float | None
    year: int | None


class SimilarArtistInfo(BaseModel):
    """Enriched similar artist with library status and external links."""

    name: str
    match_score: float  # 0-1 similarity from Last.fm
    in_library: bool
    track_count: int | None = None  # If in library
    image_url: str | None = None
    lastfm_url: str | None = None
    bandcamp_url: str | None = None  # Search link for discovery


class ArtistDetailResponse(BaseModel):
    """Detailed artist info with bio, albums, and tracks."""

    # Basic info (from library)
    name: str
    track_count: int
    album_count: int
    total_duration_seconds: float

    # From Last.fm (may be None if not fetched/available)
    bio_summary: str | None = None
    bio_content: str | None = None
    image_url: str | None = None
    lastfm_url: str | None = None
    listeners: int | None = None
    playcount: int | None = None
    tags: list[str] = []
    similar_artists: list[SimilarArtistInfo] = []

    # Library content
    albums: list[ArtistAlbum]
    tracks: list[ArtistTrack]

    # First track ID for fallback artwork
    first_track_id: str

    # Cache status
    lastfm_fetched: bool = False
    lastfm_error: str | None = None


@router.get("/artists/{artist_name}", response_model=ArtistDetailResponse)
async def get_artist_detail(
    db: DbSession,
    artist_name: str,
    refresh_lastfm: bool = False,
) -> ArtistDetailResponse:
    """Get detailed artist information including Last.fm bio and library content.

    Fetches and caches Last.fm data. Cache expires after 30 days.
    Use refresh_lastfm=true to force a refresh.

    Args:
        artist_name: The artist name (URL-encoded)
        refresh_lastfm: Force refresh of Last.fm data
    """
    from datetime import datetime, timedelta
    from urllib.parse import unquote

    from sqlalchemy import cast
    from sqlalchemy.dialects.postgresql import TEXT

    from app.db.models import ArtistInfo
    from app.services.lastfm import get_lastfm_service

    # URL decode the artist name
    artist_name = unquote(artist_name)
    artist_normalized = artist_name.lower().strip()

    # Get library stats for this artist
    stats_query = (
        select(
            func.count(Track.id).label("track_count"),
            func.count(func.distinct(Track.album)).label("album_count"),
            func.sum(Track.duration_seconds).label("total_duration"),
            func.min(cast(Track.id, TEXT)).label("first_track_id"),
        )
        .where(
            func.lower(func.trim(Track.artist)) == artist_normalized,
            Track.status == TrackStatus.ACTIVE,
        )
    )
    result = await db.execute(stats_query)
    stats = result.one_or_none()

    if not stats or stats.track_count == 0:
        raise HTTPException(status_code=404, detail="Artist not found in library")

    # Get albums by this artist
    albums_query = (
        select(
            Track.album.label("name"),
            func.max(Track.year).label("year"),
            func.count(Track.id).label("track_count"),
            func.min(cast(Track.id, TEXT)).label("first_track_id"),
        )
        .where(
            func.lower(func.trim(Track.artist)) == artist_normalized,
            Track.status == TrackStatus.ACTIVE,
            Track.album.isnot(None),
            Track.album != "",
        )
        .group_by(Track.album)
        .order_by(func.max(Track.year).desc().nullslast(), Track.album)
    )
    albums_result = await db.execute(albums_query)
    albums = [
        ArtistAlbum(
            name=row.name or "Unknown Album",
            year=row.year,
            track_count=row.track_count,
            first_track_id=str(row.first_track_id),
        )
        for row in albums_result.all()
    ]

    # Get tracks by this artist
    tracks_query = (
        select(Track)
        .where(
            func.lower(func.trim(Track.artist)) == artist_normalized,
            Track.status == TrackStatus.ACTIVE,
        )
        .order_by(Track.album, Track.disc_number, Track.track_number, Track.title)
        .limit(500)  # Limit to prevent huge responses
    )
    tracks_result = await db.execute(tracks_query)
    tracks = [
        ArtistTrack(
            id=str(t.id),
            title=t.title,
            album=t.album,
            track_number=t.track_number,
            duration_seconds=t.duration_seconds,
            year=t.year,
        )
        for t in tracks_result.scalars().all()
    ]

    # Check for cached Last.fm data
    cache_max_age = timedelta(days=30)
    lastfm_data: ArtistInfo | None = None
    lastfm_fetched = False
    lastfm_error: str | None = None

    cached = await db.get(ArtistInfo, artist_normalized)

    if cached and not refresh_lastfm:
        cache_age = datetime.utcnow() - cached.fetched_at
        # Auto-refresh if similar_artists is empty (stale cache from before feature)
        needs_similar_refresh = not cached.fetch_error and (
            not cached.similar_artists
            or "match" not in (cached.similar_artists[0] if cached.similar_artists else {})
        )
        if cache_age < cache_max_age and not needs_similar_refresh:
            lastfm_fetched = True
            lastfm_data = cached
            lastfm_error = cached.fetch_error

    # Fetch from Last.fm if needed (or if similar_artists missing)
    if not lastfm_data or refresh_lastfm:
        lastfm_service = get_lastfm_service()
        if lastfm_service.is_configured():
            try:
                info, similar_from_api = await asyncio.gather(
                    lastfm_service.get_artist_info(artist_name),
                    lastfm_service.get_similar_artists(artist_name, limit=20),
                )
                if info:
                    # Extract image URL (prefer extralarge)
                    # Filter out Last.fm's default placeholder image (star icon)
                    images = info.get("image", [])
                    image_urls: dict[str, str] = {
                        img.get("size"): img.get("#text")
                        for img in images
                        if img.get("#text") and "2a96cbd8b46e442fc41c2b86b821562f" not in img.get("#text", "")
                    }

                    # Extract similar artists (prefer dedicated API with match scores)
                    similar = similar_from_api if similar_from_api else info.get("similar", {}).get("artist", [])

                    # Extract tags
                    tags = [
                        t.get("name")
                        for t in info.get("tags", {}).get("tag", [])
                        if t.get("name")
                    ]

                    # Create or update cache entry
                    if cached:
                        cached.artist_name = info.get("name", artist_name)
                        cached.musicbrainz_id = info.get("mbid")
                        cached.lastfm_url = info.get("url")
                        cached.bio_summary = info.get("bio", {}).get("summary")
                        cached.bio_content = info.get("bio", {}).get("content")
                        cached.image_small = image_urls.get("small")
                        cached.image_medium = image_urls.get("medium")
                        cached.image_large = image_urls.get("large")
                        cached.image_extralarge = image_urls.get("extralarge")
                        cached.listeners = (
                            int(info.get("stats", {}).get("listeners", 0)) or None
                        )
                        cached.playcount = (
                            int(info.get("stats", {}).get("playcount", 0)) or None
                        )
                        cached.similar_artists = similar
                        cached.tags = tags
                        cached.fetched_at = datetime.utcnow()
                        cached.fetch_error = None
                    else:
                        cached = ArtistInfo(
                            artist_name_normalized=artist_normalized,
                            artist_name=info.get("name", artist_name),
                            musicbrainz_id=info.get("mbid"),
                            lastfm_url=info.get("url"),
                            bio_summary=info.get("bio", {}).get("summary"),
                            bio_content=info.get("bio", {}).get("content"),
                            image_small=image_urls.get("small"),
                            image_medium=image_urls.get("medium"),
                            image_large=image_urls.get("large"),
                            image_extralarge=image_urls.get("extralarge"),
                            listeners=(
                                int(info.get("stats", {}).get("listeners", 0)) or None
                            ),
                            playcount=(
                                int(info.get("stats", {}).get("playcount", 0)) or None
                            ),
                            similar_artists=similar,
                            tags=tags,
                        )
                        db.add(cached)

                    await db.commit()
                    lastfm_data = cached
                    lastfm_fetched = True
                    lastfm_error = None
                else:
                    # Artist not found on Last.fm - cache the miss
                    if not cached:
                        cached = ArtistInfo(
                            artist_name_normalized=artist_normalized,
                            artist_name=artist_name,
                            fetch_error="Artist not found on Last.fm",
                        )
                        db.add(cached)
                        await db.commit()
                    lastfm_error = "Artist not found on Last.fm"
            except Exception as e:
                lastfm_error = str(e)

    # Enrich similar artists with library status and external links
    enriched_similar: list[SimilarArtistInfo] = []
    raw_similar = lastfm_data.similar_artists if lastfm_data else []

    if raw_similar:
        from app.services.search_links import generate_artist_search_url

        # Get all similar artist names (normalized for lookup)
        similar_names = [s.get("name", "") for s in raw_similar if s.get("name")]
        similar_normalized = [n.lower().strip() for n in similar_names]

        # Batch query to check which exist in library with track counts
        if similar_normalized:
            library_artists_query = (
                select(
                    func.lower(func.trim(Track.artist)).label("artist_normalized"),
                    func.count(Track.id).label("track_count"),
                )
                .where(
                    func.lower(func.trim(Track.artist)).in_(similar_normalized),
                    Track.status == TrackStatus.ACTIVE,
                )
                .group_by(func.lower(func.trim(Track.artist)))
            )
            result = await db.execute(library_artists_query)
            library_map = {row.artist_normalized: row.track_count for row in result.all()}
        else:
            library_map = {}

        # Build enriched similar artists
        for similar in raw_similar:
            name = similar.get("name", "")
            if not name:
                continue

            normalized = name.lower().strip()
            in_library = normalized in library_map
            track_count = library_map.get(normalized)

            # Extract image URL from Last.fm data (filter out placeholder)
            LASTFM_PLACEHOLDER = "2a96cbd8b46e442fc41c2b86b821562f"
            images = similar.get("image", [])
            image_url = None
            for img in images:
                url = img.get("#text", "")
                if img.get("size") == "large" and url and LASTFM_PLACEHOLDER not in url:
                    image_url = url
                    break
            if not image_url:
                for img in images:
                    url = img.get("#text", "")
                    if url and LASTFM_PLACEHOLDER not in url:
                        image_url = url
                        break

            # Parse match score (Last.fm returns it as string "0.xxx")
            match_str = similar.get("match", "0")
            try:
                match_score = float(match_str)
            except (ValueError, TypeError):
                match_score = 0.0

            enriched_similar.append(
                SimilarArtistInfo(
                    name=name,
                    match_score=match_score,
                    in_library=in_library,
                    track_count=track_count,
                    image_url=image_url,
                    lastfm_url=similar.get("url"),
                    bandcamp_url=generate_artist_search_url("bandcamp", name),
                )
            )

    # Build response
    # Filter out Last.fm's placeholder star image from cached data
    def _filter_placeholder(url: str | None) -> str | None:
        if url and "2a96cbd8b46e442fc41c2b86b821562f" in url:
            return None
        return url

    image_url = None
    if lastfm_data:
        image_url = _filter_placeholder(lastfm_data.image_extralarge) or _filter_placeholder(lastfm_data.image_large)

    return ArtistDetailResponse(
        name=artist_name,
        track_count=stats.track_count,
        album_count=stats.album_count,
        total_duration_seconds=stats.total_duration or 0,
        bio_summary=lastfm_data.bio_summary if lastfm_data else None,
        bio_content=lastfm_data.bio_content if lastfm_data else None,
        image_url=image_url,
        lastfm_url=lastfm_data.lastfm_url if lastfm_data else None,
        listeners=lastfm_data.listeners if lastfm_data else None,
        playcount=lastfm_data.playcount if lastfm_data else None,
        tags=(lastfm_data.tags or []) if lastfm_data else [],
        similar_artists=enriched_similar,
        albums=albums,
        tracks=tracks,
        first_track_id=str(stats.first_track_id),
        lastfm_fetched=lastfm_fetched,
        lastfm_error=lastfm_error,
    )


# ============================================================================
# Artist Image
# ============================================================================


@router.get("/artists/{artist_name}/image", response_class=StreamingResponse)
async def get_artist_image(
    db: DbSession,
    request: Request,
    artist_name: str,
    size: str = "large",  # small, medium, large, extralarge
):
    """Get artist image with fallback chain.

    Fallback order:
    1. Cached Last.fm image from ArtistInfo table
    2. Fetch from Last.fm API and cache
    3. Fetch from Spotify API (requires profile with Spotify connection)
    4. Fallback to first album's artwork

    Args:
        artist_name: The artist name (URL-encoded)
        size: Image size: small, medium, large, or extralarge

    Returns:
        Redirect to image URL or streamed image from album artwork
    """
    from urllib.parse import unquote

    from app.db.models import ArtistInfo
    from app.services.artwork import compute_album_hash, extract_and_save_artwork, get_artwork_path
    from app.services.lastfm import get_lastfm_service

    # Validate size
    if size not in ("small", "medium", "large", "extralarge"):
        size = "large"

    # URL decode the artist name
    artist_name = unquote(artist_name)
    artist_normalized = artist_name.lower().strip()

    # Size mapping for ArtistInfo columns
    size_field_map = {
        "small": "image_small",
        "medium": "image_medium",
        "large": "image_large",
        "extralarge": "image_extralarge",
    }

    # Last.fm placeholder image hash - filter these out
    LASTFM_PLACEHOLDER = "2a96cbd8b46e442fc41c2b86b821562f"

    def is_valid_image(url: str | None) -> bool:
        return bool(url and LASTFM_PLACEHOLDER not in url)

    # Step 1: Check cached ArtistInfo
    cached = await db.get(ArtistInfo, artist_normalized)
    if cached:
        image_url = getattr(cached, size_field_map[size], None)
        # Try fallback sizes if requested size not available or is placeholder
        if not is_valid_image(image_url):
            image_url = None
            for fallback in ["extralarge", "large", "medium", "small"]:
                candidate = getattr(cached, size_field_map[fallback], None)
                if is_valid_image(candidate):
                    image_url = candidate
                    break
        if image_url:
            return RedirectResponse(
                url=image_url,
                headers={"Cache-Control": "public, max-age=86400"},  # 1 day cache
            )

    # Step 2: Try Last.fm API
    lastfm_service = get_lastfm_service()
    if lastfm_service.is_configured():
        try:
            info = await lastfm_service.get_artist_info(artist_name)
            if info:
                images = info.get("image", [])
                # Filter out placeholder images
                image_urls: dict[str, str] = {
                    img.get("size"): img.get("#text")
                    for img in images
                    if img.get("#text") and LASTFM_PLACEHOLDER not in img.get("#text", "")
                }

                # Get requested size or fallback to available
                image_url = (
                    image_urls.get(size)
                    or image_urls.get("extralarge")
                    or image_urls.get("large")
                    or image_urls.get("medium")
                    or image_urls.get("small")
                )

                if image_url:
                    # Cache in ArtistInfo
                    await _cache_artist_images(db, artist_normalized, artist_name, image_urls)
                    return RedirectResponse(
                        url=image_url,
                        headers={"Cache-Control": "public, max-age=86400"},
                    )
        except Exception as e:
            logger.debug(f"Last.fm artist image lookup failed for '{artist_name}': {e}")

    # Step 3: Try Spotify (requires profile with Spotify connection)
    profile_id = request.headers.get("X-Profile-ID")
    if profile_id:
        try:
            from uuid import UUID

            from app.services.spotify import SpotifyArtistService

            spotify_service = SpotifyArtistService(db)
            spotify_artist = await spotify_service.search_artist(
                UUID(profile_id),
                artist_name,
            )

            if spotify_artist and spotify_artist.get("images"):
                # Spotify returns images sorted by size (largest first)
                images = spotify_artist["images"]
                if images:
                    image_url = images[0]["url"]  # Largest image
                    # Cache as extralarge
                    await _cache_artist_images(
                        db,
                        artist_normalized,
                        artist_name,
                        {"extralarge": image_url, "large": image_url},
                    )
                    return RedirectResponse(
                        url=image_url,
                        headers={"Cache-Control": "public, max-age=86400"},
                    )
        except Exception as e:
            logger.debug(f"Spotify artist image lookup failed for '{artist_name}': {e}")

    # Step 4: Fallback to first album's artwork
    track_query = (
        select(Track)
        .where(
            func.lower(func.trim(Track.artist)) == artist_normalized,
            Track.status == TrackStatus.ACTIVE,
        )
        .order_by(Track.album, Track.track_number)
        .limit(1)
    )
    result = await db.execute(track_query)
    track = result.scalar_one_or_none()

    if track:
        album_hash = compute_album_hash(track.artist, track.album)
        artwork_size = "thumb" if size in ("small", "medium") else "full"
        artwork_path = get_artwork_path(album_hash, artwork_size)

        if artwork_path.exists():
            def stream_artwork():
                with open(artwork_path, "rb") as f:
                    yield f.read()

            return StreamingResponse(
                stream_artwork(),
                media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=31536000"},
            )

        # Try extracting from audio file
        file_path = Path(track.file_path)
        if file_path.exists():
            extract_and_save_artwork(file_path, track.artist, track.album)
            if artwork_path.exists():
                def stream_artwork():
                    with open(artwork_path, "rb") as f:
                        yield f.read()

                return StreamingResponse(
                    stream_artwork(),
                    media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=31536000"},
                )

    # No image available
    raise HTTPException(status_code=404, detail="No artist image available")


async def _cache_artist_images(
    db: DbSession,
    artist_normalized: str,
    artist_name: str,
    image_urls: dict[str, str],
) -> None:
    """Cache artist image URLs in ArtistInfo table."""
    from datetime import datetime

    from app.db.models import ArtistInfo

    cached = await db.get(ArtistInfo, artist_normalized)
    if cached:
        if image_urls.get("small"):
            cached.image_small = image_urls["small"]
        if image_urls.get("medium"):
            cached.image_medium = image_urls["medium"]
        if image_urls.get("large"):
            cached.image_large = image_urls["large"]
        if image_urls.get("extralarge"):
            cached.image_extralarge = image_urls["extralarge"]
        cached.fetched_at = datetime.utcnow()
    else:
        cached = ArtistInfo(
            artist_name_normalized=artist_normalized,
            artist_name=artist_name,
            image_small=image_urls.get("small"),
            image_medium=image_urls.get("medium"),
            image_large=image_urls.get("large"),
            image_extralarge=image_urls.get("extralarge"),
        )
        db.add(cached)

    await db.commit()


class AlbumSummary(BaseModel):
    """Album with metadata."""

    name: str
    artist: str
    year: int | None
    track_count: int
    first_track_id: str  # For artwork lookup


class AlbumListResponse(BaseModel):
    """Paginated list of albums."""

    items: list[AlbumSummary]
    total: int
    page: int
    page_size: int


class AlbumTrack(BaseModel):
    """Track belonging to an album."""

    id: str
    title: str | None
    track_number: int | None
    disc_number: int | None
    duration_seconds: float | None


class SimilarAlbumInfo(BaseModel):
    """Similar album with metadata (in library)."""

    name: str
    artist: str
    year: int | None
    track_count: int
    first_track_id: str
    similarity_score: float  # 0-1, higher is more similar


class DiscoverAlbumInfo(BaseModel):
    """Album to discover (not in library)."""

    name: str
    artist: str
    image_url: str | None = None
    lastfm_url: str | None = None
    bandcamp_url: str | None = None


class AlbumDetailResponse(BaseModel):
    """Detailed album info with tracks and discovery."""

    # Basic info
    name: str
    artist: str
    album_artist: str | None
    year: int | None
    genre: str | None
    track_count: int
    total_duration_seconds: float
    first_track_id: str

    # Tracks
    tracks: list[AlbumTrack]

    # Discovery - Similar albums in library
    similar_albums: list[SimilarAlbumInfo]

    # Discovery - Albums to discover (not in library)
    discover_albums: list[DiscoverAlbumInfo] = []

    # Discovery - Other albums by same artist
    other_albums_by_artist: list[SimilarAlbumInfo]


@router.get("/albums", response_model=AlbumListResponse)
async def list_albums(
    db: DbSession,
    artist: str | None = None,
    search: str | None = None,
    sort_by: str = "name",  # name, year, track_count, artist
    page: int = 1,
    page_size: int = 100,
) -> AlbumListResponse:
    """Get distinct albums with metadata.

    Returns albums sorted by name (default), year, track count, or artist.
    Includes first_track_id for artwork lookup.
    """
    from sqlalchemy import cast, desc, literal_column
    from sqlalchemy.dialects.postgresql import TEXT

    # Base query: group by (album_artist, album), get year and track count
    # Use album_artist (falls back to artist) to properly group compilations
    # Note: album_artist is populated during library sync for compilation albums
    # Cast UUID to text for min() since PostgreSQL doesn't support min(uuid)
    # Group by lower(album) for case-insensitive matching (e.g., "Alice In Ultraland" = "Alice in Ultraland")
    album_artist_col = func.coalesce(func.nullif(Track.album_artist, ""), Track.artist)
    album_artist_lower = func.lower(album_artist_col)
    base_query = (
        select(
            func.max(Track.album).label("name"),  # Representative album name from group
            func.max(album_artist_col).label("artist"),  # Representative artist from group
            func.max(Track.year).label("year"),  # Use max year in case of inconsistency
            func.count(Track.id).label("track_count"),
            func.min(cast(Track.id, TEXT)).label("first_track_id"),
        )
        .where(
            Track.album.isnot(None),
            Track.album != "",
            Track.status == TrackStatus.ACTIVE,
        )
        .group_by(album_artist_lower, func.lower(Track.album))
    )

    # Apply artist filter (filter by album_artist to match grouping, case-insensitive)
    if artist:
        base_query = base_query.having(album_artist_lower == func.lower(artist))

    # Apply search filter (search both album name and album artist)
    if search:
        search_lower = search.lower()
        base_query = base_query.having(
            func.lower(Track.album).contains(search_lower)
            | func.lower(album_artist_col).contains(search_lower)
        )

    # Get total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply sorting
    if sort_by == "year":
        base_query = base_query.order_by(desc(literal_column("year")), func.lower(Track.album))
    elif sort_by == "track_count":
        base_query = base_query.order_by(desc(literal_column("track_count")), func.lower(Track.album))
    elif sort_by == "artist":
        base_query = base_query.order_by(func.lower(album_artist_col), func.lower(Track.album))
    else:
        base_query = base_query.order_by(func.lower(Track.album))

    # Apply pagination
    offset = (page - 1) * page_size
    base_query = base_query.offset(offset).limit(page_size)

    result = await db.execute(base_query)
    rows = result.all()

    items = [
        AlbumSummary(
            name=row.name or "Unknown Album",
            artist=row.artist or "Unknown Artist",
            year=row.year,
            track_count=row.track_count,
            first_track_id=str(row.first_track_id),
        )
        for row in rows
    ]

    return AlbumListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/albums/{artist_name}/{album_name}", response_model=AlbumDetailResponse)
async def get_album_detail(
    db: DbSession,
    artist_name: str,
    album_name: str,
    similar_limit: int = Query(8, ge=1, le=20),
) -> AlbumDetailResponse:
    """Get detailed album information with tracks and similar albums.

    Returns album metadata, all tracks, similar albums (by audio embedding),
    and other albums by the same artist.

    Args:
        artist_name: The artist name (URL-encoded)
        album_name: The album name (URL-encoded)
        similar_limit: Maximum number of similar albums to return
    """
    from urllib.parse import unquote

    from sqlalchemy import cast
    from sqlalchemy.dialects.postgresql import TEXT

    # URL decode the names
    artist_name = unquote(artist_name)
    album_name = unquote(album_name)
    artist_normalized = artist_name.lower().strip()
    album_normalized = album_name.lower().strip()

    # Use album_artist (with fallback to artist) to match how list_albums groups albums
    # This ensures compilation/soundtrack albums are found correctly
    album_artist_col = func.coalesce(func.nullif(Track.album_artist, ""), Track.artist)

    # Get album metadata and tracks
    # First try matching by album_artist (for compilations/soundtracks)
    album_query = (
        select(Track)
        .where(
            func.lower(func.trim(album_artist_col)) == artist_normalized,
            func.lower(func.trim(Track.album)) == album_normalized,
            Track.status == TrackStatus.ACTIVE,
        )
        .order_by(Track.disc_number, Track.track_number, Track.title)
    )
    result = await db.execute(album_query)
    tracks_list = result.scalars().all()

    # If not found by album_artist, try matching by track artist
    # This handles navigation from ArtistDetail which groups by Track.artist
    if not tracks_list:
        album_query_by_artist = (
            select(Track)
            .where(
                func.lower(func.trim(Track.artist)) == artist_normalized,
                func.lower(func.trim(Track.album)) == album_normalized,
                Track.status == TrackStatus.ACTIVE,
            )
            .order_by(Track.disc_number, Track.track_number, Track.title)
        )
        result = await db.execute(album_query_by_artist)
        tracks_list = result.scalars().all()

    if not tracks_list:
        raise HTTPException(status_code=404, detail="Album not found in library")

    # Extract album info from first track
    first_track = tracks_list[0]
    album_artist = first_track.album_artist
    year = first_track.year
    genre = first_track.genre
    total_duration = sum(t.duration_seconds or 0 for t in tracks_list)

    # Build tracks list
    tracks = [
        AlbumTrack(
            id=str(t.id),
            title=t.title,
            track_number=t.track_number,
            disc_number=t.disc_number,
            duration_seconds=t.duration_seconds,
        )
        for t in tracks_list
    ]

    # Get other albums by the same artist (using album_artist for consistency)
    other_albums_query = (
        select(
            func.max(Track.album).label("name"),
            func.max(album_artist_col).label("artist"),
            func.max(Track.year).label("year"),
            func.count(Track.id).label("track_count"),
            func.min(cast(Track.id, TEXT)).label("first_track_id"),
        )
        .where(
            func.lower(func.trim(album_artist_col)) == artist_normalized,
            func.lower(func.trim(Track.album)) != album_normalized,
            Track.album.isnot(None),
            Track.album != "",
            Track.status == TrackStatus.ACTIVE,
        )
        .group_by(func.lower(Track.album))
        .order_by(func.max(Track.year).desc().nullslast())
    )
    other_albums_result = await db.execute(other_albums_query)
    other_albums_by_artist = [
        SimilarAlbumInfo(
            name=row.name or "Unknown Album",
            artist=row.artist or artist_name,
            year=row.year,
            track_count=row.track_count,
            first_track_id=str(row.first_track_id),
            similarity_score=1.0,  # Same artist = high relevance
        )
        for row in other_albums_result.all()
    ]

    # Find similar albums using Last.fm similar artists data
    # This finds albums from artists similar to this album's artist that ARE in the library
    similar_albums: list[SimilarAlbumInfo] = []
    from app.db.models import ArtistInfo

    cached_artist = await db.get(ArtistInfo, artist_normalized)
    raw_similar_artists = cached_artist.similar_artists if cached_artist else []

    if raw_similar_artists:
        # Get similar artist names that are IN the library
        similar_artist_names = [s.get("name", "") for s in raw_similar_artists if s.get("name")]
        similar_normalized = [n.lower().strip() for n in similar_artist_names]

        if similar_normalized:
            # Find albums from similar artists in library
            similar_albums_query = (
                select(
                    func.max(Track.album).label("name"),
                    func.max(Track.artist).label("artist"),
                    func.max(Track.year).label("year"),
                    func.count(Track.id).label("track_count"),
                    func.min(cast(Track.id, TEXT)).label("first_track_id"),
                )
                .where(
                    func.lower(func.trim(Track.artist)).in_(similar_normalized),
                    Track.album.isnot(None),
                    Track.album != "",
                    Track.status == TrackStatus.ACTIVE,
                )
                .group_by(
                    func.lower(func.trim(Track.artist)),
                    func.lower(func.trim(Track.album)),
                )
                .order_by(func.max(Track.year).desc().nullslast())
                .limit(similar_limit)
            )

            similar_result = await db.execute(similar_albums_query)
            # Build a map of artist normalized name to match score
            # Use position-based scores (1.0 for first, decreasing) as fallback
            match_scores = {}
            for idx, s in enumerate(raw_similar_artists):
                name = s.get("name", "")
                if name:
                    # Try to get match from Last.fm, otherwise use position-based score
                    raw_match = s.get("match")
                    if raw_match:
                        try:
                            match_scores[name.lower().strip()] = float(raw_match)
                        except (ValueError, TypeError):
                            match_scores[name.lower().strip()] = max(0.3, 1.0 - (idx * 0.1))
                    else:
                        # Position-based: first artist gets ~0.9, decreasing
                        match_scores[name.lower().strip()] = max(0.3, 1.0 - (idx * 0.1))

            for row in similar_result.all():
                artist_norm = (row.artist or "").lower().strip()
                match_score = match_scores.get(artist_norm, 0.5)
                similar_albums.append(
                    SimilarAlbumInfo(
                        name=row.name or "Unknown Album",
                        artist=row.artist or "Unknown Artist",
                        year=row.year,
                        track_count=row.track_count,
                        first_track_id=str(row.first_track_id),
                        similarity_score=round(match_score, 3),
                    )
                )

    # Get albums to discover from similar artists (not in library)
    discover_albums: list[DiscoverAlbumInfo] = []
    from app.services.search_links import generate_artist_search_url

    # Re-use raw_similar_artists from above
    if raw_similar_artists:
        # Get similar artist names
        similar_artist_names = [s.get("name", "") for s in raw_similar_artists if s.get("name")]
        similar_normalized = [n.lower().strip() for n in similar_artist_names]

        # Check which similar artists are NOT in library
        if similar_normalized:
            library_artists_query = (
                select(func.lower(func.trim(Track.artist)).label("artist_normalized"))
                .where(
                    func.lower(func.trim(Track.artist)).in_(similar_normalized),
                    Track.status == TrackStatus.ACTIVE,
                )
                .group_by(func.lower(func.trim(Track.artist)))
            )
            result = await db.execute(library_artists_query)
            in_library = {row.artist_normalized for row in result.all()}

            # For artists NOT in library, suggest exploring their albums
            for similar in raw_similar_artists[:10]:  # Limit to 10
                name = similar.get("name", "")
                if not name:
                    continue
                normalized = name.lower().strip()
                if normalized not in in_library:
                    # Get image URL from Last.fm data
                    images = similar.get("image", [])
                    image_url = None
                    for img in images:
                        if img.get("size") == "large" and img.get("#text"):
                            image_url = img["#text"]
                            break

                    discover_albums.append(
                        DiscoverAlbumInfo(
                            name=f"Albums by {name}",
                            artist=name,
                            image_url=image_url,
                            lastfm_url=similar.get("url"),
                            bandcamp_url=generate_artist_search_url("bandcamp", name),
                        )
                    )

    return AlbumDetailResponse(
        name=album_name,
        artist=artist_name,
        album_artist=album_artist,
        year=year,
        genre=genre,
        track_count=len(tracks),
        total_duration_seconds=total_duration,
        first_track_id=str(first_track.id),
        tracks=tracks,
        similar_albums=similar_albums,
        discover_albums=discover_albums,
        other_albums_by_artist=other_albums_by_artist,
    )


# ============================================================================
# Visualization Aggregations
# ============================================================================


class YearCount(BaseModel):
    """Track count for a single year."""

    year: int
    track_count: int
    album_count: int
    artist_count: int


class YearDistributionResponse(BaseModel):
    """Year distribution for timeline visualization."""

    years: list[YearCount]
    total_with_year: int
    total_without_year: int
    min_year: int | None
    max_year: int | None


@router.get("/years", response_model=YearDistributionResponse)
async def get_year_distribution(db: DbSession) -> YearDistributionResponse:
    """Get track counts grouped by year for timeline visualization.

    Returns aggregated data suitable for large libraries.
    """
    # Query for year distribution
    year_query = (
        select(
            Track.year,
            func.count(Track.id).label("track_count"),
            func.count(func.distinct(Track.album)).label("album_count"),
            func.count(func.distinct(Track.artist)).label("artist_count"),
        )
        .where(
            Track.year.isnot(None),
            Track.status == TrackStatus.ACTIVE,
        )
        .group_by(Track.year)
        .order_by(Track.year)
    )

    result = await db.execute(year_query)
    rows = result.all()

    years = [
        YearCount(
            year=row.year,
            track_count=row.track_count,
            album_count=row.album_count,
            artist_count=row.artist_count,
        )
        for row in rows
    ]

    # Count tracks without year
    without_year = await db.scalar(
        select(func.count(Track.id)).where(
            Track.year.is_(None),
            Track.status == TrackStatus.ACTIVE,
        )
    ) or 0

    total_with = sum(y.track_count for y in years)
    min_year = years[0].year if years else None
    max_year = years[-1].year if years else None

    return YearDistributionResponse(
        years=years,
        total_with_year=total_with,
        total_without_year=without_year,
        min_year=min_year,
        max_year=max_year,
    )


class MoodCell(BaseModel):
    """A cell in the mood grid with track count."""

    energy_min: float
    energy_max: float
    valence_min: float
    valence_max: float
    track_count: int
    # Sample track IDs for this cell (for preview/playback)
    sample_track_ids: list[str]


class MoodDistributionResponse(BaseModel):
    """Mood distribution for 2D visualization."""

    cells: list[MoodCell]
    grid_size: int  # Number of cells per axis
    total_with_mood: int
    total_without_mood: int


@router.get("/mood-distribution", response_model=MoodDistributionResponse)
async def get_mood_distribution(
    db: DbSession,
    grid_size: int = 10,
) -> MoodDistributionResponse:
    """Get mood (energy × valence) distribution for heatmap visualization.

    Divides the 0-1 × 0-1 space into a grid and counts tracks per cell.
    Returns sample track IDs per cell for preview/playback.

    Uses SQL aggregation instead of loading all tracks into Python.
    """
    from sqlalchemy import Integer, cast, literal_column
    from sqlalchemy.dialects.postgresql import array_agg

    cell_size = 1.0 / grid_size

    # Subquery: latest analysis per track (highest version)
    latest_analysis = (
        select(
            TrackAnalysis.track_id,
            TrackAnalysis.energy,
            TrackAnalysis.valence,
            func.row_number()
            .over(
                partition_by=TrackAnalysis.track_id,
                order_by=TrackAnalysis.version.desc(),
            )
            .label("rn"),
        )
        .subquery("latest_analysis")
    )

    # Use typed columns directly
    energy_expr = latest_analysis.c.energy
    valence_expr = latest_analysis.c.valence

    # Bin into grid cells, clamped to [0, grid_size-1]
    energy_cell = func.least(
        cast(func.floor(energy_expr * grid_size), Integer),
        grid_size - 1,
    )
    valence_cell = func.least(
        cast(func.floor(valence_expr * grid_size), Integer),
        grid_size - 1,
    )

    # Aggregate: count and sample track IDs per cell
    grid_query = (
        select(
            energy_cell.label("e_cell"),
            valence_cell.label("v_cell"),
            func.count().label("cnt"),
            # Collect up to 5 sample track IDs per cell
            array_agg(cast(latest_analysis.c.track_id, String)).label("sample_ids"),
        )
        .select_from(latest_analysis)
        .join(Track, Track.id == latest_analysis.c.track_id)
        .where(
            latest_analysis.c.rn == 1,
            Track.status == TrackStatus.ACTIVE,
            energy_expr.isnot(None),
            valence_expr.isnot(None),
        )
        .group_by(literal_column("e_cell"), literal_column("v_cell"))
    )

    result = await db.execute(grid_query)
    rows = result.all()

    # Count tracks with/without mood data
    total_with_mood = sum(row.cnt for row in rows)

    total_active = await db.scalar(
        select(func.count(Track.id)).where(Track.status == TrackStatus.ACTIVE)
    ) or 0
    total_without_mood = total_active - total_with_mood

    mood_cells = [
        MoodCell(
            energy_min=row.e_cell * cell_size,
            energy_max=(row.e_cell + 1) * cell_size,
            valence_min=row.v_cell * cell_size,
            valence_max=(row.v_cell + 1) * cell_size,
            track_count=row.cnt,
            sample_track_ids=row.sample_ids[:5] if row.sample_ids else [],
        )
        for row in rows
    ]

    return MoodDistributionResponse(
        cells=mood_cells,
        grid_size=grid_size,
        total_with_mood=total_with_mood,
        total_without_mood=total_without_mood,
    )


# ============================================================================
# Music Map (Embedding-based Similarity)
# ============================================================================


class MapNode(BaseModel):
    """A node in the music map."""

    id: str
    name: str
    x: float
    y: float
    track_count: int
    first_track_id: str


class MapEdge(BaseModel):
    """An edge connecting similar nodes."""

    source: str
    target: str
    weight: float


class MusicMapResponse(BaseModel):
    """Response for music map visualization."""

    nodes: list[MapNode]
    edges: list[MapEdge]
    entity_type: str
    total_entities: int


@router.get("/map", response_model=MusicMapResponse)
async def get_music_map(
    db: DbSession,
    entity_type: Literal["artists", "albums"] = "artists",
    limit: int = 200,
) -> MusicMapResponse:
    """Get 2D positions for artists/albums based on audio similarity.

    Uses UMAP dimensionality reduction on CLAP embeddings to position
    entities so that similar-sounding music appears close together.

    This is computationally expensive - results should be cached on the frontend.

    Args:
        entity_type: "artists" or "albums"
        limit: Maximum entities to include (default 200, max 500)
    """
    from app.services.embedding_map import get_embedding_map_service

    limit = min(limit, 500)  # Cap at 500 for performance

    service = get_embedding_map_service()

    try:
        map_data = await service.compute_map(db, entity_type=entity_type, limit=limit)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Required dependencies not available. Install umap-learn for map visualization.",
        )
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Failed to compute library map",
        )

    return MusicMapResponse(
        nodes=[
            MapNode(
                id=n.id,
                name=n.name,
                x=n.x,
                y=n.y,
                track_count=n.track_count,
                first_track_id=n.first_track_id,
            )
            for n in map_data.nodes
        ],
        edges=[
            MapEdge(source=e.source, target=e.target, weight=e.weight)
            for e in map_data.edges
        ],
        entity_type=entity_type,
        total_entities=len(map_data.nodes),
    )


@router.get("/map/stream")
async def get_music_map_stream(
    db: DbSession,
    entity_type: Literal["artists", "albums"] = "artists",
    limit: int = 200,
) -> StreamingResponse:
    """Stream music map computation progress via Server-Sent Events.

    Sends progress events during computation, then the complete map data.

    Event types:
    - progress: {"phase": "...", "progress": 0.5, "message": "..."}
    - complete: Full MusicMapResponse JSON
    - error: {"error": "..."}
    """
    import json

    from app.services.embedding_map import (
        MapData,
        MapProgress,
        get_embedding_map_service,
    )

    limit = min(limit, 500)  # Cap at 500 for performance

    async def event_stream():
        service = get_embedding_map_service()

        try:
            async for item in service.compute_map_with_progress(
                db, entity_type=entity_type, limit=limit
            ):
                if isinstance(item, MapProgress):
                    # Send progress event
                    data = {
                        "phase": item.phase,
                        "progress": item.progress,
                        "message": item.message,
                    }
                    yield f"event: progress\ndata: {json.dumps(data)}\n\n"
                elif isinstance(item, MapData):
                    # Send complete event with full map data
                    response = {
                        "nodes": [
                            {
                                "id": n.id,
                                "name": n.name,
                                "x": n.x,
                                "y": n.y,
                                "track_count": n.track_count,
                                "first_track_id": n.first_track_id,
                            }
                            for n in item.nodes
                        ],
                        "edges": [
                            {"source": e.source, "target": e.target, "weight": e.weight}
                            for e in item.edges
                        ],
                        "entity_type": entity_type,
                        "total_entities": len(item.nodes),
                    }
                    yield f"event: complete\ndata: {json.dumps(response)}\n\n"
        except ImportError as e:
            logger.warning(f"Map computation missing dependency: {e}")
            yield f"event: error\ndata: {json.dumps({'error': 'Required dependencies not available. Install umap-learn for map visualization.'})}\n\n"
        except Exception as e:
            logger.error(f"Map computation failed: {e}")
            yield f"event: error\ndata: {json.dumps({'error': 'Failed to compute library map. Please try again.'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


# ============================================================================
# Ego-Centric Music Map
# ============================================================================


class EgoMapCenterResponse(BaseModel):
    """Center artist of the ego map."""

    name: str
    track_count: int
    first_track_id: str


class EgoMapArtistResponse(BaseModel):
    """An artist in the ego-centric map."""

    name: str
    x: float
    y: float
    distance: float
    track_count: int
    first_track_id: str


class EgoMapResponse(BaseModel):
    """Response for ego-centric music map."""

    center: EgoMapCenterResponse
    artists: list[EgoMapArtistResponse]
    mode: str
    total_artists: int


class MapNode3DResponse(BaseModel):
    """A node in the 3D music map."""

    id: str
    name: str
    x: float
    y: float
    z: float
    track_count: int
    first_track_id: str


class MusicMap3DResponse(BaseModel):
    """Response for 3D music map visualization."""

    nodes: list[MapNode3DResponse]
    entity_type: str
    total_entities: int


@router.get("/map/3d", response_model=MusicMap3DResponse)
async def get_3d_music_map(
    db: DbSession,
    entity_type: Literal["artists", "albums"] = "artists",
) -> MusicMap3DResponse:
    """Get 3D positions for all artists/albums based on audio similarity.

    Uses UMAP dimensionality reduction on CLAP embeddings to position
    entities in 3D space so that similar-sounding music appears close together.

    Unlike the 2D map, this includes ALL entities in your library for full
    exploration. Results are cached for 1 hour due to expensive computation.

    Args:
        entity_type: "artists" (default) or "albums"
    """
    from app.services.embedding_map import get_embedding_map_service

    service = get_embedding_map_service()

    try:
        map_data = await service.compute_3d_map(db, entity_type=entity_type)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Required dependencies not available. Install umap-learn for map visualization.",
        )
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Failed to compute 3D library map",
        )

    return MusicMap3DResponse(
        nodes=[
            MapNode3DResponse(
                id=n.id,
                name=n.name,
                x=n.x,
                y=n.y,
                z=n.z,
                track_count=n.track_count,
                first_track_id=n.first_track_id,
            )
            for n in map_data.nodes
        ],
        entity_type=map_data.entity_type,
        total_entities=map_data.total_entities,
    )


@router.get("/map/3d/stream")
async def get_3d_music_map_stream(
    db: DbSession,
    entity_type: Literal["artists", "albums"] = "artists",
) -> StreamingResponse:
    """Stream 3D music map computation progress via Server-Sent Events.

    Sends progress events during computation, then the complete map data.
    Use this for better UX during the initial (slow) UMAP computation.

    Event types:
    - progress: {"phase": "...", "progress": 0.5, "message": "..."}
    - complete: Full MusicMap3DResponse JSON
    - error: {"error": "..."}
    """
    import json

    from app.services.embedding_map import (
        MapData3D,
        MapProgress,
        get_embedding_map_service,
    )

    async def event_stream():
        service = get_embedding_map_service()

        try:
            async for item in service.compute_3d_map_with_progress(
                db, entity_type=entity_type
            ):
                if isinstance(item, MapProgress):
                    # Send progress event
                    data = {
                        "phase": item.phase,
                        "progress": item.progress,
                        "message": item.message,
                    }
                    yield f"event: progress\ndata: {json.dumps(data)}\n\n"
                elif isinstance(item, MapData3D):
                    # Send complete event with full map data
                    response = {
                        "nodes": [
                            {
                                "id": n.id,
                                "name": n.name,
                                "x": n.x,
                                "y": n.y,
                                "z": n.z,
                                "track_count": n.track_count,
                                "first_track_id": n.first_track_id,
                            }
                            for n in item.nodes
                        ],
                        "entity_type": item.entity_type,
                        "total_entities": item.total_entities,
                    }
                    yield f"event: complete\ndata: {json.dumps(response)}\n\n"
        except ImportError as e:
            logger.warning(f"3D map computation missing dependency: {e}")
            yield f"event: error\ndata: {json.dumps({'error': 'Required dependencies not available. Install umap-learn for map visualization.'})}\n\n"
        except Exception as e:
            logger.error(f"3D map computation failed: {e}")
            yield f"event: error\ndata: {json.dumps({'error': 'Failed to compute 3D library map. Please try again.'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/map/ego")
async def get_ego_centric_map(
    db: DbSession,
    center: str = Query(..., description="Artist name to center on"),
    limit: int = Query(200, ge=10, le=500, description="Number of similar artists"),
    mode: Literal["radial"] = Query("radial", description="Layout mode"),
) -> EgoMapResponse:
    """Get ego-centric map centered on an artist.

    Returns the center artist and surrounding artists positioned radially
    based on audio similarity. Distance from center indicates dissimilarity.

    The angle of each artist is stable (based on name hash), so when you
    recenter on a different artist, positions smoothly transition rather
    than completely reshuffling.
    """
    from app.services.ego_map import get_ego_map_service

    service = get_ego_map_service()

    try:
        data = await service.compute_ego_map(db, center=center, limit=limit, mode=mode)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=sanitize_error_for_client(e, "Artist not found"))

    return EgoMapResponse(
        center=EgoMapCenterResponse(
            name=data.center.name,
            track_count=data.center.track_count,
            first_track_id=data.center.first_track_id,
        ),
        artists=[
            EgoMapArtistResponse(
                name=a.name,
                x=a.x,
                y=a.y,
                distance=a.distance,
                track_count=a.track_count,
                first_track_id=a.first_track_id,
            )
            for a in data.artists
        ],
        mode=data.mode,
        total_artists=data.total_artists,
    )


# ============================================================================
# Library Stats
# ============================================================================


@router.get("/stats", response_model=LibraryStats)
async def get_library_stats(db: DbSession) -> LibraryStats:
    """Get library statistics in a single query using conditional aggregation."""
    from sqlalchemy import case

    from app.config import ANALYSIS_VERSION

    result = await db.execute(
        select(
            func.count(Track.id).label("total_tracks"),
            func.count(func.distinct(Track.album)).label("total_albums"),
            func.count(func.distinct(Track.artist)).label("total_artists"),
            func.sum(case((Track.album_type == AlbumType.ALBUM, 1), else_=0)).label("albums"),
            func.sum(case((Track.album_type == AlbumType.COMPILATION, 1), else_=0)).label("compilations"),
            func.sum(case((Track.album_type == AlbumType.SOUNDTRACK, 1), else_=0)).label("soundtracks"),
            func.sum(case((Track.analysis_version >= ANALYSIS_VERSION, 1), else_=0)).label("analyzed"),
        )
    )
    row = result.one()

    total_tracks = row.total_tracks or 0
    analyzed_tracks = row.analyzed or 0

    return LibraryStats(
        total_tracks=total_tracks,
        total_albums=row.total_albums or 0,
        total_artists=row.total_artists or 0,
        albums=row.albums or 0,
        compilations=row.compilations or 0,
        soundtracks=row.soundtracks or 0,
        analyzed_tracks=analyzed_tracks,
        pending_analysis=total_tracks - analyzed_tracks,
    )


# ============================================================================
# Letter Index (for Alphabet Bar navigation)
# ============================================================================


class LetterIndexResponse(BaseModel):
    """Letter index for alphabet bar navigation."""

    letters: dict[str, int]  # {"A": 0, "B": 47, "C": 123, "#": 500}
    total: int


@router.get("/letter-index", response_model=LetterIndexResponse)
async def get_letter_index(
    db: DbSession,
    entity_type: Literal["tracks", "artists", "albums"] = "tracks",
    sort_field: str = "artist",  # tracks: artist/album/title, artists: name, albums: name/artist
    search: str | None = None,
    artist: str | None = None,
    album: str | None = None,
) -> LetterIndexResponse:
    """Get letter→index mapping for alphabet bar navigation.

    Returns the first occurrence index for each letter in the sorted list,
    allowing fast jumping to items starting with that letter.

    Non-alphabetic characters (numbers, symbols) map to '#'.

    Args:
        entity_type: What to index - 'tracks', 'artists', or 'albums'
        sort_field: Field to sort/index by
        search: Optional search filter
        artist: Filter by artist (for tracks/albums)
        album: Filter by album (for tracks only)
    """
    from sqlalchemy import case

    letters: dict[str, int] = {}
    total = 0

    if entity_type == "tracks":
        # Determine sort column based on sort_field
        if sort_field == "album":
            sort_col = func.coalesce(Track.album, "")
        elif sort_field == "title":
            sort_col = func.coalesce(Track.title, "")
        else:  # Default to artist
            sort_col = func.coalesce(Track.artist, "")

        # Build base query with filters
        base_filter = [Track.status == TrackStatus.ACTIVE]
        if search:
            search_lower = f"%{search.lower()}%"
            base_filter.append(
                (func.lower(Track.title).like(search_lower))
                | (func.lower(Track.artist).like(search_lower))
                | (func.lower(Track.album).like(search_lower))
            )
        if artist:
            base_filter.append(func.lower(Track.artist) == artist.lower())
        if album:
            base_filter.append(func.lower(Track.album) == album.lower())

        # Get total count
        count_query = select(func.count(Track.id)).where(*base_filter)
        total = await db.scalar(count_query) or 0

        # Extract first letter, normalize to uppercase, map non-alpha to '#'
        first_char = func.upper(func.substring(sort_col, 1, 1))
        letter_expr = case(
            (func.substring(first_char, 1, 1).op("~")("[A-Z]"), first_char),
            else_="#",
        )

        # Build subquery with row numbers
        row_num_query = (
            select(
                letter_expr.label("letter"),
                func.row_number()
                .over(order_by=[func.lower(sort_col), Track.album, Track.track_number])
                .label("row_num"),
            )
            .where(*base_filter)
            .subquery()
        )

        # Get first index for each letter
        letter_query = (
            select(
                row_num_query.c.letter,
                func.min(row_num_query.c.row_num).label("first_index"),
            )
            .group_by(row_num_query.c.letter)
            .order_by(row_num_query.c.letter)
        )

        result = await db.execute(letter_query)
        for row in result.all():
            # Convert to 0-based index
            letters[row.letter] = row.first_index - 1

    elif entity_type == "artists":
        # Sort by artist name
        sort_col = func.coalesce(func.max(Track.artist), "")  # Pick canonical display name
        artist_normalized = func.lower(Track.artist)

        # Build base filter
        base_filter = [
            Track.artist.isnot(None),
            Track.artist != "",
            Track.status == TrackStatus.ACTIVE,
        ]
        if search:
            base_filter.append(func.lower(Track.artist).contains(search.lower()))

        # Get total count
        count_query = (
            select(func.count(func.distinct(artist_normalized)))
            .select_from(Track)
            .where(*base_filter)
        )
        total = await db.scalar(count_query) or 0

        # Subquery to get distinct artists with row numbers
        artist_subquery = (
            select(
                func.max(Track.artist).label("name"),
                artist_normalized.label("artist_normalized"),
            )
            .where(*base_filter)
            .group_by(artist_normalized)
            .subquery()
        )

        # Add row numbers
        first_char = func.upper(func.substring(artist_subquery.c.name, 1, 1))
        letter_expr = case(
            (func.substring(first_char, 1, 1).op("~")("[A-Z]"), first_char),
            else_="#",
        )

        row_num_query = (
            select(
                letter_expr.label("letter"),
                func.row_number()
                .over(order_by=artist_subquery.c.artist_normalized)
                .label("row_num"),
            )
            .select_from(artist_subquery)
            .subquery()
        )

        # Get first index for each letter
        letter_query = (
            select(
                row_num_query.c.letter,
                func.min(row_num_query.c.row_num).label("first_index"),
            )
            .group_by(row_num_query.c.letter)
            .order_by(row_num_query.c.letter)
        )

        result = await db.execute(letter_query)
        for row in result.all():
            letters[row.letter] = row.first_index - 1

    elif entity_type == "albums":
        # Determine sort column
        album_artist_col = func.coalesce(func.nullif(Track.album_artist, ""), Track.artist)
        if sort_field == "artist":
            sort_col = album_artist_col
        else:  # Default to album name
            sort_col = func.coalesce(Track.album, "")

        # Build base filter
        base_filter = [
            Track.album.isnot(None),
            Track.album != "",
            Track.status == TrackStatus.ACTIVE,
        ]
        if search:
            search_lower = f"%{search.lower()}%"
            base_filter.append(
                (func.lower(Track.album).like(search_lower))
                | (func.lower(album_artist_col).like(search_lower))
            )
        if artist:
            base_filter.append(func.lower(album_artist_col) == artist.lower())

        # Subquery to get distinct albums
        album_artist_lower = func.lower(album_artist_col)
        album_lower = func.lower(Track.album)
        album_subquery = (
            select(
                func.max(Track.album).label("album_name"),
                func.max(album_artist_col).label("artist_name"),
                album_lower.label("album_normalized"),
                album_artist_lower.label("artist_normalized"),
            )
            .where(*base_filter)
            .group_by(album_artist_lower, album_lower)
            .subquery()
        )

        # Get total count
        count_query = select(func.count()).select_from(album_subquery)
        total = await db.scalar(count_query) or 0

        # Determine which column to use for letter extraction
        if sort_field == "artist":
            name_col = album_subquery.c.artist_name
            order_col = album_subquery.c.artist_normalized
        else:
            name_col = album_subquery.c.album_name
            order_col = album_subquery.c.album_normalized

        first_char = func.upper(func.substring(name_col, 1, 1))
        letter_expr = case(
            (func.substring(first_char, 1, 1).op("~")("[A-Z]"), first_char),
            else_="#",
        )

        row_num_query = (
            select(
                letter_expr.label("letter"),
                func.row_number().over(order_by=order_col).label("row_num"),
            )
            .select_from(album_subquery)
            .subquery()
        )

        # Get first index for each letter
        letter_query = (
            select(
                row_num_query.c.letter,
                func.min(row_num_query.c.row_num).label("first_index"),
            )
            .group_by(row_num_query.c.letter)
            .order_by(row_num_query.c.letter)
        )

        result = await db.execute(letter_query)
        for row in result.all():
            letters[row.letter] = row.first_index - 1

    return LetterIndexResponse(letters=letters, total=total)


class CancelResponse(BaseModel):
    """Response for cancel operations."""

    status: str
    message: str


@router.post("/analysis/cancel", response_model=CancelResponse)
async def cancel_analysis() -> CancelResponse:
    """Cancel running analysis tasks.

    Clears analysis task tracking. Note that in-progress subprocess tasks
    may continue to completion, but no new tasks will be started.
    """
    from app.services.background import get_background_manager

    bg = get_background_manager()

    # Cancel all running analysis tasks
    cancelled = 0
    for task_id, task in list(bg._analysis_tasks.items()):
        if not task.done():
            task.cancel()
            cancelled += 1
        bg._analysis_tasks.pop(task_id, None)

    return CancelResponse(
        status="cancelled",
        message=f"Cancelled {cancelled} analysis tasks",
    )


# ============================================================================
# Unified Sync Endpoints
# ============================================================================


@router.post("/sync", response_model=SyncStatus)
@limiter.limit(SCAN_RATE_LIMIT)
async def start_sync(
    request: Request,
    reread_unchanged: bool = False,
) -> SyncStatus:
    """Start a unified library sync (scan + analysis).

    This is the recommended way to sync your library. It:
    1. Discovers audio files in your library paths
    2. Reads metadata from new/changed files
    3. Analyzes audio features for new tracks

    The sync runs in the background, so this returns immediately.
    Progress is stored in Redis and can be retrieved via GET /sync/status.

    Args:
        reread_unchanged: Re-read metadata for files even if unchanged. Default False.
    """
    from app.services.background import get_background_manager

    bg = get_background_manager()

    # Check if a sync is already running
    if bg.is_sync_running():
        progress = get_sync_progress()
        if progress:
            return SyncStatus(
                status="already_running",
                message="A sync is already in progress",
                progress=SyncProgress(**{
                    k: progress.get(k, v)
                    for k, v in SyncProgress().model_dump().items()
                }),
            )
        return SyncStatus(
            status="already_running",
            message="A sync is already in progress",
        )

    # Start sync in background
    await bg.run_sync(reread_unchanged=reread_unchanged)

    return SyncStatus(
        status="started",
        message="Library sync started",
    )


@router.get("/sync/status", response_model=SyncStatus)
async def get_sync_status_endpoint() -> SyncStatus:
    """Get current sync status with unified progress.

    Returns progress through all phases:
    - discovering: Finding audio files
    - reading: Reading metadata from files
    - analyzing: Extracting audio features
    - complete: Sync finished
    """
    from datetime import datetime, timedelta

    from app.services.tasks import clear_sync_progress

    progress = get_sync_progress()

    if not progress:
        return SyncStatus(
            status="idle",
            message="No sync running",
            progress=None,
        )

    # Check if the sync is stale (no heartbeat for 5 minutes)
    status = progress.get("status", "idle")
    if status == "running":
        last_heartbeat = progress.get("last_heartbeat")
        if last_heartbeat:
            try:
                heartbeat_time = datetime.fromisoformat(last_heartbeat)
                if datetime.now() - heartbeat_time > timedelta(minutes=5):
                    clear_sync_progress()
                    return SyncStatus(
                        status="error",
                        message="Sync was interrupted (worker stopped responding)",
                        progress=None,
                    )
            except (ValueError, TypeError):
                pass

    # Convert Redis progress to SyncProgress model
    sync_progress = SyncProgress(
        phase=progress.get("phase", "idle"),
        phase_message=progress.get("phase_message", ""),
        files_discovered=progress.get("files_discovered", 0),
        files_processed=progress.get("files_processed", 0),
        files_total=progress.get("files_total", 0),
        new_tracks=progress.get("new_tracks", 0),
        updated_tracks=progress.get("updated_tracks", 0),
        unchanged_tracks=progress.get("unchanged_tracks", 0),
        relocated_tracks=progress.get("relocated_tracks", 0),
        marked_missing=progress.get("marked_missing", 0),
        recovered=progress.get("recovered", 0),
        tracks_analyzed=progress.get("tracks_analyzed", 0),
        tracks_pending_analysis=progress.get("tracks_pending_analysis", 0),
        tracks_total=progress.get("tracks_total", 0),
        analysis_percent=progress.get("analysis_percent", 0.0),
        started_at=progress.get("started_at"),
        current_item=progress.get("current_item"),
        last_heartbeat=progress.get("last_heartbeat"),
        errors=progress.get("errors", []),
    )

    return SyncStatus(
        status=status,
        message=progress.get("phase_message", ""),
        progress=sync_progress if status != "idle" else None,
    )


@router.post("/sync/cancel", response_model=CancelResponse)
async def cancel_sync() -> CancelResponse:
    """Cancel a running library sync.

    Clears the sync progress from Redis and releases the lock.
    """
    from app.services.background import get_background_manager
    from app.services.tasks import clear_sync_progress

    bg = get_background_manager()

    # Cancel the sync task and release lock
    bg._cancel_sync()
    clear_sync_progress()

    return CancelResponse(
        status="cancelled",
        message="Sync cancelled and state cleared",
    )


class ImportResult(BaseModel):
    """Import operation result."""
    status: str
    message: str
    import_path: str | None = None
    files_found: int = 0
    files: list[str] = []


class RecentImport(BaseModel):
    """Recent import directory info."""
    name: str
    path: str
    file_count: int
    created_at: str | None


@router.post("/import", response_model=ImportResult)
async def import_music(
    db: DbSession,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> ImportResult:
    """Import music from a zip file or audio file.

    Accepts:
    - Zip files containing audio (extracts and imports)
    - Individual audio files (mp3, flac, m4a, etc.)

    Files are saved to {MUSIC_LIBRARY_PATH}/_imports/{timestamp}/
    and automatically scanned for metadata.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Read uploaded file
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Save to temp file
    try:
        temp_path = save_upload_to_temp(content, file.filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")

    # Process the import
    try:
        import_service = ImportService()
        result = import_service.process_upload(temp_path, file.filename)

        # Schedule scan of the import directory
        import_dir = Path(result["import_path"])

        async def scan_import():
            # Create new db session for background task (request session is closed)
            from app.db.session import async_session_maker
            async with async_session_maker() as bg_db:
                try:
                    scanner = LibraryScanner(bg_db)
                    await scanner.scan(import_dir, full_scan=True)
                    await bg_db.commit()
                except Exception as e:
                    await bg_db.rollback()
                    import logging
                    logging.getLogger(__name__).error(f"Background scan failed: {e}")

        background_tasks.add_task(scan_import)

        return ImportResult(
            status="processing",
            message=f"Imported {result['files_found']} files, scanning for metadata...",
            import_path=result["import_path"],
            files_found=result["files_found"],
            files=result.get("files", []),
        )

    except MusicImportError as e:
        raise HTTPException(status_code=400, detail=sanitize_error_for_client(e, "Import failed"))
    except Exception:
        raise HTTPException(status_code=500, detail="Import failed")
    finally:
        # Clean up temp file
        temp_path.unlink(missing_ok=True)


@router.get("/imports/recent", response_model=list[RecentImport])
async def get_recent_imports(limit: int = 10) -> list[RecentImport]:
    """Get list of recent import directories."""
    import_service = ImportService()
    imports = import_service.get_recent_imports(limit)
    return [RecentImport(**i) for i in imports]


# ============================================================================
# Enhanced Import with Preview
# ============================================================================


class ImportTrackPreview(BaseModel):
    """Preview info for a single track."""
    filename: str
    relative_path: str
    detected_artist: str | None
    detected_album: str | None
    detected_title: str | None
    detected_track_num: int | None
    detected_year: int | None = None
    format: str
    duration_seconds: float | None
    file_size_bytes: int
    sample_rate: int | None = None
    bit_depth: int | None = None
    bitrate: int | None = None
    bitrate_mode: str | None = None  # "CBR", "VBR", or None
    # Duplicate detection
    duplicate_of: str | None = None  # ID of existing track if duplicate found
    duplicate_info: str | None = None  # e.g. "Artist - Album - Title"
    # Quality comparison (for duplicates)
    trump_status: str | None = None  # "trumps", "trumped_by", "equal"
    trump_reason: str | None = None  # Human-readable comparison reason
    incoming_quality: dict | None = None  # Quality info for incoming track
    existing_quality: dict | None = None  # Quality info for existing track
    duplicate_match_type: str | None = None  # "exact", "normalized", "artist_title"


class ImportPreviewResponse(BaseModel):
    """Response from import preview endpoint."""
    session_id: str
    tracks: list[ImportTrackPreview]
    total_size_bytes: int
    estimated_sizes: dict[str, int]
    has_convertible_formats: bool


class ImportTrackInput(BaseModel):
    """User-edited track metadata for import."""
    filename: str | None = None
    relative_path: str | None = None
    artist: str | None = None
    album: str | None = None
    title: str | None = None
    track_num: int | None = None
    year: int | None = None
    # Pass through detected values if not edited
    detected_artist: str | None = None
    detected_album: str | None = None
    detected_title: str | None = None
    detected_track_num: int | None = None
    detected_year: int | None = None
    # Quality-based replacement
    action: str = "import"  # "import", "replace", "skip"
    replace_track_id: str | None = None  # Track ID to replace (for action="replace")


class ImportOptions(BaseModel):
    """Import execution options."""
    format: str = "original"  # "original", "flac", "mp3"
    mp3_quality: int = 320  # 128, 192, 320
    organization: str = "imports"  # "organized" or "imports"
    duplicate_handling: str = "rename"  # "skip", "replace", "rename"
    queue_analysis: bool = True


class ImportExecuteRequest(BaseModel):
    """Request body for import execution."""
    session_id: str
    tracks: list[ImportTrackInput]
    options: ImportOptions


class ImportExecuteResponse(BaseModel):
    """Response from import execute endpoint."""
    status: str
    imported_count: int
    replaced_count: int = 0  # Count of tracks that replaced existing ones
    imported_files: list[str]
    errors: list[str]
    base_path: str
    queue_analysis: bool


async def _find_import_duplicate(
    db: "AsyncSession",
    artist: str,
    album: str,
    title: str,
) -> tuple["Track | None", str]:
    """Multi-phase duplicate detection for import preview.

    Returns (matching_track, match_type) where match_type is one of:
    "exact", "normalized", "artist_title", or "" if no match.
    """
    from sqlalchemy import func, select

    from app.db.models import Track
    from app.services.normalize import normalize_for_duplicate_matching

    # Phase 1: Exact case-insensitive match (artist + album + title)
    if album:
        stmt = (
            select(Track)
            .where(
                func.lower(Track.artist) == artist.lower(),
                func.lower(Track.album) == album.lower(),
                func.lower(Track.title) == title.lower(),
            )
            .limit(1)
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            return existing, "exact"

    # Phase 2: Fetch candidates by artist variants for fuzzy matching
    artist_lower = artist.lower()
    artist_variants = [artist_lower]

    # Add with/without leading articles
    for article in ("the ", "a ", "an "):
        if artist_lower.startswith(article):
            artist_variants.append(artist_lower[len(article):])
        else:
            artist_variants.append(article + artist_lower)

    stmt = (
        select(Track)
        .where(func.lower(Track.artist).in_(artist_variants))
    )
    candidates = (await db.execute(stmt)).scalars().all()

    if not candidates:
        return None, ""

    # Phase 3: Normalized artist + album + title
    norm_artist = normalize_for_duplicate_matching(artist, strip_articles=True)
    norm_album = normalize_for_duplicate_matching(album)
    norm_title = normalize_for_duplicate_matching(title)

    if norm_album:
        for candidate in candidates:
            if (
                normalize_for_duplicate_matching(candidate.artist, strip_articles=True) == norm_artist
                and normalize_for_duplicate_matching(candidate.album) == norm_album
                and normalize_for_duplicate_matching(candidate.title) == norm_title
            ):
                return candidate, "normalized"

    # Phase 4: Artist + title only (no album requirement)
    for candidate in candidates:
        if (
            normalize_for_duplicate_matching(candidate.artist, strip_articles=True) == norm_artist
            and normalize_for_duplicate_matching(candidate.title) == norm_title
        ):
            return candidate, "artist_title"

    return None, ""


@router.post("/import/preview", response_model=ImportPreviewResponse)
async def import_preview(
    db: DbSession,
    file: UploadFile = File(...),
) -> ImportPreviewResponse:
    """Preview an import - extract and scan files without importing.

    Uploads file to temp location, extracts if zip, scans metadata,
    and returns preview with session_id for later execution.

    Session expires after 24 hours if not executed.
    """
    from app.services.import_service import (
        ImportPreviewService,
        MusicImportError,
        save_upload_to_temp,
    )

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Read uploaded file
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Save to temp file
    try:
        temp_path = save_upload_to_temp(content, file.filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")

    try:
        from app.services.quality import calculate_quality_score, compare_quality

        preview_service = ImportPreviewService()
        result = preview_service.create_preview_session(temp_path, file.filename)

        # Check for duplicates in the library and compare quality
        tracks = result["tracks"]
        for track in tracks:
            artist = track.get("detected_artist") or ""
            album = track.get("detected_album") or ""
            title = track.get("detected_title") or ""

            # Only check if we have enough metadata to match
            if artist and title:
                existing, match_type = await _find_import_duplicate(
                    db, artist, album, title
                )

                if existing:
                    track["duplicate_of"] = str(existing.id)
                    track["duplicate_info"] = (
                        f"{existing.artist} - {existing.album} - {existing.title}"
                    )
                    track["duplicate_match_type"] = match_type

                    # Calculate quality scores and compare
                    incoming_score = calculate_quality_score(
                        format=track.get("format"),
                        bitrate=track.get("bitrate"),
                        sample_rate=track.get("sample_rate"),
                        bit_depth=track.get("bit_depth"),
                        bitrate_mode=track.get("bitrate_mode"),
                    )
                    existing_score = calculate_quality_score(
                        format=existing.format,
                        bitrate=existing.bitrate,
                        sample_rate=existing.sample_rate,
                        bit_depth=existing.bit_depth,
                        bitrate_mode=existing.bitrate_mode,
                    )

                    trump_status, trump_reason = compare_quality(
                        incoming_score, existing_score
                    )
                    track["trump_status"] = trump_status
                    track["trump_reason"] = trump_reason
                    track["incoming_quality"] = incoming_score.to_dict()
                    track["existing_quality"] = existing_score.to_dict()

        return ImportPreviewResponse(
            session_id=result["session_id"],
            tracks=[ImportTrackPreview(**t) for t in tracks],
            total_size_bytes=result["total_size_bytes"],
            estimated_sizes=result["estimated_sizes"],
            has_convertible_formats=result["has_convertible_formats"],
        )

    except MusicImportError as e:
        raise HTTPException(status_code=400, detail=sanitize_error_for_client(e, "Preview failed"))
    except Exception:
        raise HTTPException(status_code=500, detail="Preview failed")
    finally:
        # Clean up temp file (session has its own copy)
        temp_path.unlink(missing_ok=True)


@router.post("/import/execute", response_model=ImportExecuteResponse)
async def import_execute(
    db: DbSession,
    background_tasks: BackgroundTasks,
    request: ImportExecuteRequest,
) -> ImportExecuteResponse:
    """Execute an import with user-specified options.

    Uses session_id from preview to access uploaded files.
    Applies user-edited metadata and conversion options.
    """
    from pathlib import Path
    from uuid import UUID

    from app.db.models import Track
    from app.services.import_service import ImportExecuteService, MusicImportError
    from app.services.metadata import extract_metadata
    from app.services.scanner import compute_file_hash

    try:
        execute_service = ImportExecuteService()
        result = execute_service.execute_import(
            session_id=request.session_id,
            tracks=[t.model_dump() for t in request.tracks],
            options=request.options.model_dump(),
        )

        # Handle track replacements - update existing tracks to point to new files
        replaced_tracks = result.get("replaced_tracks", [])
        replaced_count = 0
        for replacement in replaced_tracks:
            try:
                track_id = UUID(replacement["track_id"])
                new_file_path = Path(replacement["new_file_path"])

                # Get the existing track
                existing = await db.get(Track, track_id)
                if not existing:
                    result["errors"].append(f"Track to replace not found: {track_id}")
                    continue

                # Delete the old file if it exists
                old_path = Path(existing.file_path)
                if old_path.exists():
                    old_path.unlink()

                # Update track with new file info
                existing.file_path = str(new_file_path)

                # Calculate new file hash (must match scanner's partial-hash scheme)
                existing.file_hash = compute_file_hash(new_file_path)

                # Extract metadata from new file
                metadata = extract_metadata(new_file_path)
                existing.format = metadata.get("format")
                existing.bitrate = metadata.get("bitrate")
                existing.bitrate_mode = metadata.get("bitrate_mode")
                existing.sample_rate = metadata.get("sample_rate")
                existing.bit_depth = metadata.get("bit_depth")
                existing.duration_seconds = metadata.get("duration_seconds")

                # Reset analysis to trigger re-analysis
                existing.analysis_version = 0
                existing.analyzed_at = None

                replaced_count += 1

            except Exception as e:
                result["errors"].append(f"Failed to replace track: {e}")

        # Commit replacement changes
        if replaced_count > 0:
            await db.commit()
            # Adjust imported count to not double-count replacements
            result["imported_count"] = result["imported_count"] - replaced_count
            result["replaced_count"] = replaced_count

        # Schedule scan of imported files if requested
        # Use specific scan_paths to avoid scanning entire library
        scan_paths = result.get("scan_paths", [])
        if result["queue_analysis"] and scan_paths and settings.music_library_paths:
            from app.db.session import async_session_maker
            from app.services.scanner import LibraryScanner

            library_root = Path(settings.music_library_paths[0])

            async def scan_import():
                # Create new db session for background task (request session is closed)
                async with async_session_maker() as bg_db:
                    try:
                        scanner = LibraryScanner(bg_db)
                        for rel_path in scan_paths:
                            scan_dir = library_root / rel_path
                            if scan_dir.exists():
                                await scanner.scan(scan_dir, full_scan=True)
                        await bg_db.commit()
                    except Exception as e:
                        await bg_db.rollback()
                        import logging
                        logging.getLogger(__name__).error(f"Background scan failed: {e}")

            background_tasks.add_task(scan_import)

        return ImportExecuteResponse(**result)

    except MusicImportError as e:
        raise HTTPException(status_code=400, detail=sanitize_error_for_client(e, "Import failed"))
    except Exception:
        raise HTTPException(status_code=500, detail="Import failed")


class AnalysisStatus(BaseModel):
    """Analysis status response."""

    status: str  # "idle", "running", "stuck", "error"
    total: int = 0
    analyzed: int = 0
    pending: int = 0
    failed: int = 0
    percent: float = 0.0
    current_file: str | None = None
    error: str | None = None
    heartbeat: str | None = None
    # Embedding coverage - helps detect silent failures
    with_embeddings: int = 0
    without_embeddings: int = 0
    embeddings_enabled: bool = True
    embeddings_disabled_reason: str | None = None


@router.get("/analysis/status", response_model=AnalysisStatus)
async def get_analysis_status(db: DbSession) -> AnalysisStatus:
    """Get current audio analysis status with stuck detection.

    Returns analysis progress and detects if the worker has stalled.
    Also reports embedding coverage to help detect silent failures.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import or_

    from app.config import ANALYSIS_VERSION
    from app.services.analysis import get_analysis_capabilities

    # Get analysis capabilities
    caps = get_analysis_capabilities()

    # Get counts from database
    total = await db.scalar(select(func.count(Track.id))) or 0
    analyzed = await db.scalar(
        select(func.count(Track.id)).where(Track.analysis_version >= ANALYSIS_VERSION)
    ) or 0
    failed = await db.scalar(
        select(func.count(Track.id)).where(Track.analysis_failed_at.isnot(None))
    ) or 0

    # Count tracks with/without embeddings
    with_embeddings = await db.scalar(
        select(func.count(TrackAnalysis.id)).where(TrackAnalysis.embedding.isnot(None))
    ) or 0
    without_embeddings = analyzed - with_embeddings

    # Pending = not analyzed and not recently failed
    failure_cutoff = datetime.utcnow() - timedelta(hours=24)
    pending = await db.scalar(
        select(func.count(Track.id)).where(
            Track.analysis_version < ANALYSIS_VERSION,
            or_(
                Track.analysis_failed_at.is_(None),
                Track.analysis_failed_at < failure_cutoff,
            ),
        )
    ) or 0

    percent = (analyzed / total * 100) if total > 0 else 100.0

    # Common fields for all responses
    common = {
        "total": total,
        "analyzed": analyzed,
        "pending": pending,
        "failed": failed,
        "percent": round(percent, 1),
        "with_embeddings": with_embeddings,
        "without_embeddings": without_embeddings,
        "embeddings_enabled": caps["embeddings_enabled"],
        "embeddings_disabled_reason": caps["embeddings_disabled_reason"],
    }

    # Check if background analysis tasks are running
    from app.services.background import get_background_manager

    bg = get_background_manager()
    active_tasks = bg.get_analysis_task_count()

    if active_tasks > 0:
        return AnalysisStatus(
            status="running",
            current_file=f"Processing {active_tasks} tracks...",
            **common,
        )

    # No active analysis tasks - check if there's pending work
    if pending > 0:
        return AnalysisStatus(status="idle", **common)

    # Override percent to 100 for complete status
    common["percent"] = 100.0
    return AnalysisStatus(status="complete", **common)


class AnalysisStartResponse(BaseModel):
    """Response for starting analysis."""

    status: str
    queued: int = 0
    message: str


class ExecutorStatus(BaseModel):
    """Process pool executor status."""

    disabled: bool
    consecutive_failures: int
    max_failures: int
    crashed_track_ids: list[str]
    last_reset_ago: float | None


class ExecutorResetResponse(BaseModel):
    """Response from resetting the executor."""

    status: str
    was_disabled: bool
    previous_failure_count: int
    crashed_track_ids: list[str]


@router.get("/analysis/executor", response_model=ExecutorStatus)
async def get_executor_status() -> ExecutorStatus:
    """Get process pool executor status.

    Returns whether the executor is disabled (circuit breaker tripped),
    the number of consecutive failures, and which tracks caused crashes.
    """
    from app.services.background import get_background_manager

    bg = get_background_manager()
    status = bg.get_executor_status()

    return ExecutorStatus(**status)


@router.post("/analysis/executor/reset", response_model=ExecutorResetResponse)
async def reset_executor() -> ExecutorResetResponse:
    """Reset the process pool executor circuit breaker.

    Use this to recover from a disabled executor without restarting the container.
    The circuit breaker trips after 5 consecutive worker crashes.

    Returns info about what was reset, including which tracks caused crashes.
    """
    from app.services.background import get_background_manager

    bg = get_background_manager()
    result = bg.reset_executor_circuit_breaker()

    return ExecutorResetResponse(**result)


@router.post("/analysis/start", response_model=AnalysisStartResponse)
async def start_analysis(limit: int = 500) -> AnalysisStartResponse:
    """Manually trigger analysis for unanalyzed tracks.

    This queues tracks for analysis in the background. Use GET /analysis/status
    to monitor progress.

    Scans and analysis cannot run simultaneously - they share resources.
    """
    from app.services.background import get_background_manager
    from app.services.tasks import queue_unanalyzed_tracks

    bg = get_background_manager()

    # Check if sync is running - can't run both simultaneously
    if bg.is_sync_running():
        raise HTTPException(
            status_code=409,
            detail="Cannot start analysis while a sync is running. Cancel sync first or wait for it to complete.",
        )

    try:
        queued = await queue_unanalyzed_tracks(limit=limit)
        if queued == 0:
            return AnalysisStartResponse(
                status="complete",
                queued=0,
                message="All tracks are already analyzed",
            )
        return AnalysisStartResponse(
            status="started",
            queued=queued,
            message=f"Queued {queued} tracks for analysis",
        )
    except Exception as e:
        return AnalysisStartResponse(
            status="error",
            queued=0,
            message=f"Failed to start analysis: {e}",
        )


# ============================================================================
# Missing Tracks API
# ============================================================================


class MissingTrack(BaseModel):
    """Missing track info for user review."""

    id: str
    title: str | None
    artist: str | None
    album: str | None
    file_path: str
    status: str  # "missing" or "pending_deletion"
    missing_since: str | None
    days_missing: int


class MissingTracksResponse(BaseModel):
    """List of missing tracks."""

    tracks: list[MissingTrack]
    total_missing: int
    total_pending_deletion: int


class RelocateRequest(BaseModel):
    """Request to search a folder for missing files."""

    search_path: str


class RelocateResult(BaseModel):
    """Result of batch relocation."""

    found: int
    not_found: int
    relocated_tracks: list[dict]


class LocateRequest(BaseModel):
    """Request to manually set new path for a track."""

    new_path: str


class BatchDeleteRequest(BaseModel):
    """Request to delete multiple tracks."""

    track_ids: list[str]


@router.get("/missing", response_model=MissingTracksResponse)
async def get_missing_tracks(db: DbSession) -> MissingTracksResponse:
    """Get all tracks with MISSING or PENDING_DELETION status."""
    from datetime import datetime

    result = await db.execute(
        select(Track).where(
            Track.status.in_([TrackStatus.MISSING, TrackStatus.PENDING_DELETION])
        ).order_by(Track.missing_since.desc())
    )
    tracks = result.scalars().all()

    now = datetime.now()
    missing_tracks = []
    total_missing = 0
    total_pending = 0

    for track in tracks:
        days_missing = 0
        if track.missing_since:
            days_missing = (now - track.missing_since).days

        if track.status == TrackStatus.MISSING:
            total_missing += 1
        else:
            total_pending += 1

        missing_tracks.append(
            MissingTrack(
                id=str(track.id),
                title=track.title,
                artist=track.artist,
                album=track.album,
                file_path=track.file_path,
                status=track.status.value,
                missing_since=track.missing_since.isoformat() if track.missing_since else None,
                days_missing=days_missing,
            )
        )

    return MissingTracksResponse(
        tracks=missing_tracks,
        total_missing=total_missing,
        total_pending_deletion=total_pending,
    )


@router.post("/missing/relocate", response_model=RelocateResult)
async def relocate_missing_tracks(
    db: DbSession,
    request: RelocateRequest,
) -> RelocateResult:
    """Search a folder for missing files and relocate them.

    Scans the provided path for audio files and matches them against
    missing tracks by filename. Successfully matched tracks are updated
    with the new path and marked as ACTIVE.
    """
    import os

    from app.config import AUDIO_EXTENSIONS

    search_path = Path(request.search_path)
    if not search_path.exists() or not search_path.is_dir():
        raise HTTPException(status_code=400, detail="Search path does not exist or is not a directory")

    # Get all missing tracks
    result = await db.execute(
        select(Track).where(
            Track.status.in_([TrackStatus.MISSING, TrackStatus.PENDING_DELETION])
        )
    )
    missing_tracks = {Path(t.file_path).name.lower(): t for t in result.scalars().all()}

    if not missing_tracks:
        return RelocateResult(found=0, not_found=0, relocated_tracks=[])

    # Build map of filenames in search path
    audio_ext_lower = {ext.lower() for ext in AUDIO_EXTENSIONS}
    found_files: dict[str, Path] = {}

    for root, _, filenames in os.walk(search_path):
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext in audio_ext_lower:
                key = filename.lower()
                if key not in found_files:  # First occurrence wins
                    found_files[key] = Path(root) / filename

    # Match and relocate
    relocated = []
    for filename, track in missing_tracks.items():
        if filename in found_files:
            new_path = found_files[filename]
            track.file_path = str(new_path)
            track.status = TrackStatus.ACTIVE
            track.missing_since = None
            relocated.append({
                "id": str(track.id),
                "title": track.title,
                "old_path": track.file_path,
                "new_path": str(new_path),
            })

    await db.commit()

    return RelocateResult(
        found=len(relocated),
        not_found=len(missing_tracks) - len(relocated),
        relocated_tracks=relocated,
    )


@router.post("/missing/{track_id}/locate")
async def locate_single_track(
    db: DbSession,
    track_id: str,
    request: LocateRequest,
) -> dict:
    """Manually set a new path for a missing track.

    Use this when you know exactly where the file has moved to.
    """
    from uuid import UUID

    new_path = Path(request.new_path)
    if not new_path.exists():
        raise HTTPException(status_code=400, detail="File does not exist at specified path")
    if not new_path.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    try:
        track_uuid = UUID(track_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid track ID")

    track = await db.get(Track, track_uuid)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    if track.status not in (TrackStatus.MISSING, TrackStatus.PENDING_DELETION):
        raise HTTPException(status_code=400, detail="Track is not missing")

    old_path = track.file_path
    track.file_path = str(new_path)
    track.status = TrackStatus.ACTIVE
    track.missing_since = None

    await db.commit()

    return {
        "status": "relocated",
        "track_id": track_id,
        "old_path": old_path,
        "new_path": str(new_path),
    }


@router.delete("/missing/{track_id}")
async def delete_missing_track(
    db: DbSession,
    track_id: str,
) -> dict:
    """Permanently delete a missing track from the database.

    This is irreversible - the track and all its analysis data will be removed.
    """
    from uuid import UUID

    try:
        track_uuid = UUID(track_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid track ID")

    track = await db.get(Track, track_uuid)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    if track.status not in (TrackStatus.MISSING, TrackStatus.PENDING_DELETION):
        raise HTTPException(status_code=400, detail="Track is not missing - cannot delete active tracks")

    title = track.title or Path(track.file_path).name
    await db.delete(track)
    await db.commit()

    return {
        "status": "deleted",
        "track_id": track_id,
        "title": title,
    }


@router.delete("/missing/batch")
async def delete_missing_tracks_batch(
    db: DbSession,
    request: BatchDeleteRequest,
) -> dict:
    """Permanently delete multiple missing tracks from the database.

    This is irreversible - the tracks and all their analysis data will be removed.
    Only tracks with MISSING or PENDING_DELETION status can be deleted.
    """
    from uuid import UUID

    deleted = 0
    errors = []

    for track_id in request.track_ids:
        try:
            track_uuid = UUID(track_id)
            track = await db.get(Track, track_uuid)

            if not track:
                errors.append(f"{track_id}: not found")
                continue

            if track.status not in (TrackStatus.MISSING, TrackStatus.PENDING_DELETION):
                errors.append(f"{track_id}: not missing")
                continue

            await db.delete(track)
            deleted += 1

        except ValueError:
            errors.append(f"{track_id}: invalid ID")

    await db.commit()

    return {
        "status": "completed",
        "deleted": deleted,
        "errors": errors,
    }


# ============================================================================
# Discovery Dashboard
# ============================================================================


class DiscoverNewRelease(BaseModel):
    """A new release for discovery."""

    id: str
    artist: str
    album: str
    release_date: str | None
    source: str
    image_url: str | None
    bandcamp_url: str | None
    owned_locally: bool


class DiscoverRecommendedArtist(BaseModel):
    """A recommended artist based on listening patterns."""

    name: str
    match_score: float
    in_library: bool
    track_count: int | None = None
    image_url: str | None = None
    lastfm_url: str | None = None
    bandcamp_url: str | None = None
    based_on_artist: str  # Which library artist triggered this recommendation


class DiscoverUnmatchedFavorite(BaseModel):
    """A Spotify favorite that's not in the local library."""

    spotify_track_id: str
    name: str
    artist: str
    album: str | None
    image_url: str | None
    bandcamp_url: str | None


class DiscoverResponse(BaseModel):
    """Aggregated discovery data for the dashboard."""

    # New releases from library artists
    new_releases: list[DiscoverNewRelease]
    new_releases_total: int

    # Recommended artists based on top-played artists
    recommended_artists: list[DiscoverRecommendedArtist]

    # Unmatched Spotify favorites (if Spotify connected)
    unmatched_favorites: list[DiscoverUnmatchedFavorite]
    unmatched_total: int

    # Recently added to library
    recently_added_count: int


@router.get("/discover", response_model=DiscoverResponse)
async def get_discover_dashboard(
    db: DbSession,
    releases_limit: int = Query(8, ge=1, le=20),
    recommendations_limit: int = Query(8, ge=1, le=20),
    favorites_limit: int = Query(6, ge=1, le=20),
) -> DiscoverResponse:
    """Get aggregated discovery data for the dashboard.

    Combines:
    - New releases from library artists
    - Recommended artists based on most-played
    - Unmatched Spotify favorites
    - Recently added track count
    """
    from datetime import datetime, timedelta

    from app.db.models import ArtistInfo, ProfilePlayHistory
    from app.services.lastfm import get_lastfm_service
    from app.services.new_releases import NewReleasesService
    from app.services.search_links import generate_artist_search_url, generate_release_search_urls

    # 1. Get new releases
    new_releases_service = NewReleasesService(db)
    releases_data = await new_releases_service.get_cached_releases(
        limit=releases_limit,
        offset=0,
        include_dismissed=False,
        include_owned=False,
    )
    releases_total = await new_releases_service.get_releases_count(
        include_dismissed=False,
        include_owned=False,
    )

    new_releases = []
    for r in releases_data:
        search_urls = generate_release_search_urls(r.get("artist", ""), r.get("album", ""))
        new_releases.append(
            DiscoverNewRelease(
                id=str(r.get("id", "")),
                artist=r.get("artist", ""),
                album=r.get("album", ""),
                release_date=r.get("release_date"),
                source=r.get("source", ""),
                image_url=r.get("image_url"),
                bandcamp_url=search_urls.get("bandcamp", {}).get("url"),
                owned_locally=r.get("owned_locally", False),
            )
        )

    # 2. Get recommended artists based on top-played artists
    recommended_artists: list[DiscoverRecommendedArtist] = []

    # Get top-played artists
    play_history_query = (
        select(
            func.lower(func.trim(Track.artist)).label("artist_normalized"),
            Track.artist,
            func.sum(ProfilePlayHistory.play_count).label("total_plays"),
        )
        .join(Track, ProfilePlayHistory.track_id == Track.id)
        .where(Track.artist.isnot(None))
        .group_by(func.lower(func.trim(Track.artist)), Track.artist)
        .order_by(func.sum(ProfilePlayHistory.play_count).desc())
        .limit(5)  # Top 5 artists
    )
    play_result = await db.execute(play_history_query)
    top_artists = play_result.fetchall()

    # For each top artist, get similar artists
    seen_recommendations: set[str] = set()

    for row in top_artists:
        artist_name = row.artist
        if not artist_name:
            continue

        artist_normalized = artist_name.lower().strip()

        # Check cached artist info for similar artists
        cached_info = await db.get(ArtistInfo, artist_normalized)
        if cached_info and cached_info.similar_artists:
            raw_similar = cached_info.similar_artists
        else:
            # Try fetching from Last.fm
            lastfm_service = get_lastfm_service()
            if lastfm_service.is_configured():
                try:
                    info = await lastfm_service.get_artist_info(artist_name)
                    if info:
                        raw_similar = info.get("similar", {}).get("artist", [])
                    else:
                        raw_similar = []
                except Exception:
                    raw_similar = []
            else:
                raw_similar = []

        # Process similar artists
        for similar in raw_similar[:3]:  # Take top 3 from each
            name = similar.get("name", "")
            if not name:
                continue

            normalized = name.lower().strip()
            if normalized in seen_recommendations:
                continue
            seen_recommendations.add(normalized)

            # Check if in library
            lib_check = await db.execute(
                select(func.count(Track.id))
                .where(
                    func.lower(func.trim(Track.artist)) == normalized,
                    Track.status == TrackStatus.ACTIVE,
                )
            )
            track_count = lib_check.scalar() or 0
            in_library = track_count > 0

            # Extract image URL
            images = similar.get("image", [])
            image_url = None
            for img in images:
                if img.get("size") == "large" and img.get("#text"):
                    image_url = img["#text"]
                    break

            # Parse match score
            try:
                match_score = float(similar.get("match", 0))
            except (ValueError, TypeError):
                match_score = 0.0

            recommended_artists.append(
                DiscoverRecommendedArtist(
                    name=name,
                    match_score=match_score,
                    in_library=in_library,
                    track_count=track_count if in_library else None,
                    image_url=image_url,
                    lastfm_url=similar.get("url"),
                    bandcamp_url=generate_artist_search_url("bandcamp", name),
                    based_on_artist=artist_name,
                )
            )

            if len(recommended_artists) >= recommendations_limit:
                break

        if len(recommended_artists) >= recommendations_limit:
            break

    # 3. Get unmatched Spotify favorites
    unmatched_favorites: list[DiscoverUnmatchedFavorite] = []
    unmatched_total = 0

    try:
        from app.db.models import SpotifyFavorite, SpotifyProfile

        # Check if any Spotify profile is connected
        spotify_check = await db.execute(
            select(SpotifyProfile).where(SpotifyProfile.access_token.isnot(None)).limit(1)
        )
        has_spotify = spotify_check.scalar_one_or_none() is not None

        if has_spotify:
            # Get unmatched favorites
            unmatched_query = (
                select(SpotifyFavorite)
                .where(SpotifyFavorite.matched_track_id.is_(None))
                .order_by(SpotifyFavorite.added_at.desc())
                .limit(favorites_limit)
            )
            unmatched_result = await db.execute(unmatched_query)
            favorites = unmatched_result.scalars().all()

            for fav in favorites:
                artist_name = fav.track_data.get("artist") or ""
                track_name = fav.track_data.get("name") or ""
                search_urls = generate_release_search_urls(artist_name, track_name)
                unmatched_favorites.append(
                    DiscoverUnmatchedFavorite(
                        spotify_track_id=fav.spotify_track_id,
                        name=track_name,
                        artist=artist_name,
                        album=fav.track_data.get("album"),
                        image_url=None,  # album_image_url not stored in track_data
                        bandcamp_url=search_urls.get("bandcamp", {}).get("url"),
                    )
                )

            # Get total count
            count_query = select(func.count()).select_from(
                select(SpotifyFavorite)
                .where(SpotifyFavorite.matched_track_id.is_(None))
                .subquery()
            )
            unmatched_total = await db.scalar(count_query) or 0

    except Exception:
        pass  # Spotify tables might not exist

    # 4. Get recently added count (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_query = (
        select(func.count(Track.id))
        .where(
            Track.created_at >= thirty_days_ago,
            Track.status == TrackStatus.ACTIVE,
        )
    )
    recently_added_count = await db.scalar(recent_query) or 0

    return DiscoverResponse(
        new_releases=new_releases,
        new_releases_total=releases_total,
        recommended_artists=recommended_artists,
        unmatched_favorites=unmatched_favorites,
        unmatched_total=unmatched_total,
        recently_added_count=recently_added_count,
    )
