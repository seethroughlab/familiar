"""Backup/restore endpoints."""

import gzip
import json
import logging
from typing import Any

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import (
    FamiliarError,
    PayloadTooLargeError,
    ValidationError,
    sanitize_error_for_client,
)
from app.services.export_import import BackupService, RestoreService
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class BackupRequest(BaseModel):
    """Request to create a backup."""

    # Profile data options
    include_play_history: bool = Field(default=True, description="Include play history")
    include_favorites: bool = Field(default=True, description="Include favorites")
    include_playlists: bool = Field(default=True, description="Include playlists")
    include_smart_playlists: bool = Field(default=True, description="Include smart playlists")
    include_proposed_changes: bool = Field(default=True, description="Include pending changes")

    # Library data options
    include_library_analysis: bool = Field(default=False, description="Include audio analysis")
    include_embeddings: bool = Field(default=True, description="Include audio embeddings (requires library analysis)")
    include_acoustid: bool = Field(default=True, description="Include audio fingerprints (requires library analysis)")
    include_midi: bool = Field(default=True, description="Include MIDI transcription files (requires library analysis)")
    include_ssm: bool = Field(default=True, description="Include self-similarity matrix images (requires library analysis)")

    # Output options
    compress: bool = Field(default=True, description="Compress output with gzip")

    # Optional chat history from frontend


class RestorePreviewResponse(BaseModel):
    """Response from restore preview."""

    session_id: str
    summary: dict[str, Any]
    profile_matching: dict[str, Any]
    library_matching: dict[str, Any]
    warnings: list[str]
    exported_at: str | None
    familiar_version: str | None
    profile_name: str | None


class RestoreExecuteRequest(BaseModel):
    """Request to execute a restore."""

    session_id: str

    # Profile import options
    mode: str = Field(default="merge", pattern="^(merge|overwrite)$")
    import_play_history: bool = True
    import_favorites: bool = True
    import_playlists: bool = True
    import_smart_playlists: bool = True
    import_proposed_changes: bool = True
    import_user_overrides: bool = True

    # Library import options
    library_mode: str = Field(
        default="match_only",
        pattern="^(match_only|merge|replace)$",
        description="match_only: Only apply to matched tracks. merge: Fill gaps. replace: Overwrite all.",
    )
    apply_analysis: bool = Field(default=True, description="Import analysis features")
    apply_embeddings: bool = Field(default=True, description="Import audio embeddings")
    apply_library_user_overrides: bool = Field(default=True, description="Import library user overrides")


class RestoreExecuteResponse(BaseModel):
    """Response from restore execution."""

    status: str
    results: dict[str, Any]


# ============================================================================
# Backup/Restore Endpoints
# ============================================================================


