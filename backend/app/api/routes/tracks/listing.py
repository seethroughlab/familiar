"""Track listing endpoints: list IDs, list tracks, get track, get index, batch."""

import math
import random
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import Float, cast, func, nulls_last, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentProfile, DbSession
from app.api.exceptions import TrackNotFoundError, ValidationError
from app.db.models import ProfileFavorite, ProfilePlayHistory, Track, TrackAnalysis, TrackStatus
from app.services.taste_weighting import (
    SHUFFLE_PRESETS,
    apply_artist_variety,
    compute_track_weight,
)
from app.utils.time import utcnow

from . import (
    FEATURE_FILTER_AXES,
    SORT_FEATURE_FIELDS,
    SORT_FIELD_MAP,
    BatchTracksRequest,
    TrackFeaturesResponse,
    TrackIdsResponse,
    TrackListResponse,
    TrackResponse,
    apply_track_sort,
)

router = APIRouter()


class TrackIndexResponse(BaseModel):
    """Response for track index lookup."""

    index: int


# --- Weighted shuffle presets ---


@router.get("/ids", response_model=TrackIdsResponse)
async def list_track_ids(
    db: DbSession,
    profile: CurrentProfile,
    shuffle: bool = Query(False, description="Randomize the order of IDs"),
    shuffle_preset: str | None = Query(None, description="Weighted shuffle preset name"),
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
    sort_by: str | None = Query(None, description="Column to sort by"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$", description="Sort direction"),
) -> TrackIdsResponse:
    """Get all track IDs matching filters.

    Returns only IDs (lightweight) for shuffle-all functionality.
    Use shuffle=true to get randomized order via ORDER BY random().
    Use start_with to ensure a specific track appears first (useful when shuffle=true).
    """

    has_feature_filter = any(
        x is not None for x in [energy_min, energy_max, valence_min, valence_max]
    )
    has_fx = bool(fx and fx in FEATURE_FILTER_AXES and any(x is not None for x in [fx_min, fx_max]))
    has_fy = bool(fy and fy in FEATURE_FILTER_AXES and any(x is not None for x in [fy_min, fy_max]))
    has_feature_filter = has_feature_filter or has_fx or has_fy

    query = select(Track.id).where(Track.status == TrackStatus.ACTIVE)

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

    # --- Weighted shuffle path ---
    preset = SHUFFLE_PRESETS.get(shuffle_preset) if shuffle_preset else None
    if preset and profile:
        # Fetch IDs with play history and favorite status
        weighted_query = (
            query.add_columns(
                Track.artist,
                Track.created_at,
                ProfilePlayHistory.play_count,
                ProfilePlayHistory.last_played_at,
                ProfileFavorite.favorited_at,
            )
            .outerjoin(
                ProfilePlayHistory,
                (ProfilePlayHistory.track_id == Track.id)
                & (ProfilePlayHistory.profile_id == profile.id),
            )
            .outerjoin(
                ProfileFavorite,
                (ProfileFavorite.track_id == Track.id) & (ProfileFavorite.profile_id == profile.id),
            )
        )
        result = await db.execute(weighted_query)
        rows = result.all()

        if not rows:
            return TrackIdsResponse(ids=[], total=total)

        # Find max play count for normalization
        max_pc = max((r.play_count or 0) for r in rows) or 1
        now = utcnow()

        # Compute weights and apply Efraimidis-Spirakis weighted sampling
        weighted_items: list[tuple[float, str, str | None]] = []
        for row in rows:
            w = compute_track_weight(
                play_count=row.play_count,
                last_played_at=row.last_played_at,
                created_at=row.created_at,
                is_favorited=row.favorited_at is not None,
                preset=preset,
                now=now,
                max_play_count=max_pc,
            )
            # Efraimidis-Spirakis key: u^(1/w) where u ~ Uniform(0,1)
            # Equivalent to sorting by -ln(u)/w descending, or ln(u)/w descending
            u = random.random()
            key = math.log(max(u, 1e-15)) / w
            weighted_items.append((key, str(row[0]), row.artist))

        # Sort by key descending for weighted random order
        weighted_items.sort(key=lambda x: x[0], reverse=True)

        # Apply artist variety post-processing
        ids_with_artists = [(tid, artist) for _, tid, artist in weighted_items]
        track_ids = apply_artist_variety(ids_with_artists, preset.variety_strength)

        if start_with and start_with in track_ids:
            track_ids.remove(start_with)
            track_ids.insert(0, start_with)

        return TrackIdsResponse(ids=track_ids, total=total)

    # --- Standard shuffle/sort path ---
    if shuffle:
        query = query.order_by(func.random())
    elif (
        sorted_query := apply_track_sort(
            query,
            sort_by=sort_by,
            sort_order=sort_order,
            profile=profile,
            has_feature_filter=has_feature_filter,
        )
    ) is not None:
        query = sorted_query
    else:
        # `Track.id` last for the same reason as `list_tracks`, so this endpoint's order and the
        # paged list's order are the same total order rather than two orders that agree on ties
        # by luck.
        query = query.order_by(Track.artist, Track.album, Track.track_number, Track.id)

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
    """
    if len(request.ids) > 50:
        raise ValidationError("Maximum 50 tracks per batch")

    if not request.ids:
        return []

    try:
        uuids = [UUID(id_str) for id_str in request.ids]
    except ValueError:
        raise ValidationError("Invalid track ID format")

    query = select(Track).where(Track.id.in_(uuids))
    result = await db.execute(query)
    tracks_by_id: dict[str, Track] = {str(t.id): t for t in result.scalars().all()}

    # Fetch play history
    play_history_map: dict[UUID, ProfilePlayHistory] = {}
    if profile and uuids:
        ph_query = select(ProfilePlayHistory).where(
            ProfilePlayHistory.profile_id == profile.id,
            ProfilePlayHistory.track_id.in_(uuids),
        )
        ph_result = await db.execute(ph_query)
        play_history_map = {ph.track_id: ph for ph in ph_result.scalars().all()}

    # Return in requested order, skipping missing tracks
    ordered_tracks: list[TrackResponse] = []
    for id_str in request.ids:
        if id_str in tracks_by_id:
            track = tracks_by_id[id_str]
            response = TrackResponse.model_validate(track)
            if track.id in play_history_map:
                ph = play_history_map[track.id]
                response.last_played_at = ph.last_played_at
                response.play_count = ph.play_count
            ordered_tracks.append(response)

    return ordered_tracks


# Registered twice on purpose — see the comment in tracks/__init__.py. The parent
# router serves "" (/tracks) and this serves "/" (/tracks/), because the SPA catch-all
# swallows FastAPI's redirect. They are one API operation, so only the parent
# registration appears in the schema; otherwise a generated client would grow two
# identical listTracks methods (ADR-0007).
@router.get("/", response_model=TrackListResponse, include_in_schema=False)
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
    updated_since: datetime | None = Query(
        None,
        description=(
            "Return only tracks changed at or after this time, in any status. "
            "The delta cursor for an offline library cache."
        ),
    ),
    sort_by: str | None = Query(None, description="Column to sort by"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$", description="Sort direction"),
) -> TrackListResponse:
    """List tracks with optional filtering and pagination.

    ``updated_since`` is the delta cursor for the offline library cache (ADR-0011 points 6 and 7).
    Two things about it are deliberate and load-bearing:

    **It returns rows in every status, not just active.** A cursor query cannot see a deleted row,
    but Familiar does not delete tracks — it sets ``status`` away from active, which is an ORM
    update, so ``updated_at`` moves. Returning those rows is what lets a client drop them from its
    cache. Filtering to active here would make removals invisible, and a cache would drift in the
    one direction nobody notices.

    **The comparison is ``>=``, so the boundary row comes back again.** A client passing back the
    ``max(updated_at)`` it last saw re-receives the rows carrying exactly that timestamp, which is
    an idempotent re-write on its side. ``>`` would silently skip any row sharing the boundary
    instant. This does not close the general cursor race — a row committed during a refresh with a
    timestamp below the cursor is missed by either comparison — and the active count from
    ``GET /library/fingerprint`` is the backstop that catches that drift.
    """

    has_feature_filter = any(
        x is not None for x in [energy_min, energy_max, valence_min, valence_max]
    )
    has_fx_list = bool(
        fx and fx in FEATURE_FILTER_AXES and any(x is not None for x in [fx_min, fx_max])
    )
    has_fy_list = bool(
        fy and fy in FEATURE_FILTER_AXES and any(x is not None for x in [fy_min, fy_max])
    )
    has_feature_filter = has_feature_filter or has_fx_list or has_fy_list

    # A delta sees every status; a normal listing sees only active ones. See the docstring.
    if updated_since is not None:
        # **Normalised to naive UTC before it reaches the driver.** `Track.updated_at` is
        # `TIMESTAMP WITHOUT TIME ZONE`, and asyncpg refuses to compare that against an aware
        # datetime — "can't subtract offset-naive and offset-aware datetimes", surfaced as a 500.
        #
        # Every real client hits this. The generated Swift client sends RFC 3339 with a `Z`, which
        # FastAPI parses into an aware datetime; only a hand-written naive string gets through. It
        # was found by a live slice test against the real server, having passed every fixture test
        # and every curl by hand, because both supplied the naive form.
        cursor = updated_since
        if cursor.tzinfo is not None:
            cursor = cursor.astimezone(UTC).replace(tzinfo=None)
        query = select(Track).where(Track.updated_at >= cursor)
    else:
        query = select(Track).where(Track.status == TrackStatus.ACTIVE)

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
            TrackAnalysis, (Track.id == TrackAnalysis.track_id) & (TrackAnalysis.bpm.isnot(None))
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
    if (
        sorted_query := apply_track_sort(
            query,
            sort_by=sort_by,
            sort_order=sort_order,
            profile=profile,
            has_feature_filter=has_feature_filter,
        )
    ) is not None:
        query = sorted_query
    else:
        # `Track.id` last so the total order is unique. Without it, 866 tie groups covering
        # 2,846 rows share an ordering key, and OFFSET paging over a non-unique order may
        # repeat or skip rows between pages — silently omitting tracks from anything that
        # pages the whole library.
        if updated_since is not None:
            # A delta pages in cursor order, for the same uniqueness reason: the client is
            # walking a changed set, and ordering it by artist would interleave rows whose
            # position moves as the set changes underneath the paging.
            query = query.order_by(Track.updated_at, Track.id)
        else:
            query = query.order_by(Track.artist, Track.album, Track.track_number, Track.id)

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
    profile: CurrentProfile,
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
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
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
    has_fx_idx = bool(
        fx and fx in FEATURE_FILTER_AXES and any(x is not None for x in [fx_min, fx_max])
    )
    has_fy_idx = bool(
        fy and fy in FEATURE_FILTER_AXES and any(x is not None for x in [fy_min, fy_max])
    )
    has_feature_filter = has_feature_filter or has_fx_idx or has_fy_idx

    base_query = select(Track.id).where(Track.status == TrackStatus.ACTIVE)

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
            TrackAnalysis, (Track.id == TrackAnalysis.track_id) & (TrackAnalysis.bpm.isnot(None))
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
    if sort_by and (sort_by in SORT_FIELD_MAP or sort_by in SORT_FEATURE_FIELDS):
        if sort_by in SORT_FIELD_MAP:
            sort_col = SORT_FIELD_MAP[sort_by]
            if sort_by == "lastPlayed" and profile:
                base_query = base_query.outerjoin(
                    ProfilePlayHistory,
                    (ProfilePlayHistory.track_id == Track.id)
                    & (ProfilePlayHistory.profile_id == profile.id),
                )
            if sort_order == "desc":
                order_clauses = [
                    nulls_last(sort_col.desc()),
                    Track.artist,
                    Track.album,
                    Track.track_number,
                    Track.id,
                ]
            else:
                order_clauses = [
                    nulls_last(sort_col.asc()),
                    Track.artist,
                    Track.album,
                    Track.track_number,
                    Track.id,
                ]
        else:
            needs_analysis_join = not has_feature_filter
            sort_col_attr = getattr(TrackAnalysis, sort_by, None)
            sort_expr = (
                cast(sort_col_attr, Float) if sort_col_attr is not None else TrackAnalysis.bpm
            )
            if sort_order == "desc":
                order_clauses = [
                    nulls_last(sort_expr.desc()),
                    Track.artist,
                    Track.album,
                    Track.track_number,
                    Track.id,
                ]
            else:
                order_clauses = [
                    nulls_last(sort_expr.asc()),
                    Track.artist,
                    Track.album,
                    Track.track_number,
                    Track.id,
                ]
    else:
        # Must match `list_tracks` exactly, `Track.id` tiebreaker included: this endpoint reports
        # a track's row number in that same ordering, so any divergence returns an index the
        # paged list does not agree with.
        order_clauses = [Track.artist, Track.album, Track.track_number, Track.id]

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
    query = select(Track).options(selectinload(Track.analyses)).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

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
