"""Health check endpoints."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.api.deps import DbSession
from app.config import FEATURES_VERSION, get_app_version
from app.db.models import Track, TrackAnalysis
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


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


class HealthCheckResponse(BaseModel):
    status: str


class DbHealthResponse(BaseModel):
    status: str
    database: str
    error: str | None = None


@router.get("/health", response_model=HealthCheckResponse)
async def health_check() -> HealthCheckResponse:
    """Basic liveness check."""
    return HealthCheckResponse(status="healthy")


@router.get("/health/db", response_model=DbHealthResponse)
async def db_health_check(db: DbSession) -> DbHealthResponse:
    """Database connectivity check."""
    try:
        await db.execute(text("SELECT 1"))
        return DbHealthResponse(status="healthy", database="connected")
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return DbHealthResponse(status="unhealthy", database="disconnected", error="Connection failed")


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
        warnings.insert(0, "No music library configured. Open Settings to set up your music library path.")
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


class PhaseQueue(BaseModel):
    """Per-phase analysis queue status."""

    phase: str
    pending: int
    completed: int
    total: int
    percent: float
    stall_recoveries: int = 0
    requeue_attempts: int = 0
    forced_exit_reason: str | None = None


class WorkerStatus(BaseModel):
    """Detailed worker and queue status."""

    workers: list[WorkerInfo]
    queues: list[QueueStats]
    analysis_progress: dict[str, Any]
    phase_queues: list[PhaseQueue] = []
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

    # Per-phase analysis queues
    from app.config import EMBEDDING_VERSION, MELODIC_VERSION, MOOD_TAGS_VERSION
    from app.services.tasks import get_sync_progress

    phase_queues: list[PhaseQueue] = []
    try:
        features_done = analyzed_tracks  # Already computed above

        embeddings_done = await db.scalar(
            select(func.count(TrackAnalysis.id)).where(
                TrackAnalysis.features_version >= FEATURES_VERSION,
                TrackAnalysis.embedding_version >= EMBEDDING_VERSION,
            )
        ) or 0

        melodic_done = await db.scalar(
            select(func.count(TrackAnalysis.id)).where(
                TrackAnalysis.features_version >= FEATURES_VERSION,
                TrackAnalysis.melodic_version >= MELODIC_VERSION,
            )
        ) or 0

        mood_done = await db.scalar(
            select(func.count(TrackAnalysis.id)).where(
                TrackAnalysis.features_version >= FEATURES_VERSION,
                TrackAnalysis.mood_tags_version >= MOOD_TAGS_VERSION,
            )
        ) or 0

        # Overlay runtime stats from sync progress if running
        sync_progress = get_sync_progress()
        requeue_attempts = {}
        stall_recoveries = {}
        forced_exit_reasons = {}
        if sync_progress and sync_progress.get("status") == "running":
            requeue_attempts = sync_progress.get("phase_requeue_attempts", {})
            stall_recoveries = sync_progress.get("phase_stall_recoveries", {})
            forced_exit_reasons = sync_progress.get("phase_forced_exit_reasons", {})

        phase_data = [
            ("features", features_done, total_tracks),
            ("embeddings", embeddings_done, total_tracks),
            ("melodic", melodic_done, total_tracks),
            ("mood_tags", mood_done, total_tracks),
        ]
        for phase_name, completed, total in phase_data:
            pending = total - completed
            pct = round((completed / total * 100), 1) if total > 0 else 0.0
            phase_queues.append(PhaseQueue(
                phase=phase_name,
                pending=pending,
                completed=completed,
                total=total,
                percent=pct,
                stall_recoveries=stall_recoveries.get(phase_name, 0),
                requeue_attempts=requeue_attempts.get(phase_name, 0),
                forced_exit_reason=forced_exit_reasons.get(phase_name),
            ))
    except Exception as e:
        logger.warning(f"Could not compute phase queues: {e}")

    return WorkerStatus(
        workers=workers,
        queues=queues,
        analysis_progress=analysis_progress,
        phase_queues=phase_queues,
        recent_failures=recent_failures,
        background_events=background_events,
    )


class DiscoverySourceHealthResponse(BaseModel):
    """Whether one discovery source is working — not whether it is configured."""

    source: str
    #: working | degraded | backing_off | failing | never_succeeded |
    #: not_instrumented | disabled
    state: str
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_failure_kind: str | None = None
    last_failure_detail: str | None = None
    consecutive_failures: int = 0
    items_contributed: int = 0
    backoff_until: str | None = None


class DiscoveryHealthResponse(BaseModel):
    """Health of every discovery source, plus the job that drives them."""

    sources: list[DiscoverySourceHealthResponse]
    #: Worst state across the list, so a caller can render one badge.
    status: str


def _source_state(row: Any, now: datetime, enabled: bool = True) -> str:
    """Turn a health row into the word a person reads.

    **`never_succeeded` is its own state and not a kind of "no data"** (ADR-0099
    point 8). It was the true state for nineteen nights while the nightly job crashed,
    and rendering it as "nothing found yet" is what let that pass unnoticed.

    **`not_instrumented` is the state that keeps `never_succeeded` meaningful.** A row
    with no attempt recorded means nothing has ever *tried* this source, which is a
    different fact from having tried and never succeeded. Last.fm and Bandcamp are in
    this position today: both are integrated for recommendations, neither is wired to
    the recorder until ADR-0099 point 5. Reporting them as failures would make the
    aggregate badge permanently alarming and would conflate "unmonitored" with
    "broken" — the exact conflation this surface exists to remove.
    """
    # **Checked first, because a disabled source keeps its last success forever.**
    # Without this it would read `working` indefinitely after being switched off, and
    # "off" would be indistinguishable from "fine" — the confusion this whole surface
    # exists to remove, reintroduced by the switch meant to give the owner control.
    if not enabled:
        return "disabled"

    if row.backoff_until is not None and row.backoff_until > now:
        return "backing_off"
    if row.last_attempt_at is None and row.last_success_at is None:
        return "not_instrumented"
    if row.last_success_at is None:
        return "never_succeeded"
    if row.consecutive_failures >= 3:
        return "failing"
    if row.consecutive_failures > 0:
        return "degraded"
    return "working"


def _row_enabled(source: str, discovery_source_enabled: Any) -> bool:
    """Which switch a health row answers to.

    ADR-0115's two rows are not discovery sources — the backfill enriches music you
    own, which ADR-0099 scoped out of discovery — so they must not read `disabled`
    because `discovery_enabled` is off, nor `working` after their own gate is closed.
    Each answers to the gate its phase checks.
    """
    from app.services.app_settings import get_app_settings_service
    from app.services.tasks.recording_backfill import SOURCE_ACOUSTID, SOURCE_CLAIMS

    if source == SOURCE_ACOUSTID:
        return bool(get_app_settings_service().get().recording_backfill_enabled)
    if source == SOURCE_CLAIMS:
        return bool(get_app_settings_service().get().community_cache_contribute)
    return bool(discovery_source_enabled(source))


@router.get("/health/discovery-sources", response_model=DiscoveryHealthResponse)
async def discovery_source_health(db: DbSession) -> DiscoveryHealthResponse:
    """Report whether each discovery source is working.

    Deliberately **not** folded into `/health/system`'s `services` list: `ServiceStatus`
    carries only name/status/message/details, so the four facts ADR-0099 point 6 asks
    for — last success, last failure and its kind, contribution, backoff — would land
    in an untyped `details` dict, which is what `lint_openapi` exists to stop. It is
    also a different question from "is the process up".
    """
    from app.db.models import DiscoverySourceHealth
    from app.services.discovery import source_enabled

    now = utcnow().replace(tzinfo=None)
    rows = (
        (await db.execute(select(DiscoverySourceHealth).order_by(DiscoverySourceHealth.source)))
        .scalars()
        .all()
    )

    sources = [
        DiscoverySourceHealthResponse(
            source=row.source,
            state=_source_state(row, now, enabled=_row_enabled(row.source, source_enabled)),
            last_success_at=row.last_success_at.isoformat() if row.last_success_at else None,
            last_failure_at=row.last_failure_at.isoformat() if row.last_failure_at else None,
            last_failure_kind=row.last_failure_kind,
            last_failure_detail=row.last_failure_detail,
            consecutive_failures=row.consecutive_failures,
            items_contributed=row.items_contributed,
            backoff_until=row.backoff_until.isoformat() if row.backoff_until else None,
        )
        for row in rows
    ]

    # Worst-wins, matching how `/health/system` aggregates its services.
    # `not_instrumented` sits at the bottom so it never drives the aggregate: a source
    # nothing has attempted is not evidence that discovery is unhealthy.
    severity = {
        # Neither of these drives the aggregate: a source the owner turned off is not
        # evidence that discovery is unhealthy, any more than an unmonitored one is.
        "disabled": -2,
        "not_instrumented": -1,
        "working": 0,
        "degraded": 1,
        "backing_off": 2,
        "never_succeeded": 3,
        "failing": 4,
    }
    worst = max(sources, key=lambda s: severity.get(s.state, 0), default=None)

    return DiscoveryHealthResponse(sources=sources, status=worst.state if worst else "working")


class BudgetHealth(BaseModel):
    """One of the ceilings in `app/api/concurrency.py`, and what it has seen since start."""

    limit: int
    in_flight: int
    #: The high-water mark — what the server was actually asked to do, which a refusal count alone
    #: cannot say.
    peak_in_flight: int


class StreamBudgetHealth(BudgetHealth):
    """The audio budget, with the sync reservation inside it (ADR-0112 point 3)."""

    sync_limit: int
    sync_in_flight: int
    peak_sync_in_flight: int
    refused_sync: int
    refused_interactive: int


class ArtworkBudgetHealth(BudgetHealth):
    """The cover budget, which waits briefly rather than refusing (ADR-0112 point 6)."""

    refused: int


class EncoderBudgetHealth(BudgetHealth):
    """The ffmpeg bound behind `/stream?format=aac` (ADR-0118 point 5)."""

    #: Encodes that had to wait for a slot. Above zero during a first sync is expected; above zero
    #: during ordinary listening means the bound is too low or the cache is cold.
    waited: int


class FileResponseHealth(BaseModel):
    """The three bounds on file work, and their counters, since the process started."""

    stream: StreamBudgetHealth
    artwork: ArtworkBudgetHealth
    encoder: EncoderBudgetHealth


@router.get("/health/file-responses", response_model=FileResponseHealth)
async def file_response_health() -> FileResponseHealth:
    """Report what the file-response and encoder ceilings have seen since start.

    ADR-0112's own follow-up, shared with ADR-0118: both download incidents were reconstructed by
    counting route hits in the NAS's syslog, because the server recorded nothing about the pressure
    it was under. The limiters have kept these counters since 2026-09-07 and reported them nowhere.

    Its own endpoint rather than a line in `/health/system`, for the reason
    `/health/discovery-sources` gives: `ServiceStatus.details` is an untyped dict, and these are
    twelve integers a dashboard should be able to name. No database: the counters live in the
    process, which is also why they reset with it.
    """
    from app.api.concurrency import encoder_limiter, limiter

    return FileResponseHealth(
        stream=StreamBudgetHealth(
            limit=limiter.total_limit,
            in_flight=limiter.in_flight,
            peak_in_flight=limiter.peak_in_flight,
            sync_limit=limiter.sync_limit,
            sync_in_flight=limiter.sync_in_flight,
            peak_sync_in_flight=limiter.peak_sync_in_flight,
            refused_sync=limiter.refused_sync,
            refused_interactive=limiter.refused_interactive,
        ),
        artwork=ArtworkBudgetHealth(
            limit=limiter.artwork_limit,
            in_flight=limiter.artwork_in_flight,
            peak_in_flight=limiter.peak_artwork_in_flight,
            refused=limiter.refused_artwork,
        ),
        encoder=EncoderBudgetHealth(
            limit=encoder_limiter.limit,
            in_flight=encoder_limiter.in_flight,
            peak_in_flight=encoder_limiter.peak_in_flight,
            waited=encoder_limiter.waited,
        ),
    )
