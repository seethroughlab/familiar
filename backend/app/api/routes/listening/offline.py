"""The precomputed offline ranking manifest (ADR-0006).

Ranks a device's downloaded tracks against each other with the same `score_candidate()` the
online path uses, so offline and online rankings are identical by construction rather than by
a second implementation agreeing with the first.

The server keeps no record of what a device has downloaded (ADR-0006 point 3), so the client
supplies it on every request.
"""

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import DbSession, RequiredProfile
from app.services.offline_manifest import (
    DEFAULT_NEIGHBOURS,
    build_manifest,
    eligible_seed_ids,
    known_presets,
)
from app.services.ranking_profiles import AMBIENT, RADIO

router = APIRouter(prefix="/offline", tags=["offline"])


# Ceiling on a manifest request. Generation for ~1,700 tracks measures well under two
# seconds, so this is headroom rather than a tight limit — but the work is quadratic-ish
# in the set size and a request should not be able to ask for unbounded compute.
MAX_OFFLINE_TRACKS = 10_000
class OfflineManifestRequest(BaseModel):
    """The tracks this device has downloaded.

    The server keeps no record of that (ADR-0006 decision point 3), so the client supplies
    it. Bounded because an unbounded list is an unbounded amount of work in a request.
    """

    track_ids: list[UUID] = Field(..., max_length=MAX_OFFLINE_TRACKS)
    neighbours: int = Field(default=DEFAULT_NEIGHBOURS, ge=1, le=50)


class ManifestNeighbour(BaseModel):
    track_id: UUID
    score: float


class ManifestEntryResponse(BaseModel):
    track_id: UUID
    neighbours: list[ManifestNeighbour]


class ManifestVariant(BaseModel):
    """One (weight profile, filter preset) combination."""

    profile: str
    filter_preset: str
    entries: list[ManifestEntryResponse]
    # Tracks fit to begin a session, for the offline equivalent of "surprise me".
    seed_track_ids: list[UUID]


class OfflineManifestResponse(BaseModel):
    """Everything a client needs to rank offline without carrying a scorer."""

    variants: list[ManifestVariant]
    # Echoed so the client can tell a stale manifest from a current one.
    track_count: int
@router.post("/manifest", response_model=OfflineManifestResponse)
async def offline_manifest(
    request: OfflineManifestRequest,
    db: DbSession,
    profile: RequiredProfile,
) -> OfflineManifestResponse:
    """Precompute offline rankings for a device's downloaded tracks.

    Ranks the supplied set against itself with the same `score_candidate()` the online
    path uses, so offline and online rankings are identical by construction rather than
    by two implementations intending to agree (ADR-0006).
    """
    variants: list[ManifestVariant] = []

    # Presets change the eligible pool, and the client already passes one, so a manifest
    # per preset is needed. Radio has no preset control, hence the single 'all' variant.
    combinations = [(AMBIENT, preset) for preset in known_presets()]
    combinations.append((RADIO, "all"))

    for ranking_profile, preset in combinations:
        entries = await build_manifest(
            db,
            request.track_ids,
            ranking_profile,
            filter_preset=preset,
            neighbours=request.neighbours,
        )
        seeds = await eligible_seed_ids(db, request.track_ids, filter_preset=preset)

        variants.append(
            ManifestVariant(
                profile=ranking_profile.name,
                filter_preset=preset,
                entries=[
                    ManifestEntryResponse(
                        track_id=e.track_id,
                        neighbours=[
                            ManifestNeighbour(track_id=tid, score=round(score, 4))
                            for tid, score in e.neighbours
                        ],
                    )
                    for e in entries
                ],
                seed_track_ids=seeds,
            )
        )

    return OfflineManifestResponse(variants=variants, track_count=len(request.track_ids))
