"""Audio fingerprint identification endpoints."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import DbSession

logger = logging.getLogger(__name__)

router = APIRouter()


class IdentifyCandidateResponse(BaseModel):
    """A candidate match from audio fingerprint identification."""

    acoustid_score: float  # 0.0-1.0 confidence score
    musicbrainz_recording_id: str
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    year: int | None = None
    track_number: int | None = None
    disc_number: int | None = None
    genre: str | None = None
    composer: str | None = None
    artwork_url: str | None = None
    features: dict[str, Any] = {}
    musicbrainz_url: str = ""


class IdentifyTrackResponse(BaseModel):
    """Response from track identification via audio fingerprint."""

    track_id: str
    fingerprint_generated: bool
    error: str | None = None
    error_type: str | None = None
    candidates: list[IdentifyCandidateResponse] = []


class BulkIdentifyRequest(BaseModel):
    """Request to identify multiple tracks via audio fingerprinting."""

    track_ids: list[UUID]


class BulkIdentifyTaskResponse(BaseModel):
    """Response when starting a bulk identification task."""

    task_id: str
    status: str
    message: str


class BulkIdentifyProgress(BaseModel):
    """Progress of a bulk identification task."""

    task_id: str
    status: str  # 'running', 'completed', 'error'
    phase: str
    total_tracks: int
    processed_tracks: int
    current_track: str | None = None
    results: list[IdentifyTrackResponse] = []
    errors: list[str] = []
    started_at: str | None = None


# NOTE: Bulk routes MUST be defined before /{track_id}/identify to prevent
# FastAPI from matching "bulk" as a track_id.


@router.post("/bulk/identify", response_model=BulkIdentifyTaskResponse)
async def start_bulk_identify(
    db: DbSession,
    request: BulkIdentifyRequest,
    background_tasks: BackgroundTasks,
) -> BulkIdentifyTaskResponse:
    """Start bulk audio fingerprint identification for multiple tracks.

    Returns a task_id immediately. Poll GET /tracks/bulk/identify/{task_id}
    for progress and results.

    Rate limited to respect AcoustID (3/sec) and MusicBrainz (1/sec) limits.
    """
    import uuid

    from app.services.background import get_background_manager

    # Generate task ID
    task_id = str(uuid.uuid4())

    # Verify all tracks exist
    track_ids = [str(tid) for tid in request.track_ids]

    # Start background task
    background_manager = get_background_manager()
    background_tasks.add_task(
        background_manager.run_bulk_identify,
        task_id,
        track_ids,
    )

    return BulkIdentifyTaskResponse(
        task_id=task_id,
        status="started",
        message=f"Started identification for {len(track_ids)} tracks",
    )


@router.get("/bulk/identify/{task_id}", response_model=BulkIdentifyProgress)
async def get_bulk_identify_progress(
    task_id: str,
) -> BulkIdentifyProgress:
    """Get progress and results of a bulk identification task."""
    import json

    from app.services.background import get_background_manager

    background_manager = get_background_manager()

    try:
        data: bytes | None = background_manager.redis.get(f"familiar:identify:{task_id}")  # type: ignore[assignment]
        if not data:
            raise HTTPException(
                status_code=404,
                detail=f"Task {task_id} not found or expired",
            )

        progress = json.loads(data)
        return BulkIdentifyProgress(
            task_id=task_id,
            status=progress.get("status", "unknown"),
            phase=progress.get("phase", "unknown"),
            total_tracks=progress.get("total_tracks", 0),
            processed_tracks=progress.get("processed_tracks", 0),
            current_track=progress.get("current_track"),
            results=[
                IdentifyTrackResponse(**r) for r in progress.get("results", [])
            ],
            errors=progress.get("errors", []),
            started_at=progress.get("started_at"),
        )
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Failed to parse task progress",
        )


@router.post("/{track_id}/identify", response_model=IdentifyTrackResponse)
async def identify_track(
    db: DbSession,
    track_id: UUID,
    min_score: float = Query(0.5, ge=0.0, le=1.0, description="Minimum confidence score"),
    limit: int = Query(5, ge=1, le=10, description="Maximum candidates to return"),
) -> IdentifyTrackResponse:
    """Identify a track using audio fingerprinting (AcoustID).

    Generates an audio fingerprint and looks up matching recordings in the
    AcoustID/MusicBrainz database. Returns candidate matches with full metadata
    including title, artist, album, year, genre, artwork URL, etc.

    Use this for the "Auto-populate" feature to fill in track metadata based
    on the audio content rather than text matching.

    Requires:
    - chromaprint/fpcalc installed on the system
    - AcoustID API key configured in Settings > API Keys
    """
    from app.services.audio_identification import get_audio_identification_service

    service = get_audio_identification_service()
    result = await service.identify_track(
        track_id=track_id,
        db=db,
        min_score=min_score,
        limit=limit,
    )

    return IdentifyTrackResponse(
        track_id=result.track_id,
        fingerprint_generated=result.fingerprint_generated,
        error=result.error,
        error_type=result.error_type,
        candidates=[
            IdentifyCandidateResponse(
                acoustid_score=c.acoustid_score,
                musicbrainz_recording_id=c.musicbrainz_recording_id,
                title=c.title,
                artist=c.artist,
                album=c.album,
                album_artist=c.album_artist,
                year=c.year,
                track_number=c.track_number,
                disc_number=c.disc_number,
                genre=c.genre,
                composer=c.composer,
                artwork_url=c.artwork_url,
                features=c.features,
                musicbrainz_url=c.musicbrainz_url,
            )
            for c in result.candidates
        ],
    )
