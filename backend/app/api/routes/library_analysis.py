"""Audio analysis endpoints."""

import logging

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.api.exceptions import ConflictError
from app.api.schemas.common import CancelResponse
from app.db.models import Track, TrackAnalysis
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])


class AnalysisStatus(BaseModel):
    """Analysis status response."""

    status: str  # "idle", "running", "stuck", "error"
    total: int = 0
    analyzed: int = 0
    pending: int = 0
    failed: int = 0
    percent: float = 0.0
    current_file: str | None = None
    error: str | None = None
    heartbeat: str | None = None
    # Embedding coverage - helps detect silent failures
    with_embeddings: int = 0
    without_embeddings: int = 0
    embeddings_enabled: bool = True
    embeddings_disabled_reason: str | None = None


class AnalysisStartResponse(BaseModel):
    """Response for starting analysis."""

    status: str
    queued: int = 0
    message: str


class ExecutorStatus(BaseModel):
    """Process pool executor status."""

    disabled: bool
    consecutive_failures: int
    max_failures: int
    crashed_track_ids: list[str]
    last_reset_ago: float | None


class ExecutorResetResponse(BaseModel):
    """Response from resetting the executor."""

    status: str
    was_disabled: bool
    previous_failure_count: int
    crashed_track_ids: list[str]


@router.post("/analysis/cancel", response_model=CancelResponse)
async def cancel_analysis() -> CancelResponse:
    """Cancel running analysis tasks.

    Clears analysis task tracking. Note that in-progress subprocess tasks
    may continue to completion, but no new tasks will be started.
    """
    from app.services.background import get_background_manager

    bg = get_background_manager()

    cancel_result = bg.cancel_analysis()

    return CancelResponse(
        status="cancelled",
        message=f"Cancelled {cancel_result['in_process_tasks_cancelled']} analysis tasks",
        requested=cancel_result["requested"],
        in_process_tasks_cancelled=cancel_result["in_process_tasks_cancelled"],
        subprocess_may_continue=cancel_result["subprocess_may_continue"],
    )


@router.get("/analysis/status", response_model=AnalysisStatus)
async def get_analysis_status(db: DbSession) -> AnalysisStatus:
    """Get current audio analysis status with stuck detection.

    Returns analysis progress and detects if the worker has stalled.
    Also reports embedding coverage to help detect silent failures.
    """
    from datetime import timedelta

    from sqlalchemy import or_

    from app.config import FEATURES_VERSION
    from app.services.analysis import get_analysis_capabilities

    # Get analysis capabilities
    caps = get_analysis_capabilities()

    # Get counts from database
    total = await db.scalar(select(func.count(Track.id))) or 0
    analyzed = await db.scalar(
        select(func.count(TrackAnalysis.id)).where(
            TrackAnalysis.features_version >= FEATURES_VERSION
        )
    ) or 0
    failed = await db.scalar(
        select(func.count(Track.id)).where(Track.analysis_failed_at.isnot(None))
    ) or 0

    # Count tracks with/without embeddings
    with_embeddings = await db.scalar(
        select(func.count(TrackAnalysis.id)).where(TrackAnalysis.embedding.isnot(None))
    ) or 0
    without_embeddings = analyzed - with_embeddings

    # Pending = no TrackAnalysis row or outdated version, and not recently failed
    failure_cutoff = utcnow() - timedelta(hours=24)
    pending = await db.scalar(
        select(func.count(Track.id))
        .outerjoin(TrackAnalysis, Track.id == TrackAnalysis.track_id)
        .where(
            or_(
                TrackAnalysis.id.is_(None),
                TrackAnalysis.features_version < FEATURES_VERSION,
            ),
            or_(
                Track.analysis_failed_at.is_(None),
                Track.analysis_failed_at < failure_cutoff,
            ),
        )
    ) or 0

    percent = (analyzed / total * 100) if total > 0 else 100.0

    # Common fields for all responses
    common = {
        "total": total,
        "analyzed": analyzed,
        "pending": pending,
        "failed": failed,
        "percent": round(percent, 1),
        "with_embeddings": with_embeddings,
        "without_embeddings": without_embeddings,
        "embeddings_enabled": caps["embeddings_enabled"],
        "embeddings_disabled_reason": caps["embeddings_disabled_reason"],
    }

    # Check if background analysis tasks are running
    from app.services.background import get_background_manager

    bg = get_background_manager()
    active_tasks = bg.get_analysis_task_count()

    if active_tasks > 0:
        return AnalysisStatus(
            status="running",
            current_file=f"Processing {active_tasks} tracks...",
            **common,
        )

    # No active analysis tasks - check if there's pending work
    if pending > 0:
        return AnalysisStatus(status="idle", **common)

    # Override percent to 100 for complete status
    common["percent"] = 100.0
    return AnalysisStatus(status="complete", **common)


@router.get("/analysis/executor", response_model=ExecutorStatus)
async def get_executor_status() -> ExecutorStatus:
    """Get process pool executor status.

    Returns whether the executor is disabled (circuit breaker tripped),
    the number of consecutive failures, and which tracks caused crashes.
    """
    from app.services.background import get_background_manager

    bg = get_background_manager()
    status = bg.get_executor_status()

    return ExecutorStatus(**status)


@router.post("/analysis/executor/reset", response_model=ExecutorResetResponse)
async def reset_executor() -> ExecutorResetResponse:
    """Reset the process pool executor circuit breaker.

    Use this to recover from a disabled executor without restarting the container.
    The circuit breaker trips after 5 consecutive worker crashes.

    Returns info about what was reset, including which tracks caused crashes.
    """
    from app.services.background import get_background_manager

    bg = get_background_manager()
    result = bg.reset_executor_circuit_breaker()

    return ExecutorResetResponse(**result)


@router.post("/analysis/start", response_model=AnalysisStartResponse)
async def start_analysis(limit: int = 500) -> AnalysisStartResponse:
    """Manually trigger analysis for unanalyzed tracks.

    This queues tracks for analysis in the background. Use GET /analysis/status
    to monitor progress.

    Scans and analysis cannot run simultaneously - they share resources.
    """
    from app.services.background import get_background_manager
    from app.services.tasks import queue_unanalyzed_tracks

    bg = get_background_manager()

    # Check if sync is running - can't run both simultaneously
    if bg.is_sync_running():
        raise ConflictError("Cannot start analysis while a sync is running. Cancel sync first or wait for it to complete.")

    try:
        queued = await queue_unanalyzed_tracks(limit=limit)
        if queued == 0:
            return AnalysisStartResponse(
                status="complete",
                queued=0,
                message="All tracks are already analyzed",
            )
        return AnalysisStartResponse(
            status="started",
            queued=queued,
            message=f"Queued {queued} tracks for analysis",
        )
    except Exception as e:
        return AnalysisStartResponse(
            status="error",
            queued=0,
            message=f"Failed to start analysis: {e}",
        )
