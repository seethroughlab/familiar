"""Background jobs status endpoint."""

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.artwork_fetcher import get_artwork_fetch_progress
from app.services.s3_backup import get_s3_backup_service
from app.services.tasks import (
    get_spotify_sync_progress,
    get_sync_progress,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/background", tags=["background"])


class JobProgress(BaseModel):
    """Progress for a background job."""

    current: int = 0
    total: int = 0


class BackgroundJob(BaseModel):
    """Status of a background job."""

    type: str  # "library_sync", "spotify_sync", "artwork_fetch", "s3_backup"
    status: str  # "running", "idle", "error", "complete"
    phase: str
    progress: JobProgress | None = None
    message: str
    current_item: str | None = None
    started_at: str | None = None


class BackgroundJobsResponse(BaseModel):
    """Response with all background jobs."""

    jobs: list[BackgroundJob]
    active_count: int


def _build_library_sync_job(progress: dict[str, Any]) -> BackgroundJob:
    """Build a BackgroundJob from library sync progress."""
    phase = progress.get("phase", "idle")
    status = progress.get("status", "idle")

    # Determine progress based on phase
    job_progress = None
    if phase == "reading":
        job_progress = JobProgress(
            current=progress.get("files_processed", 0),
            total=progress.get("files_total", 0),
        )
    elif phase in ("features", "embeddings", "backfill", "melodic"):
        job_progress = JobProgress(
            current=progress.get("tracks_analyzed", 0),
            total=progress.get("tracks_total", 0),
        )

    # Build message
    message = progress.get("phase_message", "")
    if not message:
        phase_messages = {
            "discovering": "Discovering files...",
            "reading": "Reading metadata...",
            "features": "Extracting audio features...",
            "embeddings": "Generating embeddings...",
            "complete": "Sync complete",
            "error": "Sync failed",
        }
        message = phase_messages.get(phase, "Syncing library...")

    return BackgroundJob(
        type="library_sync",
        status=status,
        phase=phase,
        progress=job_progress,
        message=message,
        current_item=progress.get("current_item"),
        started_at=progress.get("started_at"),
    )


def _build_spotify_sync_job(progress: dict[str, Any]) -> BackgroundJob:
    """Build a BackgroundJob from Spotify sync progress."""
    phase = progress.get("phase", "idle")
    status = "running" if phase not in ("idle", "complete", "error") else phase

    job_progress = None
    if phase in ("fetching", "matching"):
        job_progress = JobProgress(
            current=progress.get("tracks_processed", 0),
            total=progress.get("tracks_total", 0),
        )

    phase_messages = {
        "connecting": "Connecting to Spotify...",
        "fetching": "Fetching saved tracks...",
        "matching": "Matching to library...",
        "complete": "Spotify sync complete",
        "error": "Spotify sync failed",
    }
    message = phase_messages.get(phase, "Syncing Spotify...")

    return BackgroundJob(
        type="spotify_sync",
        status=status,
        phase=phase,
        progress=job_progress,
        message=message,
        current_item=progress.get("current_track"),
        started_at=progress.get("started_at"),
    )


def _build_artwork_fetch_job(progress: dict[str, Any]) -> BackgroundJob:
    """Build a BackgroundJob from artwork fetch progress."""
    phase = progress.get("phase", "idle")
    status = progress.get("status", "idle")

    queued = progress.get("queued", 0)
    in_progress = progress.get("in_progress", 0)
    completed = progress.get("completed", 0)
    total = queued + in_progress + completed

    job_progress = None
    if total > 0:
        job_progress = JobProgress(current=completed, total=total)

    if queued > 0 or in_progress > 0:
        message = f"Fetching artwork ({queued} queued)"
    else:
        message = "Artwork fetch idle"

    return BackgroundJob(
        type="artwork_fetch",
        status=status,
        phase=phase,
        progress=job_progress,
        message=message,
        current_item=progress.get("current_item"),
        started_at=progress.get("started_at"),
    )


@router.get("/jobs", response_model=BackgroundJobsResponse)
async def get_background_jobs() -> BackgroundJobsResponse:
    """Get status of all background jobs.

    Returns all jobs that are currently running or have recently completed.
    Only includes jobs with active progress tracking.
    """
    jobs: list[BackgroundJob] = []

    # Check library sync
    library_progress = get_sync_progress()
    if library_progress:
        phase = library_progress.get("phase", "idle")
        if phase not in ("idle", "complete"):
            jobs.append(_build_library_sync_job(library_progress))

    # Check Spotify sync
    spotify_progress = get_spotify_sync_progress()
    if spotify_progress:
        phase = spotify_progress.get("phase", "idle")
        if phase not in ("idle", "complete"):
            jobs.append(_build_spotify_sync_job(spotify_progress))

    # Check artwork fetch
    artwork_progress = get_artwork_fetch_progress()
    if artwork_progress:
        status = artwork_progress.get("status", "idle")
        if status == "running":
            jobs.append(_build_artwork_fetch_job(artwork_progress))

    # Check S3 backup
    s3_progress = get_s3_backup_service().get_backup_progress()
    if s3_progress and s3_progress.get("status") == "running":
        phase = s3_progress.get("phase", "starting")
        job_progress = None
        total = s3_progress.get("files_total", 0)
        uploaded = s3_progress.get("files_uploaded", 0)
        if total > 0:
            job_progress = JobProgress(current=uploaded, total=total)
        phase_messages = {
            "starting": "Starting backup...",
            "database": "Backing up database...",
            "settings": "Backing up settings...",
            "audio": "Uploading audio files...",
            "artwork": "Uploading artwork...",
            "videos": "Uploading videos...",
            "manifest": "Writing manifest...",
        }
        jobs.append(BackgroundJob(
            type="s3_backup",
            status="running",
            phase=phase,
            progress=job_progress,
            message=phase_messages.get(phase, "Running S3 backup..."),
            current_item=s3_progress.get("current_file"),
            started_at=s3_progress.get("started_at"),
        ))

    return BackgroundJobsResponse(
        jobs=jobs,
        active_count=len(jobs),
    )
