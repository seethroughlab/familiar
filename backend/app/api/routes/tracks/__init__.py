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

from app.db.models import ExternalTrack, ProfilePlayHistory, Track

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
