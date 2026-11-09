"""Audio analysis endpoints."""

import logging
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.api.exceptions import ConflictError
from app.api.schemas.common import CancelResponse
from app.db.models import TrackAnalysis

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


    from app.services.analysis import get_analysis_capabilities

    # Get analysis capabilities
    caps = get_analysis_capabilities()

    # ADR-0172: the one status model, shared with /health/workers and /library/stats.
    from app.services.analysis_lifecycle import phase_counts

    counts = await phase_counts(db)
    features = counts["features"]
    total = features.total
    analyzed = features.complete
    pending = features.pending
    failed = features.failed

    # Count tracks with/without embeddings
    with_embeddings = await db.scalar(
        select(func.count(TrackAnalysis.id)).where(TrackAnalysis.embedding.isnot(None))
    ) or 0
    without_embeddings = max(0, analyzed - with_embeddings)

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


class AnalysisFailure(BaseModel):
    """A track one analysis phase failed on (ADR-0172 point 7)."""

    track_id: UUID
    title: str | None = None
    artist: str | None = None
    phase: Literal["features", "embeddings"]
    #: A stable code: undecodable, file_missing, worker_crashed, timeout or error.
    reason: str
    attempts: int
    #: Will not be tried again until the file changes.
    final: bool
    failed_at: datetime
    error: str | None = None


class AnalysisFailures(BaseModel):
    """Tracks in the library whose analysis failed, newest first."""

    total: int
    failures: list[AnalysisFailure]


@router.get("/analysis/failures", response_model=AnalysisFailures)
async def get_analysis_failures(
    db: DbSession, limit: int = Query(100, ge=1, le=500)
) -> AnalysisFailures:
    """The tracks whose analysis failed, with why, so nobody has to read the database to find them.

    Features and embeddings are the phases that record failures; a later phase's failure marks it
    done. Only tracks in the library: a removed track's failure is not something to act on.
    """
    from sqlalchemy import and_, literal, union_all

    from app.db.models import Track
    from app.services.analysis_lifecycle import (
        FailureReason,
        classify,
        embeddings_needed,
        features_current,
        in_library,
        is_terminal,
    )

    features = (
        select(
            Track.id.label("track_id"),
            Track.title,
            Track.artist,
            literal("features").label("phase"),
            Track.analysis_error.label("error"),
            Track.analysis_failed_at.label("failed_at"),
            literal(None).label("reason"),
            literal(1).label("attempts"),
        )
        .select_from(Track)
        .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
        # The failed state `phase_counts` counts: a failure marks the version current. One from
        # before a version bump is being retried, and is counted as retrying instead.
        .where(in_library(), features_current(), Track.analysis_failed_at.is_not(None))
    )
    embeddings = (
        select(
            Track.id.label("track_id"),
            Track.title,
            Track.artist,
            literal("embeddings").label("phase"),
            TrackAnalysis.embedding_error.label("error"),
            TrackAnalysis.embedding_failed_at.label("failed_at"),
            TrackAnalysis.embedding_failure_reason.label("reason"),
            TrackAnalysis.embedding_attempts.label("attempts"),
        )
        .select_from(Track)
        .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
        .where(and_(embeddings_needed(), TrackAnalysis.embedding_failed_at.is_not(None)))
    )
    both = union_all(features, embeddings).subquery()
    total = await db.scalar(select(func.count()).select_from(both)) or 0
    rows = (
        await db.execute(select(both).order_by(both.c.failed_at.desc()).limit(limit))
    ).all()

    failures = []
    for row in rows:
        # A failure recorded before reason codes has none; classify its message, as the migration did.
        reason = FailureReason(row.reason) if row.reason else classify(row.error)
        attempts = row.attempts or 1
        # A feature failure is final on the first attempt: it marks the features version current.
        final = row.phase == "features" or is_terminal(reason, attempts)
        code = reason.value
        failures.append(
            AnalysisFailure(
                track_id=row.track_id,
                title=row.title,
                artist=row.artist,
                phase=row.phase,
                reason=code,
                attempts=attempts,
                final=final,
                failed_at=row.failed_at,
                error=row.error,
            )
        )
    return AnalysisFailures(total=total, failures=failures)


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
