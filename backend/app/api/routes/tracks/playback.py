"""Track playback endpoints: record play, skip, rejection, and play stats.

Three endpoints write listening feedback, each named for what it does (ADR-0004):

- ``POST /{track_id}/played``   bumps ProfilePlayHistory **and** writes a PlayEvent
- ``POST /{track_id}/skipped``  writes a PlayEvent only; the aggregate is untouched
- ``POST /{track_id}/rejected`` writes a PlayEvent only; the aggregate is untouched

Keeping skips off ``/played`` is deliberate: ``record_play`` increments ``play_count``
unconditionally, so routing skips through it would inflate the aggregate that ADR-0004
promises to leave alone.
"""

import logging
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import TrackNotFoundError
from app.db.models import PlayEvent, ProfilePlayHistory, Track
from app.utils.time import to_naive_utc, to_rfc3339, utcnow

logger = logging.getLogger(__name__)

router = APIRouter()

# PlayEvent.outcome values
OUTCOME_COMPLETED = "completed"
OUTCOME_SKIPPED = "skipped"
OUTCOME_REJECTED = "rejected"
OUTCOME_ERRORED = "errored"

# At or above this fraction of the track, a play counts as completed rather than skipped.
# Starting value only — ADR-0004 defers empirical tuning until real data exists.
COMPLETION_RATIO_THRESHOLD = 0.85

# Why the client stopped playing the track. Determines how `outcome` is derived.
#   "natural" — track ended on its own, or advanced via crossfade / iOS background advance.
#               Always completed: the crossfade path advances at roughly
#               `duration - crossfadeDuration`, so a fully-played track reads ~0.9.
#   "user"    — the listener moved on. Derived from completion_ratio, so pressing next at
#               95% is a completion and a short track played in full is not a skip.
#   "error"   — playback failed. Recorded as `errored` and never used as a taste signal:
#               a broken file is not a track the listener dislikes.
StopReason = Literal["natural", "user", "error"]

PlayContext = Literal[
    "library", "album", "playlist", "artist", "ephemeral", "radio", "ambient", "other"
]


class PlayRecordRequest(BaseModel):
    """Request to record a track play."""

    duration_seconds: float | None = None  # How long the track was played

    # Per-event detail (ADR-0004). All optional — older clients omit them entirely and
    # the existing /played behaviour is unchanged.
    track_duration: float | None = None
    completion_ratio: float | None = None
    context: PlayContext | None = None
    source_track_id: UUID | None = None
    # When the listening actually happened. Omitted by clients that post immediately; supplied by
    # clients replaying a queue built while offline, which is exactly when the arrival time is
    # wrong. ADR-0004 point 7 expects events to survive being offline, and an event that reports
    # the moment it was finally uploaded misdates the only listening that needed queueing.
    started_at: datetime | None = None


class PlayRecordResponse(BaseModel):
    """Response for play record."""

    track_id: UUID
    play_count: int
    total_play_seconds: float


class ListenEventRequest(BaseModel):
    """Request to record a listening event without touching the play aggregate."""

    played_seconds: float | None = None
    track_duration: float | None = None
    # Supplied when the client already knows it; otherwise computed from the two above.
    completion_ratio: float | None = None
    context: PlayContext | None = None
    # The track this one was suggested from, for radio insertions.
    source_track_id: UUID | None = None
    reason: StopReason = "user"
    # When the listening actually happened. Omitted by clients that post immediately; supplied by
    # clients replaying a queue built while offline, which is exactly when the arrival time is
    # wrong. ADR-0004 point 7 expects events to survive being offline, and an event that reports
    # the moment it was finally uploaded misdates the only listening that needed queueing.
    started_at: datetime | None = None


class ListenEventResponse(BaseModel):
    """Response for a recorded listening event."""

    track_id: UUID
    outcome: str
    completion_ratio: float


