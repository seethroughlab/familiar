"""Track endpoints — aggregated from sub-routers.

Shared Pydantic models, helpers, and constants live here so sub-modules
can ``from app.api.routes.tracks import TrackResponse, ...`` etc.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.db.models import ProfilePlayHistory, Track

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic response / request models (shared across sub-routers)
# ---------------------------------------------------------------------------

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
    brightness: float | None = None
    harmonic_complexity: float | None = None
    swing_ratio: float | None = None
    syncopation: float | None = None
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


class BatchTracksRequest(BaseModel):
    """Request to fetch tracks by IDs."""

    ids: list[str]


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
    'lastPlayed': ProfilePlayHistory.last_played_at,
}

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

from app.api.routes.tracks.discovery import router as discovery_router  # noqa: E402
from app.api.routes.tracks.identification import router as identification_router  # noqa: E402
from app.api.routes.tracks.listing import list_tracks  # noqa: E402
from app.api.routes.tracks.listing import router as listing_router  # noqa: E402
from app.api.routes.tracks.metadata import router as metadata_router  # noqa: E402
from app.api.routes.tracks.playback import router as playback_router  # noqa: E402
from app.api.routes.tracks.streaming import router as streaming_router  # noqa: E402

router = APIRouter(prefix="/tracks", tags=["tracks"])
# Register list_tracks directly on the parent router so its path is ""
# (matches /tracks without trailing slash). Using "/" on a sub-router
# only matches /tracks/ and the SPA catch-all intercepts the redirect.
router.get("", response_model=TrackListResponse)(list_tracks)
router.include_router(listing_router)
router.include_router(streaming_router)
router.include_router(discovery_router)
router.include_router(playback_router)
router.include_router(metadata_router)
router.include_router(identification_router)
