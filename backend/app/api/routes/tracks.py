"""Track endpoints."""

import asyncio
import logging
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Float, String, cast, func, literal, nulls_last, select, union_all
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentProfile, DbSession, RequiredProfile
from app.db.models import ExternalTrack, ProfilePlayHistory, Track, TrackAnalysis
from app.services.artwork import compute_album_hash, get_artwork_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tracks", tags=["tracks"])


class TrackFeaturesResponse(BaseModel):
    """Audio analysis features."""

    bpm: float | None = None
    key: str | None = None
    energy: float | None = None
    danceability: float | None = None
    valence: float | None = None
    acousticness: float | None = None
    instrumentalness: float | None = None
    speechiness: float | None = None
    loudness_lufs: float | None = None
    track_peak: float | None = None
    replaygain_track_gain: float | None = None


class TrackResponse(BaseModel):
    """Track response schema."""

    id: UUID
    file_path: str
    title: str | None
    artist: str | None
    album: str | None
    album_artist: str | None
    album_type: str
    track_number: int | None
    disc_number: int | None
    year: int | None
    genre: str | None
    duration_seconds: float | None
    format: str | None
    analysis_version: int
    features: TrackFeaturesResponse | None = None
    # Play history (profile-specific, populated when profile header is present)
    last_played_at: datetime | None = None
    play_count: int | None = None

    # External track fields (present when track_type === 'external')
    track_type: str = "local"  # 'local' | 'external'
    preview_url: str | None = None
    matched_track_id: str | None = None
    external_data: dict[str, Any] | None = None
    source: str | None = None
    spotify_id: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TrackDetailResponse(TrackResponse):
    """Track detail response with analysis features (deprecated, use TrackResponse)."""

    pass


class TrackListResponse(BaseModel):
    """Paginated track list response."""

    items: list[TrackResponse]
    total: int
    page: int
    page_size: int


class TrackIdsResponse(BaseModel):
    """Response containing only track IDs (lightweight for shuffle)."""

    ids: list[str]
    total: int


