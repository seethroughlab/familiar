"""Diagnostics export endpoint for error reporting."""

import os
import platform
import sys
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.api.deps import CurrentProfile, DbSession
from app.config import FEATURES_VERSION, get_app_version
from app.utils.time import utcnow

router = APIRouter(tags=["diagnostics"])


def get_system_info() -> dict[str, Any]:
    """Gather system information for diagnostics."""
    info: dict[str, Any] = {
        "os": platform.system(),
        "os_version": platform.release(),
        "os_detail": platform.platform(),
        "architecture": platform.machine(),
        "python_version": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
    }

    # Try to get memory info
    try:
        import psutil
        mem = psutil.virtual_memory()
        info["memory_total_gb"] = round(mem.total / (1024**3), 1)
        info["memory_available_gb"] = round(mem.available / (1024**3), 1)
        info["memory_percent_used"] = mem.percent
    except ImportError:
        pass  # psutil not installed

    # Check if running in Docker
    try:
        from app.api.routes.health import is_running_in_docker
        info["docker"] = is_running_in_docker()
    except Exception:
        info["docker"] = "unknown"

    return info


class DiagnosticsExport(BaseModel):
    """Comprehensive diagnostics data for issue reporting."""

    exported_at: str
    version: str
    deployment_mode: str
    system_info: dict[str, Any]
    system_health: dict[str, Any]
    library_stats: dict[str, Any]
    recent_failures: list[dict[str, Any]]
    recent_logs: list[dict[str, Any]]
    frontend_logs: list[dict[str, Any]]
    settings_summary: dict[str, Any]
    metrics_snapshot: dict[str, Any] | None = None


# ── Frontend Log Schemas ────────────────────────────────────────────

class FrontendLogEntry(BaseModel):
    level: str
    namespace: str
    message: str
    timestamp: str
    context: dict[str, Any] | None = None


class FrontendLogBatch(BaseModel):
    entries: list[FrontendLogEntry]


class FrontendLogIngestResponse(BaseModel):
    received: int


class FrontendLogQueryResponse(BaseModel):
    entries: list[dict[str, Any]]
    total: int


@router.get("/diagnostics/export", response_model=DiagnosticsExport)
async def export_diagnostics(db: DbSession) -> DiagnosticsExport:
    """Export comprehensive diagnostics for issue reporting.

    This endpoint gathers system health, recent logs, and configuration
    information to help diagnose issues. Sensitive data (API keys, paths)
    is excluded or redacted.
    """
    from sqlalchemy import func, select

    from app.api.routes.health import is_running_in_docker, system_health_check
    from app.db.models import Track, TrackAnalysis
    from app.logging_config import get_recent_logs
    from app.services.app_settings import get_app_settings_service
    from app.services.tasks import get_recent_failures

    # Get system health
    try:
        health = await system_health_check(db)
        system_health = {
            "status": health.status,
            "services": [s.model_dump() for s in health.services],
            "warnings": health.warnings,
        }
    except Exception as e:
        system_health = {"error": str(e)}

    # Get library stats
    library_stats: dict[str, Any] = {}
    try:
        total_tracks = await db.scalar(select(func.count(Track.id))) or 0
        analyzed_tracks = await db.scalar(
            select(func.count(TrackAnalysis.id)).where(
                TrackAnalysis.features_version >= FEATURES_VERSION
            )
        ) or 0

        library_stats = {
            "total_tracks": total_tracks,
            "analyzed_tracks": analyzed_tracks,
            "pending_analysis": total_tracks - analyzed_tracks,
            "analysis_version": FEATURES_VERSION,
        }
    except Exception as e:
        library_stats = {"error": str(e)}

    # Get recent failures
    try:
        recent_failures = get_recent_failures(limit=20)
    except Exception as e:
        recent_failures = [{"error": str(e)}]

    # Get recent logs (last 100 for export - keeps size manageable)
    try:
        recent_logs = get_recent_logs(limit=100)
    except Exception as e:
        recent_logs = [{"error": str(e)}]

    # Get non-sensitive settings summary
    settings_summary: dict[str, Any]
    try:
        settings_service = get_app_settings_service()
        app_settings = settings_service.get()
        settings_summary = {
            "llm_provider": settings_service.get_active_provider(),
            "has_anthropic_key": settings_service.has_anthropic_key(),
            "has_openai_config": settings_service.has_openai_config(),
            "active_provider_configured": settings_service.is_active_provider_configured(),
            "has_lastfm_key": bool(app_settings.lastfm_api_key),
            "library_paths_count": len(app_settings.music_library_paths),
        }
    except Exception as e:
        settings_summary = {"error": str(e)}

    # Get recent frontend logs
    frontend_logs_list: list[dict[str, Any]] = []
    try:
        from app.db.models import FrontendLog

        fe_result = await db.execute(
            select(FrontendLog)
            .order_by(FrontendLog.client_ts.desc())
            .limit(100)
        )
        for row in fe_result.scalars():
            frontend_logs_list.append({
                "level": row.level,
                "namespace": row.namespace,
                "message": row.message,
                "client_ts": row.client_ts.isoformat() if row.client_ts else None,
                "server_ts": row.server_ts.isoformat() if row.server_ts else None,
                "context": row.context,
            })
    except Exception as e:
        frontend_logs_list = [{"error": str(e)}]

    # Get metrics snapshot
    metrics_snapshot = None
    try:
        from app.services.metrics import get_metrics_collector, update_background_gauges
        collector = get_metrics_collector()
        update_background_gauges(collector)
        metrics_snapshot = collector.get_snapshot(window_seconds=300)
    except Exception as e:
        metrics_snapshot = {"error": str(e)}

    return DiagnosticsExport(
        exported_at=utcnow().isoformat(),
        version=get_app_version(),
        deployment_mode="docker" if is_running_in_docker() else "local",
        system_info=get_system_info(),
        system_health=system_health,
        library_stats=library_stats,
        recent_failures=recent_failures,
        recent_logs=recent_logs,
        frontend_logs=frontend_logs_list,
        settings_summary=settings_summary,
        metrics_snapshot=metrics_snapshot,
    )