@router.post("/backup")
async def create_backup(
    request: BackupRequest,
    db: DbSession,
    profile: RequiredProfile,
) -> StreamingResponse:
    """Create a backup of profile and/or library data.

    Returns a streaming download of JSON (optionally gzipped).
    Includes what was selected: profile data (playlists, favorites, play history)
    and/or library analysis data (features, embeddings, fingerprints).
    """
    service = BackupService(db)

    # Generate filename
    date_str = utcnow().strftime("%Y%m%d")
    safe_name = profile.name.replace(" ", "_").replace("/", "-")[:20]

    # Describe what's included
    parts = []
    if any([
        request.include_play_history,
        request.include_favorites,
        request.include_playlists,
        request.include_smart_playlists,
    ]):
        parts.append("profile")
    if request.include_library_analysis:
        parts.append("library")

    content_desc = "-".join(parts) if parts else "backup"
    extension = ".json.gz" if request.compress else ".json"
    filename = f"familiar-backup-{safe_name}-{content_desc}-{date_str}{extension}"

    # Stream the backup
    async def generate():
        async for chunk in service.create_backup(
            profile=profile,
            include_play_history=request.include_play_history,
            include_favorites=request.include_favorites,
            include_playlists=request.include_playlists,
            include_smart_playlists=request.include_smart_playlists,
            include_proposed_changes=request.include_proposed_changes,
            include_library_analysis=request.include_library_analysis,
            include_embeddings=request.include_embeddings,
            include_acoustid=request.include_acoustid,
            include_midi=request.include_midi,
            include_ssm=request.include_ssm,
            compress=request.compress,
        ):
            yield chunk

    media_type = "application/gzip" if request.compress else "application/json"

    return StreamingResponse(
        generate(),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/restore/preview", response_model=RestorePreviewResponse)
async def preview_restore(
    db: DbSession,
    profile: RequiredProfile,
    file: UploadFile = File(...),
) -> RestorePreviewResponse:
    """Preview a backup file and get matching statistics.

    Accepts backup files (.json or .json.gz).
    Returns a session_id to use with /restore/execute.
    """
    # Validate file type
    if not file.filename:
        raise ValidationError("Missing filename")

    is_gzipped = file.filename.endswith(".gz")
    if not (file.filename.endswith(".json") or file.filename.endswith(".json.gz")):
        raise ValidationError("File must be a JSON or gzipped JSON file")

    # Read and parse file
    try:
        content = await file.read()
        if len(content) > 500 * 1024 * 1024:  # 500MB limit
            raise PayloadTooLargeError("File too large (max 500MB)")

        if is_gzipped:
            content = gzip.decompress(content)

        import_data = json.loads(content.decode("utf-8"))

    except gzip.BadGzipFile:
        raise ValidationError("Invalid gzip file")
    except json.JSONDecodeError:
        raise ValidationError("The uploaded file is not valid JSON. Make sure you're uploading a Familiar backup file.")
    except UnicodeDecodeError:
        raise ValidationError("File must be UTF-8 encoded")

    # Validate basic structure
    if not isinstance(import_data, dict):
        raise ValidationError("Invalid backup file format")

    if "version" not in import_data:
        raise ValidationError("Missing version field - not a valid Familiar backup")

    # Generate preview
    service = RestoreService(db)

    try:
        session_id, preview = await service.preview_import(import_data)
    except ValueError as e:
        raise ValidationError(sanitize_error_for_client(e, "Invalid backup file"))

    return RestorePreviewResponse(
        session_id=preview["session_id"],
        summary=preview["summary"],
        profile_matching=preview.get("profile_matching", {}),
        library_matching=preview.get("library_matching", {}),
        warnings=preview["warnings"],
        exported_at=preview.get("exported_at"),
        familiar_version=preview.get("familiar_version"),
        profile_name=preview.get("profile_name"),
    )


@router.post("/restore/execute", response_model=RestoreExecuteResponse)
async def execute_restore(
    request: RestoreExecuteRequest,
    db: DbSession,
    profile: RequiredProfile,
) -> RestoreExecuteResponse:
    """Execute a restore from a previewed session.

    Requires a valid session_id from /restore/preview.

    Profile modes:
    - merge: Add new data, combine play counts, skip existing playlists
    - overwrite: Replace all data in selected categories

    Library modes:
    - match_only: Only apply to matched tracks
    - merge: Fill gaps in existing data
    - replace: Overwrite existing data
    """
    service = RestoreService(db)

    try:
        results = await service.execute_import(
            session_id=request.session_id,
            profile=profile,
            mode=request.mode,
            import_play_history=request.import_play_history,
            import_favorites=request.import_favorites,
            import_playlists=request.import_playlists,
            import_smart_playlists=request.import_smart_playlists,
            import_proposed_changes=request.import_proposed_changes,
            import_user_overrides=request.import_user_overrides,
            library_mode=request.library_mode,
            apply_analysis=request.apply_analysis,
            apply_embeddings=request.apply_embeddings,
            apply_library_user_overrides=request.apply_library_user_overrides,
        )
    except ValueError as e:
        raise ValidationError(sanitize_error_for_client(e, "Invalid restore request"))
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        raise FamiliarError(sanitize_error_for_client(e, "Restore failed unexpectedly. The backup file may be corrupted or from an incompatible version."))

    return RestoreExecuteResponse(
        status=results["status"],
        results=results["results"],
    )
