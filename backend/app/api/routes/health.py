"""Health check endpoints."""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.api.deps import DbSession
from app.config import FEATURES_VERSION, get_app_version
from app.db.models import Track, TrackAnalysis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class ServiceStatus(BaseModel):
    """Status of an individual service."""

    name: str
    status: str  # "healthy", "unhealthy", "degraded"
    message: str | None = None
    details: dict[str, Any] | None = None


class SystemHealth(BaseModel):
    """Overall system health status."""

    status: str  # "healthy", "degraded", "unhealthy"
    services: list[ServiceStatus]
    warnings: list[str] = []
    deployment_mode: str = "local"  # "docker" or "local"
    version: str = "dev"


def is_running_in_docker() -> bool:
    """Detect if we're running inside a Docker container."""
    # Check for .dockerenv file (most reliable)
    if Path("/.dockerenv").exists():
        return True
    # Check cgroup (works on most Linux systems)
    try:
        with open("/proc/1/cgroup") as f:
            return "docker" in f.read()
    except (FileNotFoundError, PermissionError):
        pass
    return False


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Basic liveness check."""
    return {"status": "healthy"}


@router.get("/health/db")
async def db_health_check(db: DbSession) -> dict[str, Any]:
    """Database connectivity check."""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {"status": "unhealthy", "database": "disconnected", "error": "Connection failed"}


@router.get("/health/system", response_model=SystemHealth)
async def system_health_check(db: DbSession) -> SystemHealth:
    """Comprehensive system health check.

    Checks all required services:
    - Database (PostgreSQL)
    - Redis
    - Background task status
    - Analysis backlog status
    - Library paths accessibility
    """
    from app.config import settings

    services: list[ServiceStatus] = []
    warnings: list[str] = []

    # Check Library Paths (before other checks so we can surface volume issues prominently)
    library_paths = settings.music_library_paths
    unmounted_volumes: list[str] = []
    empty_paths: list[str] = []
    valid_path_count = 0

    if not library_paths:
        warnings.insert(0, "No music library configured. Go to /admin to set up your music library path.")
    else:
        for library_path in library_paths:
            if not library_path.exists():
                # Check if it's a volume mount issue
                parts = library_path.parts
                if len(parts) > 2 and parts[1] == "Volumes":
                    volume_name = parts[2]
                    if not Path(f"/Volumes/{volume_name}").exists():
                        unmounted_volumes.append(volume_name)
                else:
                    warnings.append(f"Library path does not exist: {library_path}")
            elif library_path.is_dir():
                # Check if directory has any content
                try:
                    has_content = any(library_path.iterdir())
                    if not has_content:
                        empty_paths.append(str(library_path))
                    else:
                        valid_path_count += 1
                except PermissionError:
                    warnings.append(f"Cannot read library path (permission denied): {library_path}")

    if unmounted_volumes:
        volume_list = ", ".join(unmounted_volumes)
        warnings.insert(0, f"Music library volume(s) not mounted: {volume_list}. Connect the drive to continue.")

    if empty_paths:
        path_list = ", ".join(empty_paths)
        warnings.insert(0, f"Library path(s) empty (possible volume mount issue): {path_list}")

    # Add library status to services
    if library_paths:
        lib_status = "healthy" if valid_path_count > 0 else "unhealthy"
        lib_message = f"{valid_path_count}/{len(library_paths)} paths accessible"
        if valid_path_count == 0:
            lib_message = "No accessible library paths - check docker-compose volume mounts"
        services.append(ServiceStatus(
            name="library",
            status=lib_status,
            message=lib_message,
            details={
                "configured_paths": [str(p) for p in library_paths],
                "valid_paths": valid_path_count,
                "empty_paths": empty_paths,
            },
        ))

    # Check Database
    try:
        await db.execute(text("SELECT 1"))
        services.append(ServiceStatus(
            name="database",
            status="healthy",
            message="PostgreSQL connected",
        ))
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        services.append(ServiceStatus(
            name="database",
            status="unhealthy",
            message="PostgreSQL connection failed",
        ))

    # Check Redis
    try:
        import redis

        from app.config import settings
        r = redis.from_url(settings.redis_url)
        r.ping()
        services.append(ServiceStatus(
            name="redis",
            status="healthy",
            message="Redis connected",
        ))
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        services.append(ServiceStatus(
            name="redis",
            status="unhealthy",
            message="Redis connection failed",
        ))

    # Check Background Processing (in-process BackgroundManager)
    try:
        from app.services.background import get_background_manager

        bg = get_background_manager()
        is_sync_running = bg.is_sync_running()
        active_analyses = len(bg._analysis_tasks)

        # Build status message
        if is_sync_running:
            message = "Library sync in progress"
        elif active_analyses > 0:
            message = f"{active_analyses} analysis task(s) running"
        else:
            message = "Idle"

        services.append(ServiceStatus(
            name="background_processing",
            status="healthy",
            message=message,
            details={"sync_running": is_sync_running, "active_analyses": active_analyses},
        ))
    except Exception as e:
        logger.warning(f"Cannot check background processing status: {e}")
        services.append(ServiceStatus(
            name="background_processing",
            status="unhealthy",
            message="Cannot check status",
        ))

    # Check Analysis Backlog
    # Note: Analysis progress is informational, not a health concern.
    # We only warn if workers are DOWN and tracks are pending.
    try:
        total_tracks = await db.scalar(select(func.count(Track.id))) or 0
        analyzed_tracks = await db.scalar(
            select(func.count(TrackAnalysis.id)).where(TrackAnalysis.features_version >= FEATURES_VERSION)
        ) or 0
        pending = total_tracks - analyzed_tracks

        # Check if background processing is healthy
        bg_healthy = any(
            s.name == "background_processing" and s.status == "healthy"
            for s in services
        )

        # Analysis status is always "healthy" - pending work is normal, not a problem
        services.append(ServiceStatus(
            name="analysis",
            status="healthy",
            message="All tracks analyzed" if pending == 0 else f"{pending:,} tracks pending",
            details={"total": total_tracks, "analyzed": analyzed_tracks, "pending": pending},
        ))

        # Only warn if workers are DOWN and there's pending work
        if pending > 0 and not bg_healthy:
            warnings.append(
                f"{pending:,} tracks waiting for analysis. "
                "Background processing is not running."
            )
    except Exception as e:
        logger.error(f"Cannot check analysis status: {e}")
        services.append(ServiceStatus(
            name="analysis",
            status="unhealthy",
            message="Cannot check analysis status",
        ))

    # Determine overall status
    unhealthy_count = sum(1 for s in services if s.status == "unhealthy")
    degraded_count = sum(1 for s in services if s.status == "degraded")

    if unhealthy_count > 0:
        # Database or Redis down is critical
        critical_services = {"database", "redis"}
        critical_down = any(s.status == "unhealthy" and s.name in critical_services for s in services)
        overall_status = "unhealthy" if critical_down else "degraded"
    elif degraded_count > 0:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    return SystemHealth(
        status=overall_status,
        services=services,
        warnings=warnings,
        deployment_mode="docker" if is_running_in_docker() else "local",
        version=get_app_version(),
    )


class WorkerTask(BaseModel):
    """A task currently being processed by a worker."""

    id: str
    name: str
    args: list[Any] = []
    started_at: str | None = None


class WorkerInfo(BaseModel):
    """Information about a background worker."""

    name: str
    status: str  # "online", "offline"
    active_tasks: list[WorkerTask] = []
    processed_total: int = 0
    concurrency: int | None = None


class QueueStats(BaseModel):
    """Statistics about task queues."""

    name: str
    pending: int


class TaskFailure(BaseModel):
    """A recent task failure."""

    task: str
    error: str
    track: str | None = None
    timestamp: str


class BackgroundEvent(BaseModel):
    """Recent background lifecycle/resilience event."""

    event: str
    timestamp: str
    details: dict[str, Any] = {}


class WorkerStatus(BaseModel):
    """Detailed worker and queue status."""

    workers: list[WorkerInfo]
    queues: list[QueueStats]
    analysis_progress: dict[str, Any]
    recent_failures: list[TaskFailure] = []
    background_events: list[BackgroundEvent] = []


@router.get("/health/workers", response_model=WorkerStatus)
async def get_worker_status(db: DbSession) -> WorkerStatus:
    """Get detailed status of background processing and task queues."""
    from datetime import datetime

    from app.config import FEATURES_VERSION
    from app.services.background import get_background_manager
    from app.services.background.events import get_recent_background_events
    from app.services.tasks import get_recent_failures

    workers: list[WorkerInfo] = []
    queues: list[QueueStats] = []
    recent_failures: list[TaskFailure] = []
    background_events: list[BackgroundEvent] = []

    # Get recent failures
    try:
        failures = get_recent_failures(limit=10)
        recent_failures = [TaskFailure(**f) for f in failures]
    except Exception as e:
        logger.warning(f"Could not get recent failures: {e}")

    # Background lifecycle timeline
    try:
        events = get_recent_background_events(limit=20)
        background_events = [BackgroundEvent(**evt) for evt in events]
    except Exception as e:
        logger.warning(f"Could not get background events: {e}")

    # Get worker info from BackgroundManager
    try:
        bg = get_background_manager()
        active_task_list = []

        # Report sync as a task if running
        if bg.is_sync_running():
            active_task_list.append(WorkerTask(
                id="sync",
                name="library_sync",
                args=[],
                started_at=datetime.now().isoformat(),
            ))

        # Report analysis tasks
        for track_id, task in bg._analysis_tasks.items():
            if not task.done():
                active_task_list.append(WorkerTask(
                    id=track_id[:8],
                    name="analyze_track",
                    args=[track_id[:8]],
                    started_at=None,
                ))

        workers.append(WorkerInfo(
            name="in-process",
            status="online",
            active_tasks=active_task_list[:10],  # Limit to 10
            processed_total=0,  # Not tracked in new system
            concurrency=1,  # ProcessPoolExecutor max_workers
        ))

    except Exception as e:
        logger.warning(f"Could not get background processing info: {e}")

    # Get pending analysis count
    try:
        queues.append(QueueStats(name="analysis", pending=len(bg._analysis_tasks) if bg else 0))
    except Exception as e:
        logger.warning(f"Could not get queue stats: {e}")

    # Get analysis progress
    total_tracks = await db.scalar(select(func.count(Track.id))) or 0
    analyzed_tracks = await db.scalar(
        select(func.count(TrackAnalysis.id)).where(TrackAnalysis.features_version >= FEATURES_VERSION)
    ) or 0

    analysis_progress = {
        "total": total_tracks,
        "analyzed": analyzed_tracks,
        "pending": total_tracks - analyzed_tracks,
        "percent": round((analyzed_tracks / total_tracks * 100), 1) if total_tracks > 0 else 0,
    }

    return WorkerStatus(
        workers=workers,
        queues=queues,
        analysis_progress=analysis_progress,
        recent_failures=recent_failures,
        background_events=background_events,
    )
