"""Track-related Pydantic schemas shared across route modules."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import UTCDateTime


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
    status: str = "active"
    analysis_version: int
    # When the scanner first saw the file. `from_attributes` fills it straight off
    # `Track.created_at`, which is what ADR-0021's `dateAdded` column sorts by — the sort
    # shipped without the field, so the column was built, seen blank on every row, and removed.
    created_at: UTCDateTime | None = None
    # The delta cursor for the offline library cache (ADR-0011 point 6). `Track.updated_at` carries
    # `onupdate=func.now()`, and an ordinary rescan goes through `_update_track` — plain ORM
    # attribute assignment — so the timestamp moves when a track's tags change. A client keeps the
    # highest value it has seen and passes it back as `updated_since`.
    updated_at: UTCDateTime | None = None
    features: TrackFeaturesResponse | None = None
    # Play history (profile-specific, populated when profile header is present)
    last_played_at: UTCDateTime | None = None
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
