"""Library sync endpoints."""

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.ratelimit import SCAN_RATE_LIMIT, limiter
from app.services.tasks import get_sync_progress

logger = logging.getLogger(__name__)

router = APIRouter(tags=["library"])


class SyncProgress(BaseModel):
    """Unified sync progress covering discovery, reading, and analysis."""

    phase: str = "idle"  # "discovering", "reading", "analyzing", "complete", "error"
    phase_message: str = ""

    # Discovery/scan metrics
    files_discovered: int = 0
    files_processed: int = 0
    files_total: int = 0
    new_tracks: int = 0
    updated_tracks: int = 0
    unchanged_tracks: int = 0
    relocated_tracks: int = 0
    marked_missing: int = 0
    recovered: int = 0

    # Analysis metrics
    tracks_analyzed: int = 0
    tracks_pending_analysis: int = 0
    tracks_total: int = 0
    analysis_percent: float = 0.0

    # Overall
    started_at: str | None = None
    current_item: str | None = None
    last_heartbeat: str | None = None
    errors: list[str] = []


class SyncStatus(BaseModel):
    """Unified sync status response."""

    status: str  # "idle", "running", "completed", "error"
    message: str
    progress: SyncProgress | None = None


class CancelResponse(BaseModel):
    """Response for cancel operations."""

    status: str
    message: str
    requested: bool = True
    in_process_tasks_cancelled: int = 0
    subprocess_may_continue: bool = False


@router.post("/sync", response_model=SyncStatus)
@limiter.limit(SCAN_RATE_LIMIT)
async def start_sync(
    request: Request,
    reread_unchanged: bool = False,
) -> SyncStatus:
    """Start a unified library sync (scan + analysis).

    This is the recommended way to sync your library. It:
    1. Discovers audio files in your library paths
    2. Reads metadata from new/changed files
    3. Analyzes audio features for new tracks

    The sync runs in the background, so this returns immediately.
    Progress is stored in Redis and can be retrieved via GET /sync/status.

    Args:
        reread_unchanged: Re-read metadata for files even if unchanged. Default False.
    """
    from app.services.background import get_background_manager

    bg = get_background_manager()

    # Check if a sync is already running
    if bg.is_sync_running():
        progress = get_sync_progress()
        if progress:
            return SyncStatus(
                status="already_running",
                message="A sync is already in progress",
                progress=SyncProgress(**{
                    k: progress.get(k, v)
                    for k, v in SyncProgress().model_dump().items()
                }),
            )
        return SyncStatus(
            status="already_running",
            message="A sync is already in progress",
        )

    # Start sync in background
    await bg.run_sync(reread_unchanged=reread_unchanged)

    return SyncStatus(
        status="started",
        message="Library sync started",
    )


@router.get("/sync/status", response_model=SyncStatus)
async def get_sync_status_endpoint() -> SyncStatus:
    """Get current sync status with unified progress.

    Returns progress through all phases:
    - discovering: Finding audio files
    - reading: Reading metadata from files
    - analyzing: Extracting audio features
    - complete: Sync finished
    """
    from datetime import datetime, timedelta

    from app.services.background import SYNC_HEARTBEAT_STALE_SECONDS
    from app.services.tasks import clear_sync_progress

    progress = get_sync_progress()

    if not progress:
        return SyncStatus(
            status="idle",
            message="No sync running",
            progress=None,
        )

    # Check if the sync is stale (no heartbeat for 5 minutes)
    status = progress.get("status", "idle")
    if status == "running":
        last_heartbeat = progress.get("last_heartbeat")
        if last_heartbeat:
            try:
                heartbeat_time = datetime.fromisoformat(last_heartbeat)
                if datetime.now() - heartbeat_time > timedelta(seconds=SYNC_HEARTBEAT_STALE_SECONDS):
                    clear_sync_progress()
                    return SyncStatus(
                        status="error",
                        message="Sync was interrupted (worker stopped responding)",
                        progress=None,
                    )
            except (ValueError, TypeError):
                pass

    # Convert Redis progress to SyncProgress model
    sync_progress = SyncProgress(
        phase=progress.get("phase", "idle"),
        phase_message=progress.get("phase_message", ""),
        files_discovered=progress.get("files_discovered", 0),
        files_processed=progress.get("files_processed", 0),
        files_total=progress.get("files_total", 0),
        new_tracks=progress.get("new_tracks", 0),
        updated_tracks=progress.get("updated_tracks", 0),
        unchanged_tracks=progress.get("unchanged_tracks", 0),
        relocated_tracks=progress.get("relocated_tracks", 0),
        marked_missing=progress.get("marked_missing", 0),
        recovered=progress.get("recovered", 0),
        tracks_analyzed=progress.get("tracks_analyzed", 0),
        tracks_pending_analysis=progress.get("tracks_pending_analysis", 0),
        tracks_total=progress.get("tracks_total", 0),
        analysis_percent=progress.get("analysis_percent", 0.0),
        started_at=progress.get("started_at"),
        current_item=progress.get("current_item"),
        last_heartbeat=progress.get("last_heartbeat"),
        errors=progress.get("errors", []),
    )

    return SyncStatus(
        status=status,
        message=progress.get("phase_message", ""),
        progress=sync_progress if status != "idle" else None,
    )


@router.post("/sync/cancel", response_model=CancelResponse)
async def cancel_sync() -> CancelResponse:
    """Cancel a running library sync.

    Clears the sync progress from Redis and releases the lock.
    """
    from app.services.background import get_background_manager
    from app.services.tasks import clear_sync_progress

    bg = get_background_manager()

    cancel_result = bg.cancel_sync()
    clear_sync_progress()

    return CancelResponse(
        status="cancelled",
        message="Sync cancelled and state cleared",
        requested=cancel_result["requested"],
        in_process_tasks_cancelled=cancel_result["in_process_tasks_cancelled"],
        subprocess_may_continue=cancel_result["subprocess_may_continue"],
    )
