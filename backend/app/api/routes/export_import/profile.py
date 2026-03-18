"""Profile data export/import endpoints."""

import json
import logging
from typing import Any

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import (
    FamiliarError,
    PayloadTooLargeError,
    ValidationError,
    sanitize_error_for_client,
)
from app.services.export_import import ExportImportService, ImportService
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class ExportRequest(BaseModel):
    """Request to export profile data."""

    include_play_history: bool = True
    include_favorites: bool = True
    include_playlists: bool = True
    include_smart_playlists: bool = True
    include_proposed_changes: bool = True
    chat_history: list[dict[str, Any]] | None = Field(
        default=None,
        description="Chat history from frontend IndexedDB (passed through)",
    )


class ImportPreviewResponse(BaseModel):
    """Response from import preview."""

    session_id: str
    summary: dict[str, int]
    matching: dict[str, Any]
    warnings: list[str]
    exported_at: str | None
    familiar_version: str | None
    profile_name: str | None


class ImportExecuteRequest(BaseModel):
    """Request to execute an import."""

    session_id: str
    mode: str = Field(default="merge", pattern="^(merge|overwrite)$")
    import_play_history: bool = True
    import_favorites: bool = True
    import_playlists: bool = True
    import_smart_playlists: bool = True
    import_proposed_changes: bool = True
    import_user_overrides: bool = True


class ImportResultCategory(BaseModel):
    """Results for a single import category."""

    imported: int
    skipped: int
    errors: list[str]


class ImportExecuteResponse(BaseModel):
    """Response from import execution."""

    status: str
    results: dict[str, Any]


# ============================================================================
# Export Endpoints
# ============================================================================


@router.post("/export")
async def export_profile_data(
    request: ExportRequest,
    db: DbSession,
    profile: RequiredProfile,
) -> JSONResponse:
    """Export profile data as JSON.

    Returns a JSON file containing all selected data categories.
    Track references use ISRC, MusicBrainz ID, and metadata for matching.
    """
    service = ExportImportService(db)

    export_data = await service.export_profile(
        profile=profile,
        include_play_history=request.include_play_history,
        include_favorites=request.include_favorites,
        include_playlists=request.include_playlists,
        include_smart_playlists=request.include_smart_playlists,
        include_proposed_changes=request.include_proposed_changes,
        chat_history=request.chat_history,
    )

    # Generate filename
    date_str = utcnow().strftime("%Y%m%d")
    safe_name = profile.name.replace(" ", "_").replace("/", "-")[:20]
    filename = f"familiar-export-{safe_name}-{date_str}.json"

    return JSONResponse(
        content=export_data,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/json",
        },
    )


# ============================================================================
# Import Endpoints
# ============================================================================


@router.post("/import/preview", response_model=ImportPreviewResponse)
async def preview_import(
    db: DbSession,
    profile: RequiredProfile,
    file: UploadFile = File(...),
) -> ImportPreviewResponse:
    """Preview an import file and get matching statistics.

    Upload a Familiar export JSON file to see:
    - Summary of data categories
    - Track matching results (how many tracks can be matched to your library)
    - Warnings about potential issues

    Returns a session_id to use with /import/execute.
    """
    # Validate file type
    if not file.filename or not file.filename.endswith(".json"):
        raise ValidationError("File must be a JSON file")

    # Read and parse file
    try:
        content = await file.read()
        if len(content) > 50 * 1024 * 1024:  # 50MB limit
            raise PayloadTooLargeError("File too large (max 50MB)")

        import_data = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError:
        raise ValidationError("The uploaded file is not valid JSON. Make sure you're uploading a Familiar export file.")
    except UnicodeDecodeError:
        raise ValidationError("File must be UTF-8 encoded")

    # Validate basic structure
    if not isinstance(import_data, dict):
        raise ValidationError("Invalid export file format")

    if "version" not in import_data:
        raise ValidationError("Missing version field - not a valid Familiar export")

    # Generate preview
    service = ImportService(db)
    session_id, preview = await service.preview_import(import_data)

    return ImportPreviewResponse(
        session_id=preview["session_id"],
        summary=preview["summary"],
        matching=preview["matching"],
        warnings=preview["warnings"],
        exported_at=preview.get("exported_at"),
        familiar_version=preview.get("familiar_version"),
        profile_name=preview.get("profile_name"),
    )


@router.post("/import/execute", response_model=ImportExecuteResponse)
async def execute_import(
    request: ImportExecuteRequest,
    db: DbSession,
    profile: RequiredProfile,
) -> ImportExecuteResponse:
    """Execute an import from a previewed session.

    Requires a valid session_id from /import/preview.

    Modes:
    - merge: Add new data, combine play counts, skip existing playlists
    - overwrite: Replace all data in selected categories
    """
    service = ImportService(db)

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
        )
    except ValueError as e:
        raise ValidationError(sanitize_error_for_client(e, "Invalid import request"))
    except Exception as e:
        logger.error(f"Import failed: {e}")
        raise FamiliarError(sanitize_error_for_client(e, "Import failed unexpectedly. The file may be corrupted or from an incompatible version."))

    return ImportExecuteResponse(
        status=results["status"],
        results=results["results"],
    )
