"""Album browsing and detail endpoints."""

import asyncio
import logging
from collections.abc import Sequence

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.api.exceptions import NotFoundError
from app.db.models import Track, TrackStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["library"])


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
    source: str | None = Query(None, description="Navigation source: 'artist' skips album_artist lookup"),
) -> AlbumDetailResponse:
    """Get detailed album information with tracks and similar albums.

    Returns album metadata, all tracks, similar albums (by audio embedding),
    and other albums by the same artist.

    Args:
        artist_name: The artist name (URL-encoded)
        album_name: The album name (URL-encoded)
        similar_limit: Maximum number of similar albums to return
        source: Navigation source hint. 'artist' skips the album_artist query.
    """
    from urllib.parse import unquote

    from sqlalchemy import cast
    from sqlalchemy.dialects.postgresql import TEXT

    from app.db.models import ArtistInfo
    from app.services.search_links import generate_artist_search_url

    # URL decode the names
    artist_name = unquote(artist_name)
    album_name = unquote(album_name)
    artist_normalized = artist_name.lower().strip()
    album_normalized = album_name.lower().strip()

    # Use album_artist (with fallback to artist) to match how list_albums groups albums
    # This ensures compilation/soundtrack albums are found correctly
    album_artist_col = func.coalesce(func.nullif(Track.album_artist, ""), Track.artist)

    tracks_list: Sequence[Track] = []

    # When navigating from ArtistDetail (source=artist), skip the album_artist query
    # since ArtistDetail groups by Track.artist, not album_artist
    if source != "artist":
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

    # If not found by album_artist (or skipped), try matching by track artist
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
        raise NotFoundError("Album not found in library")

    # Extract album info from first track
    first_track = tracks_list[0]
    album_artist = first_track.album_artist
    year = first_track.year
    genre = first_track.genre
    total_duration = sum((t.duration_seconds or 0) for t in tracks_list)

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

    # --- Phase A: Run other-albums query and ArtistInfo lookup in parallel ---

    async def fetch_other_albums() -> list[SimilarAlbumInfo]:
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
        return [
            SimilarAlbumInfo(
                name=row.name or "Unknown Album",
                artist=row.artist or artist_name,
                year=row.year,
                track_count=row.track_count,
                first_track_id=str(row.first_track_id),
                similarity_score=1.0,
            )
            for row in other_albums_result.all()
        ]

    async def fetch_artist_info() -> list[dict]:
        cached_artist = await db.get(ArtistInfo, artist_normalized)
        return cached_artist.similar_artists if cached_artist else []

    other_albums_by_artist, raw_similar_artists = await asyncio.gather(
        fetch_other_albums(), fetch_artist_info()
    )

    # --- Phase B: Run similar-albums and discover-albums queries in parallel ---
    # Both depend on raw_similar_artists from Phase A

    async def fetch_similar_albums() -> list[SimilarAlbumInfo]:
        if not raw_similar_artists:
            return []

        similar_artist_names = [s.get("name", "") for s in raw_similar_artists if s.get("name")]
        similar_normalized = [n.lower().strip() for n in similar_artist_names]
        if not similar_normalized:
            return []

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

        # Build match score map
        match_scores = {}
        for idx, s in enumerate(raw_similar_artists):
            name = s.get("name", "")
            if name:
                raw_match = s.get("match")
                if raw_match:
                    try:
                        match_scores[name.lower().strip()] = float(raw_match)
                    except (ValueError, TypeError):
                        match_scores[name.lower().strip()] = max(0.3, 1.0 - (idx * 0.1))
                else:
                    match_scores[name.lower().strip()] = max(0.3, 1.0 - (idx * 0.1))

        albums = []
        for row in similar_result.all():
            artist_norm = (row.artist or "").lower().strip()
            match_score = match_scores.get(artist_norm, 0.5)
            albums.append(
                SimilarAlbumInfo(
                    name=row.name or "Unknown Album",
                    artist=row.artist or "Unknown Artist",
                    year=row.year,
                    track_count=row.track_count,
                    first_track_id=str(row.first_track_id),
                    similarity_score=round(match_score, 3),
                )
            )
        return albums

    async def fetch_discover_albums() -> list[DiscoverAlbumInfo]:
        if not raw_similar_artists:
            return []

        similar_artist_names = [s.get("name", "") for s in raw_similar_artists if s.get("name")]
        similar_normalized = [n.lower().strip() for n in similar_artist_names]
        if not similar_normalized:
            return []

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

        albums = []
        for similar in raw_similar_artists[:10]:
            name = similar.get("name", "")
            if not name:
                continue
            normalized = name.lower().strip()
            if normalized not in in_library:
                images = similar.get("image", [])
                image_url = None
                for img in images:
                    if img.get("size") == "large" and img.get("#text"):
                        image_url = img["#text"]
                        break

                albums.append(
                    DiscoverAlbumInfo(
                        name=f"Albums by {name}",
                        artist=name,
                        image_url=image_url,
                        lastfm_url=similar.get("url"),
                        bandcamp_url=generate_artist_search_url("bandcamp", name),
                    )
                )
        return albums

    similar_albums, discover_albums = await asyncio.gather(
        fetch_similar_albums(), fetch_discover_albums()
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