@router.get("/ids", response_model=TrackIdsResponse)
async def list_track_ids(
    db: DbSession,
    shuffle: bool = Query(False, description="Randomize the order of IDs"),
    start_with: str | None = Query(None, description="Track ID to place first in results"),
    search: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    genre: str | None = None,
    year_from: int | None = Query(None, description="Filter tracks from this year (inclusive)"),
    year_to: int | None = Query(None, description="Filter tracks up to this year (inclusive)"),
    energy_min: float | None = Query(None, ge=0, le=1, description="Minimum energy (0-1)"),
    energy_max: float | None = Query(None, ge=0, le=1, description="Maximum energy (0-1)"),
    valence_min: float | None = Query(None, ge=0, le=1, description="Minimum valence (0-1)"),
    valence_max: float | None = Query(None, ge=0, le=1, description="Maximum valence (0-1)"),
    include_external: bool = Query(False, description="Include unmatched external tracks (ext: prefixed)"),
    sort_by: str | None = Query(None, description="Column to sort by"),
    sort_order: str = Query('asc', pattern='^(asc|desc)$', description="Sort direction"),
) -> TrackIdsResponse:
    """Get all track IDs matching filters.

    Returns only IDs (lightweight) for shuffle-all functionality.
    Use shuffle=true to get randomized order via ORDER BY random().
    Use start_with to ensure a specific track appears first (useful when shuffle=true).
    When include_external=True, external track IDs are prefixed with 'ext:'.
    """

    has_feature_filter = any(x is not None for x in [energy_min, energy_max, valence_min, valence_max])
    use_external = include_external and not has_feature_filter and not genre and sort_by not in SORT_FEATURE_FIELDS and sort_by != 'lastPlayed'

    if use_external:
        # Build UNION of local IDs + ext:-prefixed external IDs
        local_q = select(
            cast(Track.id, String).label("id"),
            Track.artist.label("sort_artist"),
            Track.album.label("sort_album"),
            Track.track_number.label("sort_track_number"),
        )
        if search:
            search_filter = f"%{search}%"
            local_q = local_q.where(
                Track.title.ilike(search_filter) | Track.artist.ilike(search_filter) | Track.album.ilike(search_filter)
            )
        if artist:
            local_q = local_q.where(Track.artist.ilike(f"%{artist}%") | Track.album_artist.ilike(f"%{artist}%"))
        if album:
            local_q = local_q.where(Track.album.ilike(f"%{album}%"))
        if year_from is not None:
            local_q = local_q.where(Track.year >= year_from)
        if year_to is not None:
            local_q = local_q.where(Track.year <= year_to)

        ext_q = select(
            (literal("ext:") + cast(ExternalTrack.id, String)).label("id"),
            ExternalTrack.artist.label("sort_artist"),
            ExternalTrack.album.label("sort_album"),
            ExternalTrack.track_number.label("sort_track_number"),
        ).where(ExternalTrack.matched_track_id.is_(None))
        ext_q = _apply_metadata_filters_to_external(ext_q, search, artist, album, year_from, year_to)

        combined = union_all(local_q, ext_q).subquery()
        count_q = select(func.count()).select_from(combined)
        total = await db.scalar(count_q) or 0

        id_q = select(combined.c.id)
        if shuffle:
            id_q = id_q.order_by(func.random())
        elif sort_by and sort_by in SORT_FIELD_MAP and sort_by != 'lastPlayed':
            if sort_order == 'desc':
                id_q = id_q.order_by(nulls_last(SORT_FIELD_MAP[sort_by].desc()) if hasattr(combined.c, 'sort_col') else combined.c.sort_artist, combined.c.sort_album, combined.c.sort_track_number)
            else:
                id_q = id_q.order_by(combined.c.sort_artist, combined.c.sort_album, combined.c.sort_track_number)
        else:
            id_q = id_q.order_by(combined.c.sort_artist, combined.c.sort_album, combined.c.sort_track_number)

        result = await db.execute(id_q)
        track_ids = [row[0] for row in result.all()]

        if start_with and start_with in track_ids:
            track_ids.remove(start_with)
            track_ids.insert(0, start_with)

        return TrackIdsResponse(ids=track_ids, total=total)

    # Standard path: local tracks only
    query = select(Track.id)

    if search:
        search_filter = f"%{search}%"
        query = query.where(
            Track.title.ilike(search_filter)
            | Track.artist.ilike(search_filter)
            | Track.album.ilike(search_filter)
        )
    if artist:
        query = query.where(
            Track.artist.ilike(f"%{artist}%") | Track.album_artist.ilike(f"%{artist}%")
        )
    if album:
        query = query.where(Track.album.ilike(f"%{album}%"))
    if genre:
        query = query.where(Track.genre.ilike(f"%{genre}%"))
    if year_from is not None:
        query = query.where(Track.year >= year_from)
    if year_to is not None:
        query = query.where(Track.year <= year_to)

    if has_feature_filter:
        query = query.join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
        if energy_min is not None:
            query = query.where(TrackAnalysis.energy >= energy_min)
        if energy_max is not None:
            query = query.where(TrackAnalysis.energy <= energy_max)
        if valence_min is not None:
            query = query.where(TrackAnalysis.valence >= valence_min)
        if valence_max is not None:
            query = query.where(TrackAnalysis.valence <= valence_max)

    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    if shuffle:
        query = query.order_by(func.random())
    elif sort_by and (sort_by in SORT_FIELD_MAP or sort_by in SORT_FEATURE_FIELDS):
        if sort_by in SORT_FIELD_MAP:
            sort_col = SORT_FIELD_MAP[sort_by]
            if sort_by != 'lastPlayed':
                if sort_order == 'desc':
                    query = query.order_by(nulls_last(sort_col.desc()), Track.artist, Track.album, Track.track_number)
                else:
                    query = query.order_by(nulls_last(sort_col.asc()), Track.artist, Track.album, Track.track_number)
            else:
                query = query.order_by(Track.artist, Track.album, Track.track_number)
        else:
            if not has_feature_filter:
                query = query.outerjoin(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            sort_col_attr = getattr(TrackAnalysis, sort_by, None)
            sort_expr = cast(sort_col_attr, Float) if sort_col_attr is not None else TrackAnalysis.bpm
            if sort_order == 'desc':
                query = query.order_by(nulls_last(sort_expr.desc()), Track.artist, Track.album, Track.track_number)
            else:
                query = query.order_by(nulls_last(sort_expr.asc()), Track.artist, Track.album, Track.track_number)
    else:
        query = query.order_by(Track.artist, Track.album, Track.track_number)

    result = await db.execute(query)
    track_ids = [str(row[0]) for row in result.all()]

    if start_with and start_with in track_ids:
        track_ids.remove(start_with)
        track_ids.insert(0, start_with)

    return TrackIdsResponse(ids=track_ids, total=total)


class BatchTracksRequest(BaseModel):
    """Request to fetch tracks by IDs."""

    ids: list[str]


@router.post("/batch", response_model=list[TrackResponse])
async def get_tracks_batch(
    db: DbSession,
    request: BatchTracksRequest,
    profile: CurrentProfile,
) -> list[TrackResponse]:
    """Get full track metadata for a batch of IDs.

    Returns tracks in the same order as requested IDs.
    Limited to 50 tracks per request.
    IDs prefixed with 'ext:' are treated as external track IDs.
    """
    if len(request.ids) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 tracks per batch")

    if not request.ids:
        return []

    # Separate local and external IDs
    local_id_strs = [id_str for id_str in request.ids if not id_str.startswith("ext:")]
    ext_id_strs = [id_str for id_str in request.ids if id_str.startswith("ext:")]

    # Convert to UUIDs
    try:
        local_uuids = [UUID(id_str) for id_str in local_id_strs]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid track ID format")

    try:
        ext_uuids = [UUID(id_str[4:]) for id_str in ext_id_strs]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid external track ID format")

    # Fetch local tracks
    tracks_by_id: dict[str, Track] = {}
    if local_uuids:
        query = select(Track).where(Track.id.in_(local_uuids))
        result = await db.execute(query)
        tracks_by_id = {str(t.id): t for t in result.scalars().all()}

    # Fetch external tracks
    ext_tracks_by_id: dict[str, ExternalTrack] = {}
    if ext_uuids:
        ext_result = await db.execute(select(ExternalTrack).where(ExternalTrack.id.in_(ext_uuids)))
        ext_tracks_by_id = {str(t.id): t for t in ext_result.scalars().all()}

    # Fetch play history for local tracks
    play_history_map: dict[UUID, ProfilePlayHistory] = {}
    if profile and local_uuids:
        ph_query = select(ProfilePlayHistory).where(
            ProfilePlayHistory.profile_id == profile.id,
            ProfilePlayHistory.track_id.in_(local_uuids),
        )
        ph_result = await db.execute(ph_query)
        play_history_map = {ph.track_id: ph for ph in ph_result.scalars().all()}

    # Return in requested order, skipping missing tracks
    ordered_tracks: list[TrackResponse] = []
    for id_str in request.ids:
        if id_str.startswith("ext:"):
            ext_id = id_str[4:]
            ext = ext_tracks_by_id.get(ext_id)
            if ext:
                ordered_tracks.append(_external_track_to_response(ext))
        elif id_str in tracks_by_id:
            track = tracks_by_id[id_str]
            response = TrackResponse.model_validate(track)
            if track.id in play_history_map:
                ph = play_history_map[track.id]
                response.last_played_at = ph.last_played_at
                response.play_count = ph.play_count
            ordered_tracks.append(response)

    return ordered_tracks


# Map frontend column IDs to database fields for sorting
SORT_FIELD_MAP: dict[str, Any] = {
    'artist': Track.artist,
    'album': Track.album,
    'title': Track.title,
    'duration': Track.duration_seconds,
    'year': Track.year,
    'genre': Track.genre,
    'trackNum': Track.track_number,
    'format': Track.format,
    'lastPlayed': ProfilePlayHistory.last_played_at,
}

# Analysis features that need JSONB extraction
SORT_FEATURE_FIELDS = {
    'bpm', 'energy', 'danceability', 'valence',
    'acousticness', 'instrumentalness', 'key',
}


def _apply_metadata_filters_to_external(
    query: Any,
    search: str | None,
    artist: str | None,
    album: str | None,
    year_from: int | None,
    year_to: int | None,
) -> Any:
    """Apply metadata filters to an ExternalTrack query."""
    if search:
        search_filter = f"%{search}%"
        query = query.where(
            ExternalTrack.title.ilike(search_filter)
            | ExternalTrack.artist.ilike(search_filter)
            | ExternalTrack.album.ilike(search_filter)
        )
    if artist:
        query = query.where(ExternalTrack.artist.ilike(f"%{artist}%"))
    if album:
        query = query.where(ExternalTrack.album.ilike(f"%{album}%"))
    if year_from is not None:
        query = query.where(ExternalTrack.year >= year_from)
    if year_to is not None:
        query = query.where(ExternalTrack.year <= year_to)
    return query


def _external_track_to_response(row: Any) -> TrackResponse:
    """Convert an ExternalTrack ORM object to a TrackResponse."""
    ext_data = row.external_data or {}
    return TrackResponse(
        id=row.id,
        file_path="",
        title=row.title,
        artist=row.artist,
        album=row.album,
        album_artist=None,
        album_type="album",
        track_number=row.track_number,
        disc_number=None,
        year=row.year,
        genre=None,
        duration_seconds=row.duration_seconds,
        format=None,
        analysis_version=0,
        track_type="external",
        preview_url=ext_data.get("itunes_preview_url"),
        matched_track_id=str(row.matched_track_id) if row.matched_track_id else None,
        external_data=ext_data,
        source=row.source.value if row.source else None,
        spotify_id=row.spotify_id,
    )


@router.get("", response_model=TrackListResponse)
async def list_tracks(
    db: DbSession,
    profile: CurrentProfile,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    genre: str | None = None,
    year_from: int | None = Query(None, description="Filter tracks from this year (inclusive)"),
    year_to: int | None = Query(None, description="Filter tracks up to this year (inclusive)"),
    energy_min: float | None = Query(None, ge=0, le=1, description="Minimum energy (0-1)"),
    energy_max: float | None = Query(None, ge=0, le=1, description="Maximum energy (0-1)"),
    valence_min: float | None = Query(None, ge=0, le=1, description="Minimum valence (0-1)"),
    valence_max: float | None = Query(None, ge=0, le=1, description="Maximum valence (0-1)"),
    include_features: bool = Query(False, description="Include audio analysis features"),
    include_external: bool = Query(False, description="Include unmatched external tracks interleaved"),
    sort_by: str | None = Query(None, description="Column to sort by"),
    sort_order: str = Query('asc', pattern='^(asc|desc)$', description="Sort direction"),
) -> TrackListResponse:
    """List tracks with optional filtering and pagination.

    When include_external=True, unmatched external tracks are interleaved with
    local tracks using a UNION ALL approach for correct cross-table pagination.
    External tracks are excluded when audio feature filters are active (they have no analysis).
    """

    has_feature_filter = any(x is not None for x in [energy_min, energy_max, valence_min, valence_max])
    # External tracks can't participate in feature sorts/filters
    use_external = include_external and not has_feature_filter and not genre and sort_by not in SORT_FEATURE_FIELDS and sort_by != 'lastPlayed'

    # ──────────────────────────────────────────────────────────────────────
    # UNION path: interleave local + external tracks with correct pagination
    # ──────────────────────────────────────────────────────────────────────
    if use_external:
        # Phase 1: build lightweight UNION for ID + sort columns
        # Local side
        local_id_q = select(
            cast(Track.id, String).label("id"),
            literal("local").label("track_type"),
            Track.artist.label("sort_artist"),
            Track.album.label("sort_album"),
            Track.track_number.label("sort_track_number"),
        )
        if search:
            search_filter = f"%{search}%"
            local_id_q = local_id_q.where(
                Track.title.ilike(search_filter)
                | Track.artist.ilike(search_filter)
                | Track.album.ilike(search_filter)
            )
        if artist:
            local_id_q = local_id_q.where(
                Track.artist.ilike(f"%{artist}%") | Track.album_artist.ilike(f"%{artist}%")
            )
        if album:
            local_id_q = local_id_q.where(Track.album.ilike(f"%{album}%"))
        if year_from is not None:
            local_id_q = local_id_q.where(Track.year >= year_from)
        if year_to is not None:
            local_id_q = local_id_q.where(Track.year <= year_to)

        # Add sort_by column to local query if it's a simple metadata field
        if sort_by and sort_by in SORT_FIELD_MAP and sort_by != 'lastPlayed':
            local_id_q = local_id_q.add_columns(SORT_FIELD_MAP[sort_by].label("sort_col"))
        else:
            local_id_q = local_id_q.add_columns(literal(None, type_=String).label("sort_col"))

        # External side — only unmatched
        ext_id_q = select(
            (literal("ext:") + cast(ExternalTrack.id, String)).label("id"),
            literal("external").label("track_type"),
            ExternalTrack.artist.label("sort_artist"),
            ExternalTrack.album.label("sort_album"),
            ExternalTrack.track_number.label("sort_track_number"),
        ).where(ExternalTrack.matched_track_id.is_(None))
        ext_id_q = _apply_metadata_filters_to_external(ext_id_q, search, artist, album, year_from, year_to)

        # Add sort_by column to external query (map Track columns to ExternalTrack equivalents)
        _ext_sort_map: dict[str, Any] = {
            'artist': ExternalTrack.artist,
            'album': ExternalTrack.album,
            'title': ExternalTrack.title,
            'duration': ExternalTrack.duration_seconds,
            'year': ExternalTrack.year,
            'trackNum': ExternalTrack.track_number,
        }
        if sort_by and sort_by in _ext_sort_map:
            ext_id_q = ext_id_q.add_columns(_ext_sort_map[sort_by].label("sort_col"))
        else:
            ext_id_q = ext_id_q.add_columns(literal(None, type_=String).label("sort_col"))

        combined = union_all(local_id_q, ext_id_q).subquery()

        # Count
        count_q = select(func.count()).select_from(combined)
        total = await db.scalar(count_q) or 0

        # Order the combined results
        if sort_by and sort_by in SORT_FIELD_MAP and sort_by != 'lastPlayed':
            if sort_order == 'desc':
                order = [nulls_last(combined.c.sort_col.desc()), combined.c.sort_artist, combined.c.sort_album, combined.c.sort_track_number]
            else:
                order = [nulls_last(combined.c.sort_col.asc()), combined.c.sort_artist, combined.c.sort_album, combined.c.sort_track_number]
        else:
            order = [combined.c.sort_artist, combined.c.sort_album, combined.c.sort_track_number]

        page_q = (
            select(combined.c.id, combined.c.track_type)
            .order_by(*order)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        page_result = await db.execute(page_q)
        page_rows = page_result.all()

        # Phase 2: fetch full objects by ID
        local_uuids = [UUID(r.id) for r in page_rows if r.track_type == "local"]
        ext_uuids = [UUID(r.id[4:]) for r in page_rows if r.track_type == "external"]

        local_tracks_by_id: dict[str, Track] = {}
        if local_uuids:
            q = select(Track).where(Track.id.in_(local_uuids))
            if include_features:
                q = q.options(selectinload(Track.analyses))
            res = await db.execute(q)
            local_tracks_by_id = {str(t.id): t for t in res.scalars().all()}

        ext_tracks_by_id: dict[str, ExternalTrack] = {}
        if ext_uuids:
            ext_res = await db.execute(select(ExternalTrack).where(ExternalTrack.id.in_(ext_uuids)))
            ext_tracks_by_id = {str(t.id): t for t in ext_res.scalars().all()}

        # Play history for local tracks
        ph_map: dict[UUID, ProfilePlayHistory] = {}
        if profile and local_uuids:
            ph_result = await db.execute(
                select(ProfilePlayHistory).where(
                    ProfilePlayHistory.profile_id == profile.id,
                    ProfilePlayHistory.track_id.in_(local_uuids),
                )
            )
            ph_map = {ph.track_id: ph for ph in ph_result.scalars().all()}

        # Phase 3: build response in page order
        unified_items: list[TrackResponse] = []
        for row in page_rows:
            if row.track_type == "local":
                track = local_tracks_by_id.get(row.id)
                if not track:
                    continue
                response = TrackResponse.model_validate(track)
                if include_features and track.analyses:
                    latest = track.analyses[0]
                    if latest.bpm is not None:
                        response.features = TrackFeaturesResponse(
                            bpm=latest.bpm,
                            key=latest.key,
                            energy=latest.energy,
                            danceability=latest.danceability,
                            valence=latest.valence,
                            acousticness=latest.acousticness,
                            instrumentalness=latest.instrumentalness,
                            speechiness=latest.speechiness,
                            loudness_lufs=latest.loudness_lufs,
                            track_peak=latest.track_peak,
                            replaygain_track_gain=latest.replaygain_track_gain,
                        )
                if track.id in ph_map:
                    ph = ph_map[track.id]
                    response.last_played_at = ph.last_played_at
                    response.play_count = ph.play_count
                unified_items.append(response)
            else:
                # External track
                ext_id = row.id[4:]  # strip "ext:" prefix
                ext = ext_tracks_by_id.get(ext_id)
                if ext:
                    unified_items.append(_external_track_to_response(ext))

        return TrackListResponse(items=unified_items, total=total, page=page, page_size=page_size)

    # ──────────────────────────────────────────────────────────────────────
    # Standard path: local tracks only (original logic)
    # ──────────────────────────────────────────────────────────────────────
    query = select(Track)

    # Include analysis features if requested
    if include_features:
        query = query.options(selectinload(Track.analyses))

    # Apply filters
    if search:
        search_filter = f"%{search}%"
        query = query.where(
            Track.title.ilike(search_filter)
            | Track.artist.ilike(search_filter)
            | Track.album.ilike(search_filter)
        )
    if artist:
        query = query.where(
            Track.artist.ilike(f"%{artist}%") | Track.album_artist.ilike(f"%{artist}%")
        )
    if album:
        query = query.where(Track.album.ilike(f"%{album}%"))
    if genre:
        query = query.where(Track.genre.ilike(f"%{genre}%"))
    if year_from is not None:
        query = query.where(Track.year >= year_from)
    if year_to is not None:
        query = query.where(Track.year <= year_to)

    # Audio feature filters
    if has_feature_filter:
        query = query.join(
            TrackAnalysis,
            (Track.id == TrackAnalysis.track_id) & (TrackAnalysis.bpm.isnot(None))
        )
        if energy_min is not None:
            query = query.where(TrackAnalysis.energy >= energy_min)
        if energy_max is not None:
            query = query.where(TrackAnalysis.energy <= energy_max)
        if valence_min is not None:
            query = query.where(TrackAnalysis.valence >= valence_min)
        if valence_max is not None:
            query = query.where(TrackAnalysis.valence <= valence_max)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply ordering
    if sort_by and (sort_by in SORT_FIELD_MAP or sort_by in SORT_FEATURE_FIELDS):
        if sort_by in SORT_FIELD_MAP:
            sort_col = SORT_FIELD_MAP[sort_by]
            if sort_by == 'lastPlayed' and profile:
                query = query.outerjoin(
                    ProfilePlayHistory,
                    (ProfilePlayHistory.track_id == Track.id) &
                    (ProfilePlayHistory.profile_id == profile.id)
                )
            if sort_order == 'desc':
                query = query.order_by(nulls_last(sort_col.desc()), Track.artist, Track.album, Track.track_number)
            else:
                query = query.order_by(nulls_last(sort_col.asc()), Track.artist, Track.album, Track.track_number)
        else:
            if not has_feature_filter:
                query = query.outerjoin(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            sort_col_attr = getattr(TrackAnalysis, sort_by, None)
            sort_expr = cast(sort_col_attr, Float) if sort_col_attr is not None else TrackAnalysis.bpm
            if sort_order == 'desc':
                query = query.order_by(nulls_last(sort_expr.desc()), Track.artist, Track.album, Track.track_number)
            else:
                query = query.order_by(nulls_last(sort_expr.asc()), Track.artist, Track.album, Track.track_number)
    else:
        query = query.order_by(Track.artist, Track.album, Track.track_number)

    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    tracks = result.scalars().all()

    # Fetch play history for current profile if available
    play_history_map: dict[UUID, ProfilePlayHistory] = {}
    if profile and tracks:
        track_ids = [t.id for t in tracks]
        ph_query = select(ProfilePlayHistory).where(
            ProfilePlayHistory.profile_id == profile.id,
            ProfilePlayHistory.track_id.in_(track_ids),
        )
        ph_result = await db.execute(ph_query)
        play_history_map = {ph.track_id: ph for ph in ph_result.scalars().all()}

    # Build response with optional features
    items: list[TrackResponse] = []
    for track in tracks:
        response = TrackResponse.model_validate(track)
        if include_features and track.analyses:
            latest = track.analyses[0]
            if latest.bpm is not None:
                response.features = TrackFeaturesResponse(
                    bpm=latest.bpm,
                    key=latest.key,
                    energy=latest.energy,
                    danceability=latest.danceability,
                    valence=latest.valence,
                    acousticness=latest.acousticness,
                    instrumentalness=latest.instrumentalness,
                    speechiness=latest.speechiness,
                    loudness_lufs=latest.loudness_lufs,
                    track_peak=latest.track_peak,
                    replaygain_track_gain=latest.replaygain_track_gain,
                )
        if track.id in play_history_map:
            ph = play_history_map[track.id]
            response.last_played_at = ph.last_played_at
            response.play_count = ph.play_count
        items.append(response)

    return TrackListResponse(items=items, total=total, page=page, page_size=page_size)


class TrackIndexResponse(BaseModel):
    """Response for track index lookup."""

    index: int


@router.get("/{track_id}/index", response_model=TrackIndexResponse)
async def get_track_index(
    db: DbSession,
    track_id: UUID,
    search: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    genre: str | None = None,
    year_from: int | None = Query(None),
    year_to: int | None = Query(None),
    energy_min: float | None = Query(None, ge=0, le=1),
    energy_max: float | None = Query(None, ge=0, le=1),
    valence_min: float | None = Query(None, ge=0, le=1),
    valence_max: float | None = Query(None, ge=0, le=1),
    include_external: bool = Query(False),
    sort_by: str | None = Query(None),
    sort_order: str = Query('asc', pattern='^(asc|desc)$'),
) -> TrackIndexResponse:
    """Get the 0-based index of a track in the sorted list.

    Uses ROW_NUMBER() to efficiently find position without loading all tracks.
    Accepts the same filter and sort parameters as list_tracks so the index
    matches the current view.
    Returns {"index": N} or {"index": -1} if not found.
    """

    has_feature_filter = any(
        x is not None for x in [energy_min, energy_max, valence_min, valence_max]
    )
    use_external = include_external and not has_feature_filter and not genre and sort_by not in SORT_FEATURE_FIELDS and sort_by != 'lastPlayed'

    if use_external:
        # UNION approach for combined index lookup
        local_q = select(
            cast(Track.id, String).label("id"),
            Track.artist.label("sort_artist"),
            Track.album.label("sort_album"),
            Track.track_number.label("sort_track_number"),
        )
        if search:
            sf = f"%{search}%"
            local_q = local_q.where(Track.title.ilike(sf) | Track.artist.ilike(sf) | Track.album.ilike(sf))
        if artist:
            local_q = local_q.where(Track.artist.ilike(f"%{artist}%") | Track.album_artist.ilike(f"%{artist}%"))
        if album:
            local_q = local_q.where(Track.album.ilike(f"%{album}%"))
        if year_from is not None:
            local_q = local_q.where(Track.year >= year_from)
        if year_to is not None:
            local_q = local_q.where(Track.year <= year_to)

        ext_q = select(
            (literal("ext:") + cast(ExternalTrack.id, String)).label("id"),
            ExternalTrack.artist.label("sort_artist"),
            ExternalTrack.album.label("sort_album"),
            ExternalTrack.track_number.label("sort_track_number"),
        ).where(ExternalTrack.matched_track_id.is_(None))
        ext_q = _apply_metadata_filters_to_external(ext_q, search, artist, album, year_from, year_to)

        combined = union_all(local_q, ext_q).subquery()

        ext_order_clauses: list[Any] = [combined.c.sort_artist, combined.c.sort_album, combined.c.sort_track_number]
        row_num = func.row_number().over(order_by=ext_order_clauses).label("row_num")
        numbered = select(combined.c.id, row_num).subquery()

        # Look up this track's row number (local tracks use UUID string, not ext:-prefixed)
        result = await db.execute(
            select(numbered.c.row_num).where(numbered.c.id == str(track_id))
        )
        row = result.scalar_one_or_none()
        if row is None:
            return TrackIndexResponse(index=-1)
        return TrackIndexResponse(index=row - 1)

    # Standard path: local tracks only
    base_query = select(Track.id)

    if search:
        search_filter = f"%{search}%"
        base_query = base_query.where(
            Track.title.ilike(search_filter)
            | Track.artist.ilike(search_filter)
            | Track.album.ilike(search_filter)
        )
    if artist:
        base_query = base_query.where(
            Track.artist.ilike(f"%{artist}%") | Track.album_artist.ilike(f"%{artist}%")
        )
    if album:
        base_query = base_query.where(Track.album.ilike(f"%{album}%"))
    if genre:
        base_query = base_query.where(Track.genre.ilike(f"%{genre}%"))
    if year_from is not None:
        base_query = base_query.where(Track.year >= year_from)
    if year_to is not None:
        base_query = base_query.where(Track.year <= year_to)

    if has_feature_filter:
        base_query = base_query.join(
            TrackAnalysis,
            (Track.id == TrackAnalysis.track_id) & (TrackAnalysis.bpm.isnot(None))
        )
        if energy_min is not None:
            base_query = base_query.where(TrackAnalysis.energy >= energy_min)
        if energy_max is not None:
            base_query = base_query.where(TrackAnalysis.energy <= energy_max)
        if valence_min is not None:
            base_query = base_query.where(TrackAnalysis.valence >= valence_min)
        if valence_max is not None:
            base_query = base_query.where(TrackAnalysis.valence <= valence_max)

    needs_analysis_join = False
    order_clauses: list[Any] = []
    if sort_by and sort_by != 'lastPlayed' and (sort_by in SORT_FIELD_MAP or sort_by in SORT_FEATURE_FIELDS):
        if sort_by in SORT_FIELD_MAP:
            sort_col = SORT_FIELD_MAP[sort_by]
            if sort_order == 'desc':
                order_clauses = [nulls_last(sort_col.desc()), Track.artist, Track.album, Track.track_number]
            else:
                order_clauses = [nulls_last(sort_col.asc()), Track.artist, Track.album, Track.track_number]
        else:
            needs_analysis_join = not has_feature_filter
            sort_col_attr = getattr(TrackAnalysis, sort_by, None)
            sort_expr = cast(sort_col_attr, Float) if sort_col_attr is not None else TrackAnalysis.bpm
            if sort_order == 'desc':
                order_clauses = [nulls_last(sort_expr.desc()), Track.artist, Track.album, Track.track_number]
            else:
                order_clauses = [nulls_last(sort_expr.asc()), Track.artist, Track.album, Track.track_number]
    else:
        order_clauses = [Track.artist, Track.album, Track.track_number]

    if needs_analysis_join:
        base_query = base_query.outerjoin(TrackAnalysis, Track.id == TrackAnalysis.track_id)

    row_num = func.row_number().over(order_by=order_clauses).label("row_num")
    base_query = base_query.add_columns(row_num)
    numbered_query = base_query.subquery()

    result = await db.execute(
        select(numbered_query.c.row_num).where(numbered_query.c.id == track_id)
    )
    row = result.scalar_one_or_none()

    if row is None:
        return TrackIndexResponse(index=-1)

    return TrackIndexResponse(index=row - 1)


@router.get("/{track_id}", response_model=TrackResponse)
async def get_track(db: DbSession, track_id: UUID) -> TrackResponse:
    """Get a single track with its latest analysis."""
    query = (
        select(Track)
        .options(selectinload(Track.analyses))
        .where(Track.id == track_id)
    )
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    response = TrackResponse.model_validate(track)

    # Get latest analysis features
    if track.analyses:
        latest = track.analyses[0]
        if latest.bpm is not None:
            response.features = TrackFeaturesResponse(
                bpm=latest.bpm,
                key=latest.key,
                energy=latest.energy,
                danceability=latest.danceability,
                valence=latest.valence,
                acousticness=latest.acousticness,
                instrumentalness=latest.instrumentalness,
                speechiness=latest.speechiness,
                loudness_lufs=latest.loudness_lufs,
                track_peak=latest.track_peak,
                replaygain_track_gain=latest.replaygain_track_gain,
            )

    return response


class AlbumGainResponse(BaseModel):
    """Album-level loudness/gain data."""

    album_gain_db: float | None = None
    album_peak: float | None = None
    track_count: int = 0


@router.get("/{track_id}/album-gain", response_model=AlbumGainResponse)
async def get_album_gain(
    db: DbSession,
    track_id: UUID,
) -> AlbumGainResponse:
    """Compute average LUFS for all tracks sharing the same album_artist + album.

    Returns album-level gain (dB relative to -14 LUFS target) and peak.
    Used for album-mode volume normalization.
    """
    # Get the track to find its album_artist and album
    track = await db.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    if not track.album:
        return AlbumGainResponse()

    # Find all tracks with same album_artist (or artist) and album
    album_artist = track.album_artist or track.artist
    if not album_artist:
        return AlbumGainResponse()

    # Get loudness_lufs for all tracks in this album
    album_query = (
        select(
            TrackAnalysis.loudness_lufs.label("lufs"),
            TrackAnalysis.track_peak.label("peak"),
        )
        .join(Track, Track.id == TrackAnalysis.track_id)
        .where(
            Track.album == track.album,
            (Track.album_artist == album_artist) | (Track.artist == album_artist),
            TrackAnalysis.loudness_lufs.isnot(None),
        )
    )

    result = await db.execute(album_query)
    rows = result.all()

    if not rows:
        return AlbumGainResponse()

    lufs_values = [r.lufs for r in rows if r.lufs is not None]
    peak_values = [r.peak for r in rows if r.peak is not None]

    if not lufs_values:
        return AlbumGainResponse(track_count=len(rows))

    # Average LUFS across album tracks
    import numpy as np

    avg_lufs = float(np.mean(lufs_values))
    max_peak = float(max(peak_values)) if peak_values else None

    # Album gain = target - average loudness (target defaults to -14 LUFS)
    album_gain_db = -14.0 - avg_lufs

    return AlbumGainResponse(
        album_gain_db=album_gain_db,
        album_peak=max_peak,
        track_count=len(lufs_values),
    )


@router.get("/{track_id}/similar")
async def get_similar_tracks(
    db: DbSession,
    track_id: UUID,
    limit: int = Query(10, ge=1, le=50),
) -> list[TrackResponse]:
    """Find similar tracks using embedding similarity (pgvector)."""
    # Get the track's embedding
    query = (
        select(TrackAnalysis.embedding)
        .where(TrackAnalysis.track_id == track_id)
    )
    result = await db.execute(query)
    embedding = result.scalar_one_or_none()

    if embedding is None:
        raise HTTPException(status_code=404, detail="Track not analyzed yet")

    # Find similar tracks using cosine distance
    # Note: pgvector uses <=> for cosine distance, <-> for L2 distance
    similar_query = (
        select(Track)
        .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
        .where(Track.id != track_id)
        .where(TrackAnalysis.embedding.isnot(None))
        .order_by(TrackAnalysis.embedding.cosine_distance(embedding))
        .limit(limit)
    )

    result = await db.execute(similar_query)
    tracks = result.scalars().all()

    return [TrackResponse.model_validate(t) for t in tracks]


class SimilarArtistInfo(BaseModel):
    """Similar artist with library status and external links."""

    name: str
    match_score: float
    in_library: bool
    track_count: int | None = None
    image_url: str | None = None
    lastfm_url: str | None = None
    bandcamp_url: str | None = None


class TrackDiscoverResponse(BaseModel):
    """Discovery data for a track - similar tracks and artists."""

    # Source track info
    track_id: str
    artist: str | None
    title: str | None

    # Similar tracks in library (from embedding similarity)
    similar_tracks: list[TrackResponse]

    # Similar artists (from Last.fm, enriched with library status)
    similar_artists: list[SimilarArtistInfo]

    # External discovery links
    bandcamp_artist_url: str | None = None
    bandcamp_track_url: str | None = None


@router.get("/{track_id}/discover", response_model=TrackDiscoverResponse)
async def get_track_discover(
    db: DbSession,
    track_id: UUID,
    track_limit: int = Query(6, ge=1, le=20),
    artist_limit: int = Query(6, ge=1, le=20),
) -> TrackDiscoverResponse:
    """Get discovery recommendations for a track.

    Combines:
    - Similar tracks from your library (embedding-based)
    - Similar artists (Last.fm, with library status)
    - External purchase/discovery links
    """

    from app.db.models import ArtistInfo, TrackStatus
    from app.services.lastfm import get_lastfm_service
    from app.services.search_links import generate_artist_search_url, generate_search_url

    # Get the source track
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    # Get similar tracks (reuse the embedding similarity logic)
    similar_tracks: list[TrackResponse] = []
    embedding_query = (
        select(TrackAnalysis.embedding)
        .where(TrackAnalysis.track_id == track_id)
    )
    embedding_result = await db.execute(embedding_query)
    embedding = embedding_result.scalar_one_or_none()

    if embedding is not None:
        similar_query = (
            select(Track)
            .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .where(Track.id != track_id)
            .where(TrackAnalysis.embedding.isnot(None))
            .order_by(TrackAnalysis.embedding.cosine_distance(embedding))
            .limit(track_limit)
        )
        sim_result = await db.execute(similar_query)
        similar_tracks = [TrackResponse.model_validate(t) for t in sim_result.scalars().all()]

    # Get similar artists from Last.fm (if artist is known)
    similar_artists: list[SimilarArtistInfo] = []

    if track.artist:
        artist_normalized = track.artist.lower().strip()

        # Check for cached artist info
        cached = await db.get(ArtistInfo, artist_normalized)
        raw_similar = cached.similar_artists if cached and cached.similar_artists else []

        # If not cached or stale, try to fetch from Last.fm
        if not raw_similar:
            lastfm_service = get_lastfm_service()
            if lastfm_service.is_configured():
                try:
                    info = await lastfm_service.get_artist_info(track.artist)
                    if info:
                        raw_similar = info.get("similar", {}).get("artist", [])
                except Exception:
                    pass  # Ignore Last.fm errors

        # Enrich similar artists with library status
        if raw_similar:
            similar_names = [s.get("name", "") for s in raw_similar if s.get("name")]
            similar_normalized = [n.lower().strip() for n in similar_names]

            # Batch query to check library status
            if similar_normalized:
                library_query = (
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
                lib_result = await db.execute(library_query)
                library_map = {row.artist_normalized: row.track_count for row in lib_result.all()}
            else:
                library_map = {}

            for similar in raw_similar[:artist_limit]:
                name = similar.get("name", "")
                if not name:
                    continue

                normalized = name.lower().strip()
                in_library = normalized in library_map
                track_count = library_map.get(normalized)

                # Extract image URL
                images = similar.get("image", [])
                image_url = None
                for img in images:
                    if img.get("size") == "large" and img.get("#text"):
                        image_url = img["#text"]
                        break
                if not image_url:
                    for img in images:
                        if img.get("#text"):
                            image_url = img["#text"]
                            break

                # Parse match score
                match_str = similar.get("match", "0")
                try:
                    match_score = float(match_str)
                except (ValueError, TypeError):
                    match_score = 0.0

                similar_artists.append(
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

    # Generate external discovery links
    bandcamp_artist_url = None
    bandcamp_track_url = None

    if track.artist:
        bandcamp_artist_url = generate_artist_search_url("bandcamp", track.artist)
    if track.artist and track.title:
        bandcamp_track_url = generate_search_url("bandcamp", track.artist, track.title)

    return TrackDiscoverResponse(
        track_id=str(track_id),
        artist=track.artist,
        title=track.title,
        similar_tracks=similar_tracks,
        similar_artists=similar_artists,
        bandcamp_artist_url=bandcamp_artist_url,
        bandcamp_track_url=bandcamp_track_url,
    )


# MIME types for audio formats
AUDIO_MIME_TYPES = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
}

# Formats that browsers can't natively decode — need server-side transcoding
TRANSCODE_EXTENSIONS = {".aiff", ".aif"}


def get_audio_mime_type(file_path: Path) -> str:
    """Get MIME type for audio file."""
    suffix = file_path.suffix.lower()
    return AUDIO_MIME_TYPES.get(suffix, "application/octet-stream")


@router.get("/{track_id}/stream")
async def stream_track(
    db: DbSession,
    track_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
) -> StreamingResponse:
    """Stream audio file with range request support for seeking."""
    # Get track from database
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        logger.warning("Stream request for unknown track_id=%s", track_id)
        raise HTTPException(status_code=404, detail="Track not found")

    # Trigger auto-enrichment in background if track has incomplete metadata
    from app.services.metadata_enrichment import needs_enrichment
    from app.services.tasks import propose_enrichment_for_track

    if needs_enrichment(track, check_artwork=False):
        background_tasks.add_task(propose_enrichment_for_track, str(track.id))

    file_path = Path(track.file_path)
    if not file_path.exists():
        logger.warning("Audio file missing: track_id=%s path=%s", track_id, file_path)
        raise HTTPException(status_code=404, detail="Audio file not found")

    # Fix FLAC files missing PTS timestamps (causes Chromium playback errors)
    if file_path.suffix.lower() == ".flac":
        from app.services.flac_remux import needs_remux, remux_flac_in_place

        try:
            if await needs_remux(file_path):
                logger.info("Re-muxing FLAC for PTS fix: %s", file_path.name)
                await remux_flac_in_place(file_path)
                # Update hash/size so scanner doesn't detect false change
                from app.services.scanner import compute_file_hash

                track.file_hash = compute_file_hash(file_path)
                track.file_size = file_path.stat().st_size
                track.file_modified_at = datetime.fromtimestamp(
                    file_path.stat().st_mtime
                )
                await db.commit()
        except Exception:
            logger.warning(
                "FLAC PTS check/re-mux failed for %s, serving as-is",
                track_id,
                exc_info=True,
            )

    # Transcode formats that browsers can't natively decode
    if file_path.suffix.lower() in TRANSCODE_EXTENSIONS:
        logger.debug("Transcoding track_id=%s path=%s to FLAC", track_id, file_path)
        return await _stream_transcoded(file_path)

    mime_type = get_audio_mime_type(file_path)
    logger.debug("Streaming track_id=%s path=%s type=%s", track_id, file_path, mime_type)

    from app.api.streaming import stream_file
    return await stream_file(file_path, request, mime_type)


async def _stream_transcoded(file_path: Path) -> StreamingResponse:
    """Transcode an audio file to FLAC via ffmpeg and stream the result."""
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", str(file_path), "-f", "flac", "-loglevel", "error", "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def stream_output():
        assert process.stdout is not None
        try:
            while chunk := await process.stdout.read(64 * 1024):
                yield chunk
        finally:
            await process.wait()

    return StreamingResponse(
        stream_output(),
        media_type="audio/flac",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/{track_id}/artwork")
async def get_track_artwork(
    db: DbSession,
    track_id: UUID,
    size: str = Query("full", pattern="^(full|thumb)$"),
) -> StreamingResponse:
    """Get album artwork for a track.

    Artwork is extracted from the audio file on first request and cached.
    """
    # Get track from database
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    # Compute album hash
    album_hash = compute_album_hash(track.artist, track.album)
    artwork_path = get_artwork_path(album_hash, size)

    # Check if artwork exists on disk
    if not artwork_path.exists():
        # Try to extract from audio file
        file_path = Path(track.file_path)
        if file_path.exists():
            from app.services.artwork import extract_and_save_artwork
            extract_and_save_artwork(file_path, track.artist, track.album)

        # Check again
        if not artwork_path.exists():
            raise HTTPException(status_code=404, detail="No artwork available")

    # Stream the artwork file
    def stream_artwork() -> Iterator[bytes]:
        with open(artwork_path, "rb") as f:
            yield f.read()

    return StreamingResponse(
        stream_artwork(),  # type: ignore[no-untyped-call]
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=31536000",  # Cache for 1 year
        },
    )


class ArtworkUploadResponse(BaseModel):
    """Response for artwork upload."""

    success: bool
    message: str
    embedded_in_file: bool = False
    saved_to_cache: bool = False


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_ARTWORK_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/{track_id}/artwork", response_model=ArtworkUploadResponse)
async def upload_track_artwork(
    db: DbSession,
    track_id: UUID,
    file: UploadFile,
    embed_in_file: bool = Query(True, description="Embed artwork in audio file tags"),
) -> ArtworkUploadResponse:
    """Upload or replace album artwork for a track.

    The artwork is saved to the cache and optionally embedded in the audio file.
    All tracks from the same album will share this artwork.

    Accepts JPEG, PNG, or WebP images up to 10MB.
    """
    from app.services.artwork import compute_album_hash, save_artwork
    from app.services.metadata_writer import write_artwork

    # Validate content type
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image type. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}",
        )

    # Read file data
    image_data = await file.read()

    if len(image_data) > MAX_ARTWORK_SIZE:
        raise HTTPException(
            status_code=400, detail=f"Image too large. Max size: {MAX_ARTWORK_SIZE // 1024 // 1024}MB"
        )

    if len(image_data) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    # Get track
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    # Save to cache
    album_hash = compute_album_hash(track.artist, track.album)
    saved_paths = save_artwork(image_data, album_hash)
    saved_to_cache = len(saved_paths) > 0

    # Embed in file if requested
    embedded_in_file = False
    embed_error = None

    if embed_in_file:
        file_path = Path(track.file_path)
        if file_path.exists():
            write_result = write_artwork(file_path, image_data, file.content_type or "image/jpeg")
            embedded_in_file = write_result.success
            if not write_result.success:
                embed_error = write_result.error

    message = "Artwork uploaded successfully"
    if embed_in_file and not embedded_in_file:
        message = f"Artwork saved to cache but failed to embed in file: {embed_error}"

    return ArtworkUploadResponse(
        success=saved_to_cache or embedded_in_file,
        message=message,
        embedded_in_file=embedded_in_file,
        saved_to_cache=saved_to_cache,
    )


@router.delete("/{track_id}/artwork", response_model=ArtworkUploadResponse)
async def delete_track_artwork(
    db: DbSession,
    track_id: UUID,
    remove_from_file: bool = Query(False, description="Also remove embedded artwork from audio file"),
) -> ArtworkUploadResponse:
    """Remove album artwork for a track.

    Removes artwork from the cache. Optionally removes embedded artwork from the audio file.
    Note: This affects all tracks from the same album.
    """
    from app.services.artwork import compute_album_hash, get_artwork_path

    # Get track
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    # Remove cached artwork
    album_hash = compute_album_hash(track.artist, track.album)
    removed_cache = False

    for size in ["full", "thumb"]:
        artwork_path = get_artwork_path(album_hash, size)
        if artwork_path.exists():
            artwork_path.unlink()
            removed_cache = True

    # Remove from file if requested (this is destructive and format-specific)
    removed_from_file = False
    if remove_from_file:
        # For now, we don't implement removal from files as it's risky
        # The user can re-embed new artwork instead
        pass

    if not removed_cache:
        return ArtworkUploadResponse(
            success=False,
            message="No cached artwork found to remove",
            embedded_in_file=False,
            saved_to_cache=False,
        )

    return ArtworkUploadResponse(
        success=True,
        message="Artwork removed from cache",
        embedded_in_file=removed_from_file,
        saved_to_cache=False,
    )


class LyricLineResponse(BaseModel):
    """A single line of lyrics with timing."""
    time: float
    text: str


class LyricsResponse(BaseModel):
    """Lyrics response schema."""
    synced: bool
    lines: list[LyricLineResponse]
    plain_text: str
    source: str


@router.get("/{track_id}/lyrics", response_model=LyricsResponse | None)
async def get_track_lyrics(
    db: DbSession,
    track_id: UUID,
) -> LyricsResponse | None:
    """
    Get lyrics for a track.
    Returns synced lyrics with timestamps if available, otherwise plain lyrics.
    """
    from app.services.lyrics import get_lyrics_service

    # Get track from database
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    if not track.title or not track.artist:
        raise HTTPException(
            status_code=400,
            detail="Track must have title and artist to search for lyrics"
        )

    # Search for lyrics
    lyrics_service = get_lyrics_service()
    lyrics = await lyrics_service.search(
        track_name=track.title,
        artist_name=track.artist,
        album_name=track.album,
        duration=track.duration_seconds
    )

    if not lyrics:
        raise HTTPException(status_code=404, detail="No lyrics found")

    return LyricsResponse(
        synced=lyrics.synced,
        lines=[LyricLineResponse(time=line.time, text=line.text) for line in lyrics.lines],
        plain_text=lyrics.plain_text,
        source=lyrics.source
    )


class PlayRecordRequest(BaseModel):
    """Request to record a track play."""

    duration_seconds: float | None = None  # How long the track was played


class PlayRecordResponse(BaseModel):
    """Response for play record."""

    track_id: UUID
    play_count: int
    total_play_seconds: float


@router.post("/{track_id}/played", response_model=PlayRecordResponse)
async def record_play(
    track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
    request: PlayRecordRequest | None = None,
) -> PlayRecordResponse:
    """Record that a track was played.

    Increments play count and updates last_played_at for the profile.
    Optionally records how long the track was played.
    """
    from datetime import datetime

    # Verify track exists
    track = await db.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    # Get or create play history record
    result = await db.execute(
        select(ProfilePlayHistory).where(
            ProfilePlayHistory.profile_id == profile.id,
            ProfilePlayHistory.track_id == track_id,
        )
    )
    play_history = result.scalar_one_or_none()

    if play_history:
        # Update existing record
        play_history.play_count += 1
        play_history.last_played_at = datetime.utcnow()
        if request and request.duration_seconds:
            play_history.total_play_seconds += request.duration_seconds
    else:
        # Create new record
        play_history = ProfilePlayHistory(
            profile_id=profile.id,
            track_id=track_id,
            play_count=1,
            last_played_at=datetime.utcnow(),
            total_play_seconds=request.duration_seconds if request and request.duration_seconds else 0.0,
        )
        db.add(play_history)

    await db.commit()
    await db.refresh(play_history)

    return PlayRecordResponse(
        track_id=track_id,
        play_count=play_history.play_count,
        total_play_seconds=play_history.total_play_seconds,
    )


class EnrichResponse(BaseModel):
    """Response for track enrichment request."""

    status: str
    message: str


@router.post("/{track_id}/enrich", response_model=EnrichResponse)
async def enrich_track_metadata(
    track_id: UUID,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> EnrichResponse:
    """Trigger background metadata enrichment for a track.

    Fire-and-forget endpoint that returns immediately.
    Enrichment runs in background if track has missing metadata.
    Fetches data from MusicBrainz/AcoustID, updates ID3 tags, and saves artwork.
    """
    from app.services.app_settings import get_app_settings_service
    from app.services.metadata_enrichment import needs_enrichment
    from app.services.tasks import run_track_enrichment

    # Check if auto-enrichment is enabled
    settings_service = get_app_settings_service()
    app_settings = settings_service.get()
    if not app_settings.auto_enrich_metadata:
        return EnrichResponse(status="disabled", message="Auto-enrichment is disabled")

    # Verify track exists
    track = await db.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    # Check if enrichment is needed
    if not needs_enrichment(track):
        return EnrichResponse(status="skipped", message="Track metadata is complete")

    # Queue background task (fire-and-forget)
    background_tasks.add_task(run_track_enrichment, str(track_id))

    return EnrichResponse(status="queued", message="Enrichment started in background")


class ProfilePlayStatsResponse(BaseModel):
    """Profile play statistics."""

    total_plays: int
    total_play_seconds: float
    unique_tracks: int
    top_tracks: list[dict[str, Any]]


@router.get("/stats/plays", response_model=ProfilePlayStatsResponse)
async def get_play_stats(
    db: DbSession,
    profile: RequiredProfile,
    limit: int = Query(10, ge=1, le=50),
) -> ProfilePlayStatsResponse:
    """Get play statistics for the current profile."""
    # Get all play history for profile
    result = await db.execute(
        select(ProfilePlayHistory, Track)
        .join(Track, ProfilePlayHistory.track_id == Track.id)
        .where(ProfilePlayHistory.profile_id == profile.id)
        .order_by(ProfilePlayHistory.play_count.desc())
    )
    rows = result.all()

    total_plays = sum(ph.play_count for ph, _ in rows)
    total_play_seconds = sum(ph.total_play_seconds for ph, _ in rows)
    unique_tracks = len(rows)

    top_tracks = [
        {
            "id": str(track.id),
            "title": track.title,
            "artist": track.artist,
            "play_count": ph.play_count,
            "total_play_seconds": ph.total_play_seconds,
            "last_played_at": ph.last_played_at.isoformat() if ph.last_played_at else None,
        }
        for ph, track in rows[:limit]
    ]

    return ProfilePlayStatsResponse(
        total_plays=total_plays,
        total_play_seconds=total_play_seconds,
        unique_tracks=unique_tracks,
        top_tracks=top_tracks,
    )


# ============================================================================
# Track Metadata Editing
# ============================================================================


class TrackMetadataUpdateRequest(BaseModel):
    """Request to update track metadata.

    All fields are optional - only provided fields are updated.
    """

    # Core metadata
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    track_number: int | None = None
    disc_number: int | None = None
    year: int | None = None
    genre: str | None = None

    # Extended metadata
    composer: str | None = None
    conductor: str | None = None
    lyricist: str | None = None
    grouping: str | None = None
    comment: str | None = None

    # Sort fields
    sort_artist: str | None = None
    sort_album: str | None = None
    sort_title: str | None = None

    # Lyrics
    lyrics: str | None = None

    # User overrides for analysis values (bpm, key, etc.)
    user_overrides: dict[str, Any] | None = None

    # Whether to write changes to the audio file tags
    write_to_file: bool = False


class TrackMetadataResponse(BaseModel):
    """Extended track response with all metadata fields."""

    id: UUID
    file_path: str

    # Core metadata
    title: str | None
    artist: str | None
    album: str | None
    album_artist: str | None
    track_number: int | None
    disc_number: int | None
    year: int | None
    genre: str | None

    # Extended metadata
    composer: str | None = None
    conductor: str | None = None
    lyricist: str | None = None
    grouping: str | None = None
    comment: str | None = None

    # Sort fields
    sort_artist: str | None = None
    sort_album: str | None = None
    sort_title: str | None = None

    # Lyrics
    lyrics: str | None = None

    # User overrides
    user_overrides: dict[str, Any] = {}

    # Audio info
    duration_seconds: float | None
    format: str | None

    # Analysis
    features: TrackFeaturesResponse | None = None

    # Write status (only set after update)
    file_write_status: str | None = None
    file_write_error: str | None = None

    model_config = ConfigDict(from_attributes=True)


@router.patch("/{track_id}/metadata", response_model=TrackMetadataResponse)
async def update_track_metadata(
    db: DbSession,
    track_id: UUID,
    request: TrackMetadataUpdateRequest,
) -> TrackMetadataResponse:
    """Update track metadata in the database and optionally write to audio file.

    Only provided fields are updated. Set write_to_file=true to also update
    the audio file's embedded tags.

    Returns the updated track with all metadata fields.
    """
    from pathlib import Path

    # Get track
    query = select(Track).options(selectinload(Track.analyses)).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    # Track which fields were updated for file writing
    updated_fields: dict[str, Any] = {}

    # Update only provided fields
    update_data = request.model_dump(exclude_unset=True, exclude={"write_to_file"})

    for field, value in update_data.items():
        if hasattr(track, field):
            setattr(track, field, value)
            updated_fields[field] = value

    # Commit database changes
    await db.commit()
    await db.refresh(track)

    # Prepare response
    response = TrackMetadataResponse.model_validate(track)

    # Get latest analysis features
    if track.analyses:
        latest = track.analyses[0]
        if latest.bpm is not None:
            # Merge user overrides with analysis features
            features_data: dict[str, Any] = {
                "bpm": latest.bpm,
                "key": latest.key,
                "energy": latest.energy,
                "danceability": latest.danceability,
                "valence": latest.valence,
                "acousticness": latest.acousticness,
                "instrumentalness": latest.instrumentalness,
                "speechiness": latest.speechiness,
                "loudness_lufs": latest.loudness_lufs,
                "track_peak": latest.track_peak,
                "replaygain_track_gain": latest.replaygain_track_gain,
            }
            # Apply user overrides
            if track.user_overrides:
                for key, val in track.user_overrides.items():
                    if key in features_data:
                        features_data[key] = val
            response.features = TrackFeaturesResponse(**features_data)

    # Optionally write to audio file
    if request.write_to_file and updated_fields:
        from app.services.metadata_writer import write_lyrics, write_metadata

        file_path = Path(track.file_path)

        # Separate lyrics from other metadata (needs special handling)
        lyrics_value = updated_fields.pop("lyrics", None)
        updated_fields.pop("user_overrides", None)  # Don't write to file

        # Write standard metadata
        if updated_fields:
            write_result = write_metadata(file_path, updated_fields)
            if write_result.success:
                response.file_write_status = "success"
            else:
                response.file_write_status = "partial"
                response.file_write_error = write_result.error

        # Write lyrics separately if provided
        if lyrics_value is not None:
            lyrics_result = write_lyrics(file_path, lyrics_value)
            if not lyrics_result.success:
                if response.file_write_status == "success":
                    response.file_write_status = "partial"
                response.file_write_error = (
                    f"{response.file_write_error or ''} Lyrics: {lyrics_result.error}".strip()
                )

        if response.file_write_status is None:
            response.file_write_status = "success"

    return response


@router.get("/{track_id}/metadata", response_model=TrackMetadataResponse)
async def get_track_metadata(
    db: DbSession,
    track_id: UUID,
) -> TrackMetadataResponse:
    """Get full track metadata including extended fields.

    Returns all metadata fields including composer, conductor, lyrics, etc.
    User overrides are merged with analysis features.
    """
    query = select(Track).options(selectinload(Track.analyses)).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    response = TrackMetadataResponse.model_validate(track)

    # Get latest analysis features with user overrides applied
    if track.analyses:
        latest = track.analyses[0]
        if latest.bpm is not None:
            features_data: dict[str, Any] = {
                "bpm": latest.bpm,
                "key": latest.key,
                "energy": latest.energy,
                "danceability": latest.danceability,
                "valence": latest.valence,
                "acousticness": latest.acousticness,
                "instrumentalness": latest.instrumentalness,
                "speechiness": latest.speechiness,
                "loudness_lufs": latest.loudness_lufs,
                "track_peak": latest.track_peak,
                "replaygain_track_gain": latest.replaygain_track_gain,
            }
            # Apply user overrides
            if track.user_overrides:
                for key, val in track.user_overrides.items():
                    if key in features_data:
                        features_data[key] = val
            response.features = TrackFeaturesResponse(**features_data)

    return response


# ============================================================================
# Bulk Metadata Editing
# ============================================================================


class BulkMetadataUpdateRequest(BaseModel):
    """Request to update metadata for multiple tracks."""

    track_ids: list[UUID]
    metadata: TrackMetadataUpdateRequest
    write_to_files: bool = False


class BulkEditErrorResponse(BaseModel):
    """Error for a single track in bulk edit."""

    track_id: str
    file_path: str
    error: str


class BulkEditResultResponse(BaseModel):
    """Result of bulk edit operation."""

    total: int
    successful: int
    failed: int
    errors: list[BulkEditErrorResponse]
    fields_updated: list[str]


@router.post("/bulk/metadata", response_model=BulkEditResultResponse)
async def bulk_update_metadata(
    db: DbSession,
    request: BulkMetadataUpdateRequest,
) -> BulkEditResultResponse:
    """Update metadata for multiple tracks at once.

    Only provided (non-None) fields in metadata are applied to all tracks.
    Set write_to_files=true to also update audio file tags.

    Returns summary with success/failure counts and any errors.
    """
    from app.services.bulk_editor import BulkEditorService

    service = BulkEditorService(db)

    # Extract metadata dict (exclude write_to_file as it's handled separately)
    metadata_dict = request.metadata.model_dump(
        exclude_unset=True, exclude={"write_to_file"}
    )

    result = await service.apply_to_tracks(
        track_ids=request.track_ids,
        metadata=metadata_dict,
        write_to_files=request.write_to_files,
    )

    return BulkEditResultResponse(
        total=result.total,
        successful=result.successful,
        failed=result.failed,
        errors=[
            BulkEditErrorResponse(
                track_id=e.track_id, file_path=e.file_path, error=e.error
            )
            for e in result.errors
        ],
        fields_updated=result.fields_updated,
    )


class CommonValuesRequest(BaseModel):
    """Request to get common values across tracks."""

    track_ids: list[UUID]


class CommonValuesResponse(BaseModel):
    """Common values across multiple tracks.

    Fields with identical values across all tracks have that value.
    Fields with different values are None (representing "mixed").
    """

    # Core metadata
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    track_number: int | None = None
    disc_number: int | None = None
    year: int | None = None
    genre: str | None = None

    # Extended metadata
    composer: str | None = None
    conductor: str | None = None
    lyricist: str | None = None
    grouping: str | None = None
    comment: str | None = None

    # Sort fields
    sort_artist: str | None = None
    sort_album: str | None = None
    sort_title: str | None = None

    # Lyrics
    lyrics: str | None = None

    # Track count for UI
    track_count: int = 0


@router.post("/bulk/common-values", response_model=CommonValuesResponse)
async def get_common_values(
    db: DbSession,
    request: CommonValuesRequest,
) -> CommonValuesResponse:
    """Get common field values across multiple tracks.

    Used to pre-fill the bulk edit form. Fields with different values
    across the selected tracks are returned as None (indicating "mixed").
    """
    from app.services.bulk_editor import BulkEditorService

    service = BulkEditorService(db)
    common = await service.get_common_values(request.track_ids)

    return CommonValuesResponse(
        **common,
        track_count=len(request.track_ids),
    )


# ============================================================================
# Metadata Lookup
# ============================================================================


class MetadataLookupRequest(BaseModel):
    """Request to look up track metadata from external sources."""

    title: str
    artist: str
    album: str | None = None


class MetadataCandidateResponse(BaseModel):
    """A candidate metadata match."""

    source: str
    source_id: str
    confidence: float
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    year: int | None = None
    track_number: int | None = None
    genre: str | None = None
    artwork_url: str | None = None


@router.post("/lookup/metadata", response_model=list[MetadataCandidateResponse])
async def lookup_metadata(
    request: MetadataLookupRequest,
) -> list[MetadataCandidateResponse]:
    """Look up track metadata from MusicBrainz.

    Returns a list of candidate matches sorted by confidence.
    Use this to find correct metadata for tracks with incomplete or wrong info.
    """
    from app.services.metadata_lookup import MetadataLookupService

    service = MetadataLookupService()
    candidates = await service.lookup_track(
        title=request.title,
        artist=request.artist,
        album=request.album,
        limit=5,
    )

    return [
        MetadataCandidateResponse(
            source=c.source,
            source_id=c.source_id,
            confidence=c.confidence,
            title=c.metadata.get("title"),
            artist=c.metadata.get("artist"),
            album=c.metadata.get("album"),
            album_artist=c.metadata.get("album_artist"),
            year=c.metadata.get("year"),
            track_number=c.metadata.get("track_number"),
            genre=c.metadata.get("genre"),
            artwork_url=c.artwork_url,
        )
        for c in candidates
    ]


# ============================================================================
# Audio Fingerprint Identification
# ============================================================================


class IdentifyCandidateResponse(BaseModel):
    """A candidate match from audio fingerprint identification."""

    acoustid_score: float  # 0.0-1.0 confidence score
    musicbrainz_recording_id: str
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    year: int | None = None
    track_number: int | None = None
    disc_number: int | None = None
    genre: str | None = None
    composer: str | None = None
    artwork_url: str | None = None
    features: dict[str, Any] = {}
    musicbrainz_url: str = ""


class IdentifyTrackResponse(BaseModel):
    """Response from track identification via audio fingerprint."""

    track_id: str
    fingerprint_generated: bool
    error: str | None = None
    error_type: str | None = None
    candidates: list[IdentifyCandidateResponse] = []


# ============================================================================
# Bulk Audio Fingerprint Identification
# ============================================================================
# NOTE: These routes MUST be defined before /{track_id}/identify to prevent
# FastAPI from matching "bulk" as a track_id.


class BulkIdentifyRequest(BaseModel):
    """Request to identify multiple tracks via audio fingerprinting."""

    track_ids: list[UUID]


class BulkIdentifyTaskResponse(BaseModel):
    """Response when starting a bulk identification task."""

    task_id: str
    status: str
    message: str


class BulkIdentifyProgress(BaseModel):
    """Progress of a bulk identification task."""

    task_id: str
    status: str  # 'running', 'completed', 'error'
    phase: str
    total_tracks: int
    processed_tracks: int
    current_track: str | None = None
    results: list[IdentifyTrackResponse] = []
    errors: list[str] = []
    started_at: str | None = None


@router.post("/bulk/identify", response_model=BulkIdentifyTaskResponse)
async def start_bulk_identify(
    db: DbSession,
    request: BulkIdentifyRequest,
    background_tasks: BackgroundTasks,
) -> BulkIdentifyTaskResponse:
    """Start bulk audio fingerprint identification for multiple tracks.

    Returns a task_id immediately. Poll GET /tracks/bulk/identify/{task_id}
    for progress and results.

    Rate limited to respect AcoustID (3/sec) and MusicBrainz (1/sec) limits.
    """
    import uuid

    from app.services.background import get_background_manager

    # Generate task ID
    task_id = str(uuid.uuid4())

    # Verify all tracks exist
    track_ids = [str(tid) for tid in request.track_ids]

    # Start background task
    background_manager = get_background_manager()
    background_tasks.add_task(
        background_manager.run_bulk_identify,
        task_id,
        track_ids,
    )

    return BulkIdentifyTaskResponse(
        task_id=task_id,
        status="started",
        message=f"Started identification for {len(track_ids)} tracks",
    )


@router.get("/bulk/identify/{task_id}", response_model=BulkIdentifyProgress)
async def get_bulk_identify_progress(
    task_id: str,
) -> BulkIdentifyProgress:
    """Get progress and results of a bulk identification task."""
    import json

    from app.services.background import get_background_manager

    background_manager = get_background_manager()

    try:
        data: bytes | None = background_manager.redis.get(f"familiar:identify:{task_id}")  # type: ignore[assignment]
        if not data:
            raise HTTPException(
                status_code=404,
                detail=f"Task {task_id} not found or expired",
            )

        progress = json.loads(data)
        return BulkIdentifyProgress(
            task_id=task_id,
            status=progress.get("status", "unknown"),
            phase=progress.get("phase", "unknown"),
            total_tracks=progress.get("total_tracks", 0),
            processed_tracks=progress.get("processed_tracks", 0),
            current_track=progress.get("current_track"),
            results=[
                IdentifyTrackResponse(**r) for r in progress.get("results", [])
            ],
            errors=progress.get("errors", []),
            started_at=progress.get("started_at"),
        )
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Failed to parse task progress",
        )


# ============================================================================
# Single Track Identification
# ============================================================================


@router.post("/{track_id}/identify", response_model=IdentifyTrackResponse)
async def identify_track(
    db: DbSession,
    track_id: UUID,
    min_score: float = Query(0.5, ge=0.0, le=1.0, description="Minimum confidence score"),
    limit: int = Query(5, ge=1, le=10, description="Maximum candidates to return"),
) -> IdentifyTrackResponse:
    """Identify a track using audio fingerprinting (AcoustID).

    Generates an audio fingerprint and looks up matching recordings in the
    AcoustID/MusicBrainz database. Returns candidate matches with full metadata
    including title, artist, album, year, genre, artwork URL, etc.

    Use this for the "Auto-populate" feature to fill in track metadata based
    on the audio content rather than text matching.

    Requires:
    - chromaprint/fpcalc installed on the system
    - AcoustID API key configured in Settings > API Keys
    """
    from app.services.audio_identification import get_audio_identification_service

    service = get_audio_identification_service()
    result = await service.identify_track(
        track_id=track_id,
        db=db,
        min_score=min_score,
        limit=limit,
    )

    return IdentifyTrackResponse(
        track_id=result.track_id,
        fingerprint_generated=result.fingerprint_generated,
        error=result.error,
        error_type=result.error_type,
        candidates=[
            IdentifyCandidateResponse(
                acoustid_score=c.acoustid_score,
                musicbrainz_recording_id=c.musicbrainz_recording_id,
                title=c.title,
                artist=c.artist,
                album=c.album,
                album_artist=c.album_artist,
                year=c.year,
                track_number=c.track_number,
                disc_number=c.disc_number,
                genre=c.genre,
                composer=c.composer,
                artwork_url=c.artwork_url,
                features=c.features,
                musicbrainz_url=c.musicbrainz_url,
            )
            for c in result.candidates
        ],
    )
