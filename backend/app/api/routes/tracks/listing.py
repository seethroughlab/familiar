"""Track listing endpoints: list IDs, list tracks, get track, get index, batch."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Float, String, cast, func, literal, nulls_last, select, union_all
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentProfile, DbSession
from app.db.models import ExternalTrack, ProfilePlayHistory, Track, TrackAnalysis

from . import (
    FEATURE_FILTER_AXES,
    SORT_FEATURE_FIELDS,
    SORT_FIELD_MAP,
    BatchTracksRequest,
    TrackFeaturesResponse,
    TrackIdsResponse,
    TrackListResponse,
    TrackResponse,
    _apply_metadata_filters_to_external,
    _external_track_to_response,
)

router = APIRouter()


class TrackIndexResponse(BaseModel):
    """Response for track index lookup."""

    index: int


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
    fx: str | None = Query(None, description="Feature name for X-axis filter"),
    fx_min: float | None = Query(None, ge=0, le=1),
    fx_max: float | None = Query(None, ge=0, le=1),
    fy: str | None = Query(None, description="Feature name for Y-axis filter"),
    fy_min: float | None = Query(None, ge=0, le=1),
    fy_max: float | None = Query(None, ge=0, le=1),
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
    has_fx = bool(fx and fx in FEATURE_FILTER_AXES and any(x is not None for x in [fx_min, fx_max]))
    has_fy = bool(fy and fy in FEATURE_FILTER_AXES and any(x is not None for x in [fy_min, fy_max]))
    has_feature_filter = has_feature_filter or has_fx or has_fy
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
        if has_fx:
            fx_col = getattr(TrackAnalysis, fx)
            if fx_min is not None:
                query = query.where(fx_col >= fx_min)
            if fx_max is not None:
                query = query.where(fx_col <= fx_max)
        if has_fy:
            fy_col = getattr(TrackAnalysis, fy)
            if fy_min is not None:
                query = query.where(fy_col >= fy_min)
            if fy_max is not None:
                query = query.where(fy_col <= fy_max)

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


@router.get("/", response_model=TrackListResponse)
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
    fx: str | None = Query(None, description="Feature name for X-axis filter"),
    fx_min: float | None = Query(None, ge=0, le=1),
    fx_max: float | None = Query(None, ge=0, le=1),
    fy: str | None = Query(None, description="Feature name for Y-axis filter"),
    fy_min: float | None = Query(None, ge=0, le=1),
    fy_max: float | None = Query(None, ge=0, le=1),
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
    has_fx_list = bool(fx and fx in FEATURE_FILTER_AXES and any(x is not None for x in [fx_min, fx_max]))
    has_fy_list = bool(fy and fy in FEATURE_FILTER_AXES and any(x is not None for x in [fy_min, fy_max]))
    has_feature_filter = has_feature_filter or has_fx_list or has_fy_list
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
                            brightness=latest.brightness,
                            harmonic_complexity=latest.harmonic_complexity,
                            swing_ratio=latest.swing_ratio,
                            syncopation=latest.syncopation,
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
        if has_fx_list:
            fx_col = getattr(TrackAnalysis, fx)
            if fx_min is not None:
                query = query.where(fx_col >= fx_min)
            if fx_max is not None:
                query = query.where(fx_col <= fx_max)
        if has_fy_list:
            fy_col = getattr(TrackAnalysis, fy)
            if fy_min is not None:
                query = query.where(fy_col >= fy_min)
            if fy_max is not None:
                query = query.where(fy_col <= fy_max)

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
                    brightness=latest.brightness,
                    harmonic_complexity=latest.harmonic_complexity,
                    swing_ratio=latest.swing_ratio,
                    syncopation=latest.syncopation,
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
    fx: str | None = Query(None),
    fx_min: float | None = Query(None, ge=0, le=1),
    fx_max: float | None = Query(None, ge=0, le=1),
    fy: str | None = Query(None),
    fy_min: float | None = Query(None, ge=0, le=1),
    fy_max: float | None = Query(None, ge=0, le=1),
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
    has_fx_idx = bool(fx and fx in FEATURE_FILTER_AXES and any(x is not None for x in [fx_min, fx_max]))
    has_fy_idx = bool(fy and fy in FEATURE_FILTER_AXES and any(x is not None for x in [fy_min, fy_max]))
    has_feature_filter = has_feature_filter or has_fx_idx or has_fy_idx
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
        if has_fx_idx:
            fx_col = getattr(TrackAnalysis, fx)
            if fx_min is not None:
                base_query = base_query.where(fx_col >= fx_min)
            if fx_max is not None:
                base_query = base_query.where(fx_col <= fx_max)
        if has_fy_idx:
            fy_col = getattr(TrackAnalysis, fy)
            if fy_min is not None:
                base_query = base_query.where(fy_col >= fy_min)
            if fy_max is not None:
                base_query = base_query.where(fy_col <= fy_max)

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
                brightness=latest.brightness,
                harmonic_complexity=latest.harmonic_complexity,
                swing_ratio=latest.swing_ratio,
                syncopation=latest.syncopation,
                loudness_lufs=latest.loudness_lufs,
                track_peak=latest.track_peak,
                replaygain_track_gain=latest.replaygain_track_gain,
            )

    return response
