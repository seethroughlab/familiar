"""Track playback endpoints: record play, play stats, enrichment."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession, RequiredProfile
from app.db.models import ProfilePlayHistory, Track

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


class EnrichResponse(BaseModel):
    """Response for track enrichment request."""

    status: str
    message: str


class BatchEnrichRequest(BaseModel):
    """Request body for batch enrichment."""

    track_ids: list[str]


class BatchEnrichResponse(BaseModel):
    """Response for batch enrichment request."""

    queued: int
    skipped: int
    total: int


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
    from datetime import datetime

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
        play_history.last_played_at = datetime.utcnow()
        if request and request.duration_seconds:
            play_history.total_play_seconds += request.duration_seconds
    else:
        # Create new record
        play_history = ProfilePlayHistory(
            profile_id=profile.id,
            track_id=track_id,
            play_count=1,
            last_played_at=datetime.utcnow(),
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


@router.post("/{track_id}/enrich", response_model=EnrichResponse)
async def enrich_track_metadata(
    track_id: UUID,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> EnrichResponse:
    """Trigger background metadata enrichment for a track.

    Fire-and-forget endpoint that returns immediately.
    Enrichment runs in background if track has missing metadata.
    Fetches data from MusicBrainz/AcoustID, updates ID3 tags, and saves artwork.
    """
    from app.services.app_settings import get_app_settings_service
    from app.services.metadata_enrichment import needs_enrichment
    from app.services.tasks import run_track_enrichment

    # Check if auto-enrichment is enabled
    settings_service = get_app_settings_service()
    app_settings = settings_service.get()
    if not app_settings.auto_enrich_metadata:
        return EnrichResponse(status="disabled", message="Auto-enrichment is disabled")

    # Verify track exists
    track = await db.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    # Check if enrichment is needed
    if not needs_enrichment(track):
        return EnrichResponse(status="skipped", message="Track metadata is complete")

    # Queue background task (fire-and-forget)
    background_tasks.add_task(run_track_enrichment, str(track_id))

    return EnrichResponse(status="queued", message="Enrichment started in background")


@router.post("/enrich-batch", response_model=BatchEnrichResponse)
async def enrich_tracks_batch(
    body: BatchEnrichRequest,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> BatchEnrichResponse:
    """Trigger background metadata enrichment for multiple tracks.

    Fire-and-forget endpoint that returns immediately.
    Checks which tracks need enrichment and queues them in background.
    """
    from app.services.app_settings import get_app_settings_service
    from app.services.metadata_enrichment import needs_enrichment
    from app.services.tasks import run_track_enrichment

    total = len(body.track_ids)

    # Check if auto-enrichment is enabled
    settings_service = get_app_settings_service()
    app_settings = settings_service.get()
    if not app_settings.auto_enrich_metadata:
        return BatchEnrichResponse(queued=0, skipped=total, total=total)

    # Fetch all tracks in one query
    track_uuids = []
    for tid in body.track_ids:
        try:
            track_uuids.append(UUID(tid))
        except ValueError:
            continue

    result = await db.execute(
        select(Track).where(Track.id.in_(track_uuids))
    )
    tracks_by_id = {str(t.id): t for t in result.scalars().all()}

    queued = 0
    for tid in body.track_ids:
        track = tracks_by_id.get(tid)
        if track and needs_enrichment(track):
            background_tasks.add_task(run_track_enrichment, tid)
            queued += 1

    return BatchEnrichResponse(queued=queued, skipped=total - queued, total=total)


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
