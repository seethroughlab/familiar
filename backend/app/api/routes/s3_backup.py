"""S3 Glacier Deep Archive backup API endpoints."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.app_settings import get_app_settings_service
from app.services.s3_backup import get_s3_backup_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/s3-backup", tags=["s3-backup"])


# ── Request/Response Models ──────────────────────────────────────────


class ValidateRequest(BaseModel):
    bucket: str
    region: str = "us-east-1"
    prefix: str = ""


class ValidateResponse(BaseModel):
    valid: bool
    permissions: dict[str, bool]
    error: str | None = None


class CostCategory(BaseModel):
    file_count: int = 0
    size_bytes: int = 0
    size_gb: float = 0
    monthly_cost: float = 0


class CostEstimateResponse(BaseModel):
    storage_gb: float
    monthly_cost: float
    initial_upload_cost: float
    estimated_restore_cost: float
    by_category: dict[str, Any]


class BackupStatusResponse(BaseModel):
    enabled: bool
    bucket: str | None = None
    region: str | None = None
    schedule: str | None = None
    is_running: bool = False
    last_backup: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None


class BackupProgressResponse(BaseModel):
    status: str
    phase: str
    files_total: int = 0
    files_uploaded: int = 0
    files_skipped: int = 0
    bytes_uploaded: int = 0
    current_file: str | None = None
    started_at: str | None = None
    error: str | None = None


class ManifestResponse(BaseModel):
    last_backup_at: str | None = None
    database: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None
    file_count: int = 0
    total_size_bytes: int = 0
    by_category: dict[str, Any] = {}


class RestoreRequest(BaseModel):
    categories: list[str] | None = None


class RestoreDownloadRequest(BaseModel):
    confirm: bool = False


# ── Phase 1: Validation & Estimate ───────────────────────────────────


@router.post("/validate", response_model=ValidateResponse)
async def validate_credentials(request: ValidateRequest) -> ValidateResponse:
    """Validate AWS credentials and required S3 permissions.

    Credentials are read from environment variables (S3_BACKUP_ACCESS_KEY_ID,
    S3_BACKUP_SECRET_ACCESS_KEY) or settings.json via get_effective().
    """
    app_settings = get_app_settings_service()
    access_key = app_settings.get_effective("s3_backup_access_key_id")
    secret_key = app_settings.get_effective("s3_backup_secret_access_key")

    if not access_key or not secret_key:
        return ValidateResponse(
            valid=False,
            permissions={"put": False, "get": False, "list": False, "restore": False},
            error="AWS credentials not configured. Set S3_BACKUP_ACCESS_KEY_ID and S3_BACKUP_SECRET_ACCESS_KEY in docker/.env",
        )

    service = get_s3_backup_service()
    loop = asyncio.get_event_loop()

    result = await loop.run_in_executor(
        None,
        lambda: service.validate_credentials(
            bucket=request.bucket,
            region=request.region,
            access_key_id=access_key,
            secret_access_key=secret_key,
            prefix=request.prefix,
        ),
    )
    return ValidateResponse(**result)


@router.get("/estimate", response_model=CostEstimateResponse)
async def get_cost_estimate() -> CostEstimateResponse:
    """Estimate S3 backup costs based on actual library data sizes."""
    service = get_s3_backup_service()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, service.estimate_cost)
    return CostEstimateResponse(**result)


@router.get("/status", response_model=BackupStatusResponse)
async def get_backup_status() -> BackupStatusResponse:
    """Get backup status: enabled, last backup, next scheduled."""
    service = get_s3_backup_service()
    status = service.get_status()
    return BackupStatusResponse(**status)


# ── Phase 2: Manual Backup ───────────────────────────────────────────


@router.post("/run")
async def trigger_backup() -> dict[str, Any]:
    """Trigger a manual backup. Runs in background thread."""
    service = get_s3_backup_service()

    # Check if already running
    progress = service.get_backup_progress()
    if progress and progress.get("status") == "running":
        return {"status": "already_running", "message": "A backup is already in progress"}

    # Run in background thread
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, service.run_backup)

    return {"status": "started", "message": "Backup started"}


@router.get("/progress", response_model=BackupProgressResponse)
async def get_progress() -> BackupProgressResponse:
    """Poll backup progress."""
    service = get_s3_backup_service()
    progress = service.get_backup_progress()
    if progress:
        return BackupProgressResponse(**progress)
    return BackupProgressResponse(status="idle", phase="idle")


@router.post("/cancel")
async def cancel_backup() -> dict[str, str]:
    """Cancel a running backup."""
    service = get_s3_backup_service()
    if service.cancel_backup():
        return {"status": "cancelling", "message": "Backup cancellation requested"}
    return {"status": "not_running", "message": "No backup is currently running"}


# ── Phase 3: History ─────────────────────────────────────────────────


@router.get("/history")
async def get_backup_history() -> list[dict[str, Any]]:
    """Get backup history (last 10 runs)."""
    service = get_s3_backup_service()
    return service.get_backup_history()


# ── Phase 4: Restore — Initiation ───────────────────────────────────


@router.get("/manifest", response_model=ManifestResponse)
async def get_manifest() -> ManifestResponse:
    """Get backup contents from manifest (instant, stored in S3 Standard)."""
    service = get_s3_backup_service()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, service.get_manifest)
    return ManifestResponse(**result)


@router.post("/restore")
async def initiate_restore(request: RestoreRequest) -> dict[str, Any]:
    """Initiate Glacier retrieval for backed-up files.

    This sends RestoreObject requests to start the 12-48 hour retrieval process.
    """
    service = get_s3_backup_service()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: service.initiate_restore(request.categories),
    )
    return result


@router.get("/restore/status")
async def get_restore_status() -> dict[str, Any]:
    """Get Glacier retrieval progress."""
    service = get_s3_backup_service()
    return service.get_restore_status()


@router.post("/restore/check")
async def check_restore_availability() -> dict[str, Any]:
    """Check if Glacier retrieval is complete (HEAD requests on sample)."""
    service = get_s3_backup_service()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, service.check_restore_status)
    return result


# ── Phase 5: Restore — Download ─────────────────────────────────────


@router.post("/restore/download")
async def download_and_restore(request: RestoreDownloadRequest) -> dict[str, Any]:
    """Download restored files from S3 and apply.

    Requires confirm=true. Creates a local safety backup first.
    """
    if not request.confirm:
        return {
            "status": "error",
            "error": "Must pass confirm=true to proceed with restore",
        }

    service = get_s3_backup_service()

    # Run in background thread
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, service.download_and_restore)

    return {"status": "started", "message": "Restore download started"}


@router.get("/restore/progress")
async def get_restore_download_progress() -> BackupProgressResponse:
    """Get restore download progress (reuses backup progress key)."""
    service = get_s3_backup_service()
    progress = service.get_backup_progress()
    if progress:
        return BackupProgressResponse(**progress)
    return BackupProgressResponse(status="idle", phase="idle")
