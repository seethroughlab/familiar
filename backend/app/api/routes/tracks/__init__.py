"""Track endpoints — aggregated from sub-routers.

Shared Pydantic models live in ``app.api.schemas.tracks`` and are re-exported
here so sub-modules can still ``from app.api.routes.tracks import TrackResponse, ...``.
"""

import logging
from typing import Any

from fastapi import APIRouter
from sqlalchemy import Float, cast, nulls_last

from app.api.schemas.tracks import (  # noqa: F401 — re-export for sub-routers
    BatchTracksRequest,
    TrackDetailResponse,
    TrackFeaturesResponse,
    TrackIdsResponse,
    TrackListResponse,
    TrackResponse,
)
from app.db.models import ProfilePlayHistory, Track, TrackAnalysis

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

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
    'dateAdded': Track.created_at,
    'lastPlayed': ProfilePlayHistory.last_played_at,
    'playCount': ProfilePlayHistory.play_count,
}

# Sort fields that live on the *listener's* play history rather than on the track.
#
# They need the per-profile join, and they are meaningless without a profile — "how often have you
# played this" has no answer when there is no you. Ordering by one anyway would leave SQLAlchemy to
# invent a cross join against every row of `profile_play_history`, which is a wrong answer served
# slowly rather than an error.
PROFILE_SORT_FIELDS = {'lastPlayed', 'playCount'}

# Analysis features that need JSONB extraction
SORT_FEATURE_FIELDS = {
    'bpm', 'energy', 'danceability', 'valence',
    'acousticness', 'instrumentalness', 'key',
    'speechiness', 'brightness', 'harmonic_complexity', 'swing_ratio', 'syncopation',
}

# Allowlist of TrackAnalysis columns usable as generic feature filters (fx/fy)
FEATURE_FILTER_AXES = {
    "energy", "valence", "danceability", "acousticness", "instrumentalness",
    "speechiness", "brightness", "harmonic_complexity", "swing_ratio", "syncopation",
}

# MIME types for audio formats
AUDIO_MIME_TYPES = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg; codecs=opus",
    ".wav": "audio/wav",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
}


# ---------------------------------------------------------------------------
# Shared helper functions
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Aggregate sub-routers into top-level router
# ---------------------------------------------------------------------------

def apply_track_sort(
    query: Any,
    *,
    sort_by: str | None,
    sort_order: str,
    profile: Any | None,
    has_feature_filter: bool,
) -> Any:
    """Order a track query, or leave it to the caller's default when the request cannot be honoured.

    Shared by `/tracks` and `/tracks/ids` because they had the same twenty lines twice, and the two
    must agree: `/tracks/ids` builds the queue that `/tracks` paginates the metadata for, so an
    order that differs between them would hand the player a queue in one order and titles in
    another.

    Returns `None` when the sort was not applied, so the caller can fall back to its own default
    ordering rather than this function having to know what that is.
    """
    if not sort_by:
        return None

    if sort_by in SORT_FIELD_MAP:
        # A play-history field with nobody to attribute it to. Falling back beats ordering by a
        # column from a table that was never joined — see `PROFILE_SORT_FIELDS`.
        if sort_by in PROFILE_SORT_FIELDS and profile is None:
            return None

        sort_col = SORT_FIELD_MAP[sort_by]
        if sort_by in PROFILE_SORT_FIELDS:
            query = query.outerjoin(
                ProfilePlayHistory,
                (ProfilePlayHistory.track_id == Track.id)
                & (ProfilePlayHistory.profile_id == profile.id),
            )
        sort_expr = sort_col.desc() if sort_order == 'desc' else sort_col.asc()
    elif sort_by in SORT_FEATURE_FIELDS:
        if not has_feature_filter:
            query = query.outerjoin(TrackAnalysis, Track.id == TrackAnalysis.track_id)
        sort_col_attr = getattr(TrackAnalysis, sort_by, None)
        expr = cast(sort_col_attr, Float) if sort_col_attr is not None else TrackAnalysis.bpm
        sort_expr = expr.desc() if sort_order == 'desc' else expr.asc()
    else:
        return None

    # `Track.id` last so the total order is unique. Without it, 866 tie groups covering 2,846 rows
    # share an ordering key, and OFFSET paging over a non-unique order may repeat or skip rows
    # between pages.
    return query.order_by(
        nulls_last(sort_expr), Track.artist, Track.album, Track.track_number, Track.id
    )


from app.api.routes.tracks.discovery import router as discovery_router  # noqa: E402
from app.api.routes.tracks.identification import router as identification_router  # noqa: E402
from app.api.routes.tracks.listing import list_tracks  # noqa: E402
from app.api.routes.tracks.listing import router as listing_router  # noqa: E402
from app.api.routes.tracks.metadata import router as metadata_router  # noqa: E402
from app.api.routes.tracks.playback import router as playback_router  # noqa: E402
from app.api.routes.tracks.streaming import router as streaming_router  # noqa: E402
from app.api.routes.tracks.visualizers import router as visualizers_router  # noqa: E402

# No tag on the aggregator (ADR-0072 point 2): the seven sub-routers below own their own, and
# ADR-0073 splits them across six — `tracks`, `plays`, `metadata`, `identification`, `discover`
# and `visualizers`. A tag here would concatenate onto every one of them.
router = APIRouter(prefix="/tracks")
# Register list_tracks directly on the parent router so its path is ""
# (matches /tracks without trailing slash). Using "/" on a sub-router
# only matches /tracks/ and the SPA catch-all intercepts the redirect.
router.get("", response_model=TrackListResponse, tags=["tracks"])(list_tracks)
router.include_router(listing_router)
router.include_router(streaming_router)
router.include_router(discovery_router)
router.include_router(playback_router)
router.include_router(metadata_router)
router.include_router(identification_router)
router.include_router(visualizers_router)

