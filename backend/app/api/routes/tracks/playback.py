"""Track playback endpoints: record play, play stats."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession, RequiredProfile
from app.db.models import ProfilePlayHistory, Track
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

router = APIRouter()


class PlayRecordRequest(BaseModel):
    """Request to record a track play."""

    duration_seconds: float | None = None  # How long the track was played


class PlayRecordResponse(BaseModel):
    """Response for play record."""

    track_id: UUID
    play_count: int
    total_play_seconds: float


class ProfilePlayStatsResponse(BaseModel):
    """Profile play statistics."""

    total_plays: int
    total_play_seconds: float
    unique_tracks: int
    top_tracks: list[dict[str, Any]]


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
    """

    # Verify track exists
    track = await db.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

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
            total_play_seconds=request.duration_seconds if request and request.duration_seconds else 0.0,
        )
        db.add(play_history)

    await db.commit()
    await db.refresh(play_history)

    return PlayRecordResponse(
        track_id=track_id,
        play_count=play_history.play_count,
        total_play_seconds=play_history.total_play_seconds,
    )


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
        {
            "id": str(track.id),
            "title": track.title,
            "artist": track.artist,
            "play_count": ph.play_count,
            "total_play_seconds": ph.total_play_seconds,
            "last_played_at": ph.last_played_at.isoformat() if ph.last_played_at else None,
        }
        for ph, track in rows[:limit]
    ]

    return ProfilePlayStatsResponse(
        total_plays=total_plays,
        total_play_seconds=total_play_seconds,
        unique_tracks=unique_tracks,
        top_tracks=top_tracks,
    )