class MetricsSnapshotResponse(BaseModel):
    model_config = {"extra": "allow"}

    requests: dict[str, Any] | None = None
    background: dict[str, Any] | None = None
    window_seconds: int | None = None


@router.get("/diagnostics/metrics", response_model=MetricsSnapshotResponse)
async def get_metrics() -> MetricsSnapshotResponse:
    """Get application metrics snapshot (request timing + background gauges)."""
    from app.services.metrics import get_metrics_collector, update_background_gauges

    collector = get_metrics_collector()
    update_background_gauges(collector)
    return MetricsSnapshotResponse(**collector.get_snapshot(window_seconds=300))


# ── Frontend Log Endpoints ──────────────────────────────────────────


@router.post("/diagnostics/frontend-logs", response_model=FrontendLogIngestResponse)
async def ingest_frontend_logs(
    batch: FrontendLogBatch,
    db: DbSession,
    profile: CurrentProfile,
) -> FrontendLogIngestResponse:
    """Ingest a batch of frontend log entries."""
    from sqlalchemy import insert

    from app.db.models import FrontendLog

    if not batch.entries:
        return FrontendLogIngestResponse(received=0)

    # Cap at 200 per request
    entries = batch.entries[:200]

    profile_id = UUID(str(profile.id)) if profile else None

    values = []
    for entry in entries:
        try:
            client_ts = datetime.fromisoformat(entry.timestamp)
            # Strip timezone info -- column is TIMESTAMP WITHOUT TIME ZONE
            if client_ts.tzinfo is not None:
                client_ts = client_ts.replace(tzinfo=None)
        except (ValueError, TypeError):
            client_ts = utcnow()

        values.append({
            "id": uuid4(),
            "profile_id": profile_id,
            "level": entry.level[:10],
            "namespace": entry.namespace[:200],
            "message": entry.message,
            "context": entry.context,
            "client_ts": client_ts,
        })

    await db.execute(insert(FrontendLog), values)
    return FrontendLogIngestResponse(received=len(values))


@router.get("/diagnostics/frontend-logs")
async def query_frontend_logs(
    db: DbSession,
    level: str | None = Query(None),
    namespace: str | None = Query(None),
    search: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    format: str = Query("json"),
) -> Any:
    """Query frontend logs with optional filters.

    Set format=text for plain-text output suitable for curl | grep.
    """
    from sqlalchemy import func, select

    from app.db.models import FrontendLog

    query = select(FrontendLog)

    if level:
        query = query.where(FrontendLog.level == level)
    if namespace:
        query = query.where(FrontendLog.namespace == namespace)
    if search:
        query = query.where(FrontendLog.message.ilike(f"%{search}%"))
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.where(FrontendLog.client_ts >= since_dt)
        except ValueError:
            pass
    if until:
        try:
            until_dt = datetime.fromisoformat(until)
            query = query.where(FrontendLog.client_ts <= until_dt)
        except ValueError:
            pass

    # Get total count (without limit/offset)
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply ordering and pagination
    query = query.order_by(FrontendLog.client_ts.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.scalars().all()

    if format == "text":
        lines = []
        for row in rows:
            ts = row.client_ts.isoformat() if row.client_ts else "?"
            lines.append(f"{ts} {row.level.upper():5s} [{row.namespace}] {row.message}")
        return PlainTextResponse("\n".join(lines))

    entries = []
    for row in rows:
        entries.append({
            "id": str(row.id),
            "level": row.level,
            "namespace": row.namespace,
            "message": row.message,
            "context": row.context,
            "client_ts": row.client_ts.isoformat() if row.client_ts else None,
            "server_ts": row.server_ts.isoformat() if row.server_ts else None,
        })

    return FrontendLogQueryResponse(entries=entries, total=total)


class ClearLogsResponse(BaseModel):
    status: str


@router.delete("/diagnostics/frontend-logs", response_model=ClearLogsResponse)
async def clear_frontend_logs(db: DbSession) -> ClearLogsResponse:
    """Delete all frontend log entries."""
    from sqlalchemy import delete

    from app.db.models import FrontendLog

    await db.execute(delete(FrontendLog))
    return ClearLogsResponse(status="cleared")
