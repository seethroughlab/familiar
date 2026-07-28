"""Queue suggestion endpoints (ADR-0005).

Radio: tracks the listener is likely to enjoy, slipped into a queue they are already
playing. It reuses the ambient ranking engine under the `RADIO` weight profile rather
than being a second recommender — see `services/ranking_profiles.py`.

Unlike the ambient routes this is **profile-aware**. Ambient ranks purely on musical
compatibility with the current track and needs no notion of who is listening; radio
weighs taste and past skips, which are per-profile by definition. `ambient` is
allowlisted as profile-less in `scripts/lint_profile_contracts.py`; this module
deliberately does not inherit that exemption.
"""

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import TrackNotFoundError, ValidationError
from app.api.schemas.tracks import TrackResponse
from app.db.models import Track
from app.services.ambient import get_candidates
from app.services.offline_manifest import (
    DEFAULT_NEIGHBOURS,
    build_manifest,
    eligible_seed_ids,
    known_presets,
)
from app.services.ranking_profiles import AMBIENT, RADIO, get_profile

router = APIRouter(prefix="/queue", tags=["queue"])

# Ceiling on a manifest request. Generation for ~1,700 tracks measures well under two
# seconds, so this is headroom rather than a tight limit — but the work is quadratic-ish
# in the set size and a request should not be able to ask for unbounded compute.
MAX_OFFLINE_TRACKS = 10_000


# ============================================================================
# Request / Response schemas
# ============================================================================


class SuggestionsRequest(BaseModel):
    """What to suggest from, and what to avoid repeating."""

    # UUID rather than str: the ambient routes take strings and call bare `UUID(...)`,
    # so a malformed id raises ValueError and surfaces as a 500 instead of a 422.
    current_track_id: UUID
    recent_track_ids: list[UUID] = Field(default_factory=list)
    recent_artist_names: list[str] = Field(default_factory=list)
    profile: str = Field(default="radio", description="Ranking profile: 'radio' or 'ambient'")
    limit: int = Field(default=5, ge=1, le=20)


class Suggestion(BaseModel):
    """One suggested track and how well it scored."""

    track: TrackResponse
    score: float


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


class SuggestionsResponse(BaseModel):
    """Ranked suggestions for insertion into the playing queue."""

    suggestions: list[Suggestion]
    # Size of the retrieved candidate pool before ranking, and whether it was too small
    # to rank meaningfully — the client can use this to stay quiet rather than insert
    # something arbitrary.
    pool_size: int
    pool_collapsed: bool


# ============================================================================
# Endpoints
# ============================================================================


@router.post("/suggestions", response_model=SuggestionsResponse)
async def suggestions(
    request: SuggestionsRequest,
    db: DbSession,
    profile: RequiredProfile,
) -> SuggestionsResponse:
    """Rank tracks to insert into the queue, weighted by this profile's taste."""
    try:
        ranking_profile = get_profile(request.profile)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    candidates, pool_size, pool_collapsed = await get_candidates(
        db,
        current_track_id=request.current_track_id,
        recent_track_ids=request.recent_track_ids,
        recent_artist_names=request.recent_artist_names,
        limit=request.limit,
        profile=ranking_profile,
        profile_id=profile.id,
    )

    if not candidates:
        # An unanalyzed or unknown seed collapses the pool rather than erroring, which is
        # ambient's existing contract; preserve it so the client can just not insert.
        return SuggestionsResponse(suggestions=[], pool_size=pool_size, pool_collapsed=pool_collapsed)

    # The ranker works in descriptors, so fetch the tracks themselves for the handful
    # that survived — the client inserts tracks, not descriptors. `analyses` is eagerly
    # loaded because `Track.analysis_version` returns 0 when it is not.
    ordered_ids = [c.descriptor.track_id for c in candidates]
    tracks = (
        (
            await db.execute(
                select(Track)
                .options(selectinload(Track.analyses))
                .where(Track.id.in_(ordered_ids))
            )
        )
        .scalars()
        .all()
    )
    by_id = {t.id: t for t in tracks}

    if not by_id:
        raise TrackNotFoundError("Suggested tracks could not be loaded")

    return SuggestionsResponse(
        suggestions=[
            Suggestion(
                track=TrackResponse.model_validate(by_id[c.descriptor.track_id]),
                score=round(c.compatibility_score, 4),
            )
            for c in candidates
            if c.descriptor.track_id in by_id
        ],
        pool_size=pool_size,
        pool_collapsed=pool_collapsed,
    )


@router.post("/offline-manifest", response_model=OfflineManifestResponse)
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
