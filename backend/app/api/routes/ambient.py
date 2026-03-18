"""Ambient mode API endpoints.

Provides seed selection, candidate ranking, and track descriptors
for the ambient playback feature.
"""

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import DbSession
from app.api.exceptions import NotFoundError, TrackNotFoundError
from app.services.ambient import (
    find_seed_by_artist,
    get_candidates,
    get_track_descriptor,
    pick_surprise_seed,
)

router = APIRouter(prefix="/ambient", tags=["ambient"])


# ============================================================================
# Request / Response schemas
# ============================================================================

class AmbientDescriptorResponse(BaseModel):
    track_id: str
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration_seconds: float | None = None
    key: str | None = None
    bpm: float | None = None
    energy: float | None = None
    brightness: float | None = None
    valence: float | None = None
    instrumentalness: float | None = None
    speechiness: float | None = None
    dynamic_range_db: float | None = None
    energy_shape: str | None = None
    section_count: int | None = None
    modal_character: str | None = None
    acousticness: float | None = None


class AmbientCandidateResponse(BaseModel):
    descriptor: AmbientDescriptorResponse
    compatibility_score: float
    key_compatibility: float
    suggested_start_pct: float
    suggested_end_pct: float


class SeedRequest(BaseModel):
    track_id: str | None = None
    artist: str | None = None
    surprise_me: bool = False
    filter_preset: str = Field(default="all", pattern=r"^(all|soft|dark|instrumental)$")


class SeedResponse(BaseModel):
    seed: AmbientDescriptorResponse
    initial_candidates: list[AmbientCandidateResponse]
    pool_size: int


class CandidatesRequest(BaseModel):
    current_track_id: str
    filter_preset: str = Field(default="all", pattern=r"^(all|soft|dark|instrumental)$")
    intensity: str = Field(default="balanced", pattern=r"^(quiet|balanced|immersive)$")
    recent_track_ids: list[str] = Field(default_factory=list)
    recent_artist_names: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=50)


class CandidatesResponse(BaseModel):
    candidates: list[AmbientCandidateResponse]
    pool_size: int
    pool_collapsed: bool


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/seed", response_model=SeedResponse)
async def get_seed(request: SeedRequest, db: DbSession) -> SeedResponse:
    """Resolve a seed track and return initial candidates."""
    seed = None

    if request.track_id:
        seed = await get_track_descriptor(db, UUID(request.track_id))
    elif request.artist:
        seed = await find_seed_by_artist(db, request.artist, request.filter_preset)
    elif request.surprise_me:
        seed = await pick_surprise_seed(db, request.filter_preset)

    if not seed:
        raise NotFoundError("No suitable seed track found")

    # Get initial candidates
    candidates, pool_size, _ = await get_candidates(
        db,
        current_track_id=seed.track_id,
        filter_preset=request.filter_preset,
        limit=10,
    )

    return SeedResponse(
        seed=AmbientDescriptorResponse(**seed.to_dict()),
        initial_candidates=[
            AmbientCandidateResponse(**c.to_dict()) for c in candidates
        ],
        pool_size=pool_size,
    )


@router.post("/candidates", response_model=CandidatesResponse)
async def get_next_candidates(request: CandidatesRequest, db: DbSession) -> CandidatesResponse:
    """Get ranked candidates for ambient continuation."""
    recent_ids = [UUID(tid) for tid in request.recent_track_ids]

    candidates, pool_size, pool_collapsed = await get_candidates(
        db,
        current_track_id=UUID(request.current_track_id),
        filter_preset=request.filter_preset,
        intensity=request.intensity,
        recent_track_ids=recent_ids,
        recent_artist_names=request.recent_artist_names,
        limit=request.limit,
    )

    return CandidatesResponse(
        candidates=[AmbientCandidateResponse(**c.to_dict()) for c in candidates],
        pool_size=pool_size,
        pool_collapsed=pool_collapsed,
    )


@router.get("/descriptor/{track_id}", response_model=AmbientDescriptorResponse)
async def get_descriptor(track_id: str, db: DbSession) -> AmbientDescriptorResponse:
    """Get a single track's ambient descriptor."""
    descriptor = await get_track_descriptor(db, UUID(track_id))
    if not descriptor:
        raise TrackNotFoundError("Track not found or not analyzed")
    return AmbientDescriptorResponse(**descriptor.to_dict())
