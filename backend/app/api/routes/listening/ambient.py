"""Ambient — a session of harmonically-chained snippets (ADR-0106).

Seed resolution, candidate ranking and track descriptors for ambient mode. All three are thin
wrappers over `services/ambient.py`, which is the shared ranking engine ADR-0005 named and which
never stopped being called: radio, the offline manifest, playlist generation, collection
suggestions and the MCP discovery handler all reach it. **Only these routes went**, deleted by
ADR-0077 in `db7a8dc7` once the web player took their only client with it, and restored here at
the same paths.

Unlike radio this is **profile-less**, and deliberately: ambient ranks on musical compatibility
with the current track and has no notion of who is listening. `ambient` is allowlisted for that in
`scripts/lint_profile_contracts.py`, which it has been throughout — radio's docstring next door
records that it does not inherit the exemption.

What these responses carry that no other endpoint does, and which is why ADR-0106 point 3 refused
to serve this from `/radio/suggestions`: `energy_shape`, `dynamic_range_db`, `section_count` and
`modal_character`, none of which are on `TrackFeaturesResponse` — plus a `key` that actually
arrives, which radio's `TrackResponse.features` does not, because that path validates from `Track`
and `Track` has no `features` attribute to populate it from.

**Four defects from the deleted version are not reproduced here.** They are called out at their
sites below: string ids that 500 on malformed input, an `intensity` that was accepted and dropped,
a `pool_collapsed` that was hardcoded, and seeds that could be files no longer on disk.
"""

from typing import Literal
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

# `Literal` rather than the `Field(pattern=...)` the deleted routes used. A regex constraint
# generates as a bare `String` in the Swift client, which is how `ServerRadioSuggestionsSource`
# came to carry a comment warning that sending "RADIO" instead of "radio" returns a 400 — "a good
# error, but only if anyone reads it". An enum cannot be got wrong at the call site.
FilterPreset = Literal["all", "soft", "dark", "instrumental"]
Intensity = Literal["quiet", "balanced", "immersive"]


# ============================================================================
# Request / Response schemas
# ============================================================================

class AmbientDescriptorResponse(BaseModel):
    """A track reduced to what an ambient transition is decided from.

    `key` drives the drone's pitch, `duration_seconds` and `energy_shape` place the snippet
    window; the rest is what `score_candidate` weighs, returned so a client can show its working.
    """

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
    """How to start a session: from a track, from an artist, or from nothing in particular."""

    # UUID rather than str, which is what the deleted version took. It called bare `UUID(...)` on
    # the string, so a malformed id raised ValueError and surfaced as a 500 where it should have
    # been a 422 — the defect `radio.py:39-40` documented while these routes still existed, and
    # which outlived the file that had it (ADR-0106 point 5).
    track_id: UUID | None = None
    artist: str | None = None
    surprise_me: bool = False
    filter_preset: FilterPreset = "all"
    # Accepted *and used*. The deleted route declared no intensity at all and called
    # `get_candidates` without one, so the opening candidates of every session were ranked as
    # `balanced` however the listener had set it, and only the second batch obeyed. The setting
    # appeared to do nothing until a session had run for a minute.
    intensity: Intensity = "balanced"


class SeedResponse(BaseModel):
    seed: AmbientDescriptorResponse
    initial_candidates: list[AmbientCandidateResponse]
    pool_size: int
    # Reported rather than hardcoded `False`, which is what the deleted route did — so a filter
    # that left nothing to chain to looked, at the moment of starting, exactly like one that had.
    pool_collapsed: bool


class CandidatesRequest(BaseModel):
    current_track_id: UUID
    filter_preset: FilterPreset = "all"
    # Swaps two of `AMBIENT`'s weights rather than changing the pool — see
    # `ranking_profiles.py`'s `intensity_overrides`.
    intensity: Intensity = "balanced"
    recent_track_ids: list[UUID] = Field(default_factory=list)
    recent_artist_names: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=50)


class CandidatesResponse(BaseModel):
    candidates: list[AmbientCandidateResponse]
    pool_size: int
    # True when the filters left too little to rank meaningfully. A normal answer, not a failure:
    # the client says so and stops, rather than chaining to something arbitrary.
    pool_collapsed: bool


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/seed", response_model=SeedResponse)
async def seed(request: SeedRequest, db: DbSession) -> SeedResponse:
    """Resolve a seed track and return initial candidates."""
    resolved = None

    if request.track_id:
        resolved = await get_track_descriptor(db, request.track_id)
    elif request.artist:
        resolved = await find_seed_by_artist(db, request.artist, request.filter_preset)
    elif request.surprise_me:
        resolved = await pick_surprise_seed(db, request.filter_preset)

    if not resolved:
        raise NotFoundError("No suitable seed track found")

    ranked, pool_size, pool_collapsed = await get_candidates(
        db,
        current_track_id=resolved.track_id,
        filter_preset=request.filter_preset,
        intensity=request.intensity,
        limit=10,
    )

    return SeedResponse(
        seed=AmbientDescriptorResponse(**resolved.to_dict()),
        initial_candidates=[
            AmbientCandidateResponse(**c.to_dict()) for c in ranked
        ],
        pool_size=pool_size,
        pool_collapsed=pool_collapsed,
    )


@router.post("/candidates", response_model=CandidatesResponse)
async def candidates(request: CandidatesRequest, db: DbSession) -> CandidatesResponse:
    """Get ranked candidates for ambient continuation."""
    ranked, pool_size, pool_collapsed = await get_candidates(
        db,
        current_track_id=request.current_track_id,
        filter_preset=request.filter_preset,
        intensity=request.intensity,
        recent_track_ids=request.recent_track_ids,
        recent_artist_names=request.recent_artist_names,
        limit=request.limit,
    )

    return CandidatesResponse(
        candidates=[AmbientCandidateResponse(**c.to_dict()) for c in ranked],
        pool_size=pool_size,
        pool_collapsed=pool_collapsed,
    )


@router.get("/descriptor/{track_id}", response_model=AmbientDescriptorResponse)
async def descriptor(track_id: UUID, db: DbSession) -> AmbientDescriptorResponse:
    """Get a single track's ambient descriptor."""
    resolved = await get_track_descriptor(db, track_id)
    if not resolved:
        raise TrackNotFoundError("Track not found or not analyzed")
    return AmbientDescriptorResponse(**resolved.to_dict())
