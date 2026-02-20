"""Artist browsing and detail endpoints."""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.db.models import Track, TrackAnalysis, TrackStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["library"])


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