def _resolve_completion_ratio(
    played_seconds: float | None,
    track_duration: float | None,
    explicit: float | None,
) -> float:
    """Return the fraction of the track that was played, clamped to 0.0-1.0.

    Prefers the client's value when given, otherwise derives it. Falls back to 0.0 when
    duration is unknown or zero, so a missing duration never looks like a completion.
    """
    if explicit is not None:
        return max(0.0, min(1.0, explicit))
    if played_seconds is None or not track_duration:
        return 0.0
    return max(0.0, min(1.0, played_seconds / track_duration))


def _resolve_started_at(supplied: datetime | None) -> datetime:
    """When the listening happened, trusting the client only as far as is safe.

    Normalised to naive UTC because the column is TIMESTAMP WITHOUT TIME ZONE and a browser or
    Swift client sends an offset-aware value — comparing the two raises, which is how the queue
    session endpoints returned 500 on their first real request.

    Clamped to now: a device with a fast clock would otherwise write events into the future, where
    every "recent listening" window would keep finding them.
    """
    now = utcnow()
    if supplied is None:
        return now
    return min(to_naive_utc(supplied) or now, now)


def _derive_outcome(reason: StopReason, completion_ratio: float) -> str:
    """Map a stop reason plus completion to a PlayEvent outcome."""
    if reason == "error":
        return OUTCOME_ERRORED
    if reason == "natural":
        return OUTCOME_COMPLETED
    return OUTCOME_COMPLETED if completion_ratio >= COMPLETION_RATIO_THRESHOLD else OUTCOME_SKIPPED


async def _get_track_or_404(db: DbSession, track_id: UUID) -> Track:
    track = await db.get(Track, track_id)
    if not track:
        raise TrackNotFoundError()
    return track


class TopTrackStat(BaseModel):
    """A track in the profile's most-played list."""

    id: str
    title: str | None = None
    artist: str | None = None
    play_count: int
    total_play_seconds: float
    last_played_at: str | None = None


class ProfilePlayStatsResponse(BaseModel):
    """Profile play statistics."""

    total_plays: int
    total_play_seconds: float
    unique_tracks: int
    top_tracks: list[TopTrackStat]


@router.post("/{track_id}/played", response_model=PlayRecordResponse)
async def record_play(
    track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
    request: PlayRecordRequest | None = None,
) -> PlayRecordResponse:
    """Record that a track was played.

    Increments play count and updates last_played_at for the profile.
    Optionally records how long the track was played.

    Also writes a `completed` PlayEvent. Reaching this endpoint *is* the definition of a
    play — the client only calls it once scrobble thresholds are met — so the outcome is
    not derived from completion_ratio here. Derivation belongs on /skipped.
    """

    # Verify track exists
    await _get_track_or_404(db, track_id)

    # Get or create play history record
    result = await db.execute(
        select(ProfilePlayHistory).where(
            ProfilePlayHistory.profile_id == profile.id,
            ProfilePlayHistory.track_id == track_id,
        )
    )
    play_history = result.scalar_one_or_none()

    if play_history:
        # Update existing record
        play_history.play_count += 1
        play_history.last_played_at = utcnow()
        if request and request.duration_seconds:
            play_history.total_play_seconds += request.duration_seconds
    else:
        # Create new record
        play_history = ProfilePlayHistory(
            profile_id=profile.id,
            track_id=track_id,
            play_count=1,
            last_played_at=utcnow(),
            total_play_seconds=request.duration_seconds
            if request and request.duration_seconds
            else 0.0,
        )
        db.add(play_history)

    # Per-play event, written in the same transaction as the aggregate so the two
    # cannot diverge.
    played_seconds = request.duration_seconds if request else None
    db.add(
        PlayEvent(
            profile_id=profile.id,
            track_id=track_id,
            source_track_id=request.source_track_id if request else None,
            started_at=_resolve_started_at(request.started_at if request else None),
            played_seconds=played_seconds or 0.0,
            track_duration=request.track_duration if request else None,
            completion_ratio=_resolve_completion_ratio(
                played_seconds,
                request.track_duration if request else None,
                request.completion_ratio if request else None,
            ),
            outcome=OUTCOME_COMPLETED,
            context=request.context if request else None,
        )
    )

    await db.commit()
    await db.refresh(play_history)

    return PlayRecordResponse(
        track_id=track_id,
        play_count=play_history.play_count,
        total_play_seconds=play_history.total_play_seconds,
    )


