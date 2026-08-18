"""Rank a client's visualizers against a track (ADR-0064).

**The client sends its candidates and the server ranks them.** That shape is forced rather than
preferred: ADR-0029 point 5 keeps device identity uninvented, so the server has no key to file
"which visualizers does this device have" under — and ADR-0034 point 4 puts local bundles in a
directory on the device that the server is never told about. A ranking over visualizers the
listener does not have is not a ranking.

**Nothing is stored** (ADR-0064 point 6). The chosen visualizer and whether auto-select is on at
all are listener preferences and stay on the device under ADR-0029 point 4; this endpoint is a pure
function of the posted candidates and the track's analysis.
"""

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentProfile, DbSession
from app.api.exceptions import TrackNotFoundError
from app.db.models import Track, TrackAnalysis
from app.services.visualizer_affinity import (
    Affinity,
    Candidate,
    FeatureRange,
    rank_candidates,
)

router = APIRouter()


class VisualizerFeatureRange(BaseModel):
    """A bound a visualizer declares over one numeric analysis column.

    Either end may be omitted for an open range. A feature this server does not know, one that
    holds a string, and one this track was never analysed for are all inert — see
    `services/visualizer_affinity`.
    """

    feature: str
    minimum: float | None = None
    maximum: float | None = None


class VisualizerAffinity(BaseModel):
    """What a visualizer says it suits, as declared in its manifest."""

    tags: list[str] = Field(default_factory=list)
    ranges: list[VisualizerFeatureRange] = Field(default_factory=list)


class VisualizerCandidate(BaseModel):
    """One visualizer the client reports having loaded."""

    id: str
    affinity: VisualizerAffinity | None = None


class VisualizerRankingRequest(BaseModel):
    """The visualizers this client actually has, in the order it would otherwise use."""

    candidates: list[VisualizerCandidate] = Field(default_factory=list)


class RankedVisualizer(BaseModel):
    """One visualizer's placing, with enough detail to explain it.

    `ignored` is per-candidate rather than global because a declaration belongs to the visualizer
    that made it — it is what the picker shows an author whose tag did not land.
    """

    id: str
    score: float
    matched_tags: list[str] = Field(default_factory=list)
    matched_ranges: list[str] = Field(default_factory=list)
    unmatched_ranges: list[str] = Field(default_factory=list)
    ignored: list[str] = Field(default_factory=list)


class VisualizerRankingResponse(BaseModel):
    """Candidates best-first, or unranked when there was nothing to rank against."""

    visualizers: list[RankedVisualizer]
    # False when the track has no analysis row, or none of its features are populated. The client
    # must keep whatever it is showing rather than pick — a library mid-sync has a meaningful
    # fraction of such tracks, and switching to an arbitrary visualizer on each is worse than not
    # switching at all (ADR-0064).
    ranked: bool


def _to_domain(candidate: VisualizerCandidate) -> Candidate:
    affinity = candidate.affinity
    if affinity is None:
        return Candidate(id=candidate.id)
    return Candidate(
        id=candidate.id,
        affinity=Affinity(
            tags=tuple(affinity.tags),
            ranges=tuple(
                FeatureRange(feature=r.feature, minimum=r.minimum, maximum=r.maximum)
                for r in affinity.ranges
            ),
        ),
    )


@router.post("/{track_id}/visualizer-ranking", response_model=VisualizerRankingResponse)
async def rank_visualizers(
    track_id: UUID,
    request: VisualizerRankingRequest,
    db: DbSession,
    profile: CurrentProfile,
) -> VisualizerRankingResponse:
    """Rank the client's visualizers by how well each suits this track.

    A track that does not exist is a 404. A track that exists but has never been analysed is **not**
    — it returns the candidates in the order they were submitted with `ranked: false`, because
    "nothing to rank against" is an ordinary state on a library that is still being analysed, and
    an error would push the client into treating it as a failure.
    """
    track_exists = (
        await db.execute(select(Track.id).where(Track.id == track_id))
    ).scalar_one_or_none()
    if track_exists is None:
        raise TrackNotFoundError()

    analysis = (
        await db.execute(select(TrackAnalysis).where(TrackAnalysis.track_id == track_id))
    ).scalar_one_or_none()

    features = analysis.to_features_dict() if analysis else {}
    mood_tags = (analysis.mood_tags if analysis else None) or []

    if not features and not mood_tags:
        return VisualizerRankingResponse(
            visualizers=[
                RankedVisualizer(id=c.id, score=0.0) for c in request.candidates
            ],
            ranked=False,
        )

    ranked = rank_candidates(
        [_to_domain(c) for c in request.candidates], features, list(mood_tags)
    )

    return VisualizerRankingResponse(
        visualizers=[
            RankedVisualizer(
                id=r.id,
                score=round(r.score, 4),
                matched_tags=list(r.matched_tags),
                matched_ranges=list(r.matched_ranges),
                unmatched_ranges=list(r.unmatched_ranges),
                ignored=list(r.ignored),
            )
            for r in ranked
        ],
        ranked=True,
    )
