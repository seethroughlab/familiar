"""Radio — what to play next (ADR-0005).

Tracks the listener is likely to enjoy, slipped into a queue they are already playing. It reuses
the ambient ranking engine under the `RADIO` weight profile rather than being a second
recommender — see `services/ranking_profiles.py`.

Unlike the ambient routes this is **profile-aware**. Ambient ranks purely on musical
compatibility with the current track and needs no notion of who is listening; radio weighs taste
and past skips, which are per-profile by definition. `ambient` is allowlisted as profile-less in
`scripts/lint_profile_contracts.py`; this module deliberately does not inherit that exemption.

This docstring described the whole of `queue.py` before ADR-0074 split it — which was the
clearest evidence of the conflation, a file named for a queue and documented as radio.
"""

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import (
    TrackNotFoundError,
    ValidationError,
)
from app.api.schemas.tracks import TrackFeaturesResponse, TrackResponse
from app.db.models import Track
from app.services.ambient import get_candidates
from app.services.ranking_profiles import get_profile

router = APIRouter(prefix="/radio", tags=["radio"])


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
class SuggestionsResponse(BaseModel):
    """Ranked suggestions for insertion into the playing queue."""

    suggestions: list[Suggestion]
    # Size of the retrieved candidate pool before ranking, and whether it was too small
    # to rank meaningfully — the client can use this to stay quiet rather than insert
    # something arbitrary.
    pool_size: int
    pool_collapsed: bool


def _with_features(track: Track) -> TrackResponse:
    """A suggestion, with the analysis a client might want to show alongside it.

    **This was `model_validate(track)` and so answered `features: null` every time.** `Track` has no
    `features` attribute — only `routes/tracks/listing.py` ever populated one — so the field has
    been on this response since it existed and has never once been filled. A client asking radio
    what to play next got a track it could not tell you the key or tempo of.

    Free here: `analyses` is already eagerly loaded above, because `Track.analysis_version` returns
    0 when it is not.
    """
    response = TrackResponse.model_validate(track)
    if track.analyses:
        response.features = TrackFeaturesResponse.from_analysis(track.analyses[0])
    return response


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
        return SuggestionsResponse(
            suggestions=[], pool_size=pool_size, pool_collapsed=pool_collapsed
        )

    # The ranker works in descriptors, so fetch the tracks themselves for the handful
    # that survived — the client inserts tracks, not descriptors. `analyses` is eagerly
    # loaded because `Track.analysis_version` returns 0 when it is not.
    ordered_ids = [c.descriptor.track_id for c in candidates]
    tracks = (
        (
            await db.execute(
                select(Track).options(selectinload(Track.analyses)).where(Track.id.in_(ordered_ids))
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
                track=_with_features(by_id[c.descriptor.track_id]),
                score=round(c.compatibility_score, 4),
            )
            for c in candidates
            if c.descriptor.track_id in by_id
        ],
        pool_size=pool_size,
        pool_collapsed=pool_collapsed,
    )