async def _record_listen_event(
    db: DbSession,
    profile_id: UUID,
    track_id: UUID,
    request: ListenEventRequest | None,
    outcome: str | None = None,
) -> ListenEventResponse:
    """Write a PlayEvent without touching ProfilePlayHistory.

    When `outcome` is given it is used verbatim; otherwise it is derived from the stop
    reason and completion ratio.
    """
    await _get_track_or_404(db, track_id)

    body = request or ListenEventRequest()
    completion_ratio = _resolve_completion_ratio(
        body.played_seconds, body.track_duration, body.completion_ratio
    )
    resolved = outcome or _derive_outcome(body.reason, completion_ratio)

    db.add(
        PlayEvent(
            profile_id=profile_id,
            track_id=track_id,
            source_track_id=body.source_track_id,
            started_at=_resolve_started_at(body.started_at),
            played_seconds=body.played_seconds or 0.0,
            track_duration=body.track_duration,
            completion_ratio=completion_ratio,
            outcome=resolved,
            context=body.context,
        )
    )
    await db.commit()

    return ListenEventResponse(
        track_id=track_id,
        outcome=resolved,
        completion_ratio=completion_ratio,
    )


@router.post("/{track_id}/skipped", response_model=ListenEventResponse)
async def record_skip(
    track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
    request: ListenEventRequest | None = None,
) -> ListenEventResponse:
    """Record that playback of a track stopped before it was scrobbled.

    ProfilePlayHistory is not modified — only completed plays count toward it.

    The outcome is derived rather than assumed: a track abandoned at 95%, or a short
    track played in full, is recorded as `completed`, and a failed load is recorded as
    `errored` so it never reaches the taste signal.
    """
    return await _record_listen_event(db, profile.id, track_id, request)


@router.post("/{track_id}/rejected", response_model=ListenEventResponse)
async def record_rejection(
    track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
    request: ListenEventRequest | None = None,
) -> ListenEventResponse:
    """Record an explicit thumbs-down on a track, typically a radio insertion.

    A deliberate rejection is a stronger signal than a skip and is stored distinctly.
    ProfilePlayHistory is not modified.
    """
    return await _record_listen_event(db, profile.id, track_id, request, outcome=OUTCOME_REJECTED)


@router.get("/stats/plays", response_model=ProfilePlayStatsResponse)
async def get_play_stats(
    db: DbSession,
    profile: RequiredProfile,
    limit: int = Query(10, ge=1, le=50),
) -> ProfilePlayStatsResponse:
    """Get play statistics for the current profile."""
    # Get all play history for profile
    result = await db.execute(
        select(ProfilePlayHistory, Track)
        .join(Track, ProfilePlayHistory.track_id == Track.id)
        .where(ProfilePlayHistory.profile_id == profile.id)
        .order_by(ProfilePlayHistory.play_count.desc())
    )
    rows = result.all()

    total_plays = sum(ph.play_count for ph, _ in rows)
    total_play_seconds = sum(ph.total_play_seconds for ph, _ in rows)
    unique_tracks = len(rows)

    top_tracks = [
        TopTrackStat(
            id=str(track.id),
            title=track.title,
            artist=track.artist,
            play_count=ph.play_count,
            total_play_seconds=ph.total_play_seconds,
            last_played_at=to_rfc3339(ph.last_played_at) if ph.last_played_at else None,
        )
        for ph, track in rows[:limit]
    ]

    return ProfilePlayStatsResponse(
        total_plays=total_plays,
        total_play_seconds=total_play_seconds,
        unique_tracks=unique_tracks,
        top_tracks=top_tracks,
    )
