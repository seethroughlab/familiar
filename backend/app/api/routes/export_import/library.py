"""Library export/import endpoints (for machine migration)."""

import gzip
import json
import logging
from typing import Any

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import DbSession
from app.api.exceptions import (
    FamiliarError,
    PayloadTooLargeError,
    ValidationError,
    sanitize_error_for_client,
)
from app.services.export_import import LibraryExportService, LibraryImportService
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class LibraryExportRequest(BaseModel):
    """Request to export library data."""

    include_embeddings: bool = Field(
        default=True,
        description="Include audio embeddings (increases file size significantly)",
    )
    include_acoustid: bool = Field(
        default=True,
        description="Include audio fingerprints",
    )
    include_midi: bool = Field(
        default=True,
        description="Include MIDI transcription files",
    )
    include_ssm: bool = Field(
        default=True,
        description="Include self-similarity matrix images",
    )
    compress: bool = Field(
        default=True,
        description="Compress output with gzip",
    )


class LibraryImportPreviewResponse(BaseModel):
    """Response from library import preview."""

    session_id: str
    summary: dict[str, Any]
    matching: dict[str, Any]
    warnings: list[str]
    exported_at: str | None
    familiar_version: str | None


class LibraryImportExecuteRequest(BaseModel):
    """Request to execute a library import."""

    session_id: str
    mode: str = Field(
        default="match_only",
        pattern="^(match_only|merge|replace)$",
        description="match_only: Only apply to matched tracks. merge: Fill gaps. replace: Overwrite all.",
    )
    apply_metadata: bool = Field(
        default=False,
        description="Update track metadata (usually not needed for same library)",
    )
    apply_analysis: bool = Field(
        default=True,
        description="Import analysis features",
    )
    apply_embeddings: bool = Field(
        default=True,
        description="Import audio embeddings",
    )
    apply_user_overrides: bool = Field(
        default=True,
        description="Import user overrides (BPM corrections, etc.)",
    )


class LibraryImportExecuteResponse(BaseModel):
    """Response from library import execution."""

    status: str
    results: dict[str, Any]


# ============================================================================
# Library Export/Import Endpoints
# ============================================================================


@router.post("/library/export")
async def export_library(
    request: LibraryExportRequest,
    db: DbSession,
) -> StreamingResponse:
    """Export full library data for migration to another machine.

    Includes:
    - Track metadata
    - Analysis features
    - Audio embeddings (optional)
    - User overrides

    Returns a streaming download of JSON (optionally gzipped).
    """
    service = LibraryExportService(db)

    # Generate filename
    date_str = utcnow().strftime("%Y%m%d")
    extension = ".json.gz" if request.compress else ".json"
    filename = f"familiar-library-export-{date_str}{extension}"

    # Stream the export
    async def generate():
        async for chunk in service.export_library(
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


@router.post("/library/import/preview", response_model=LibraryImportPreviewResponse)
async def preview_library_import(
    db: DbSession,
    file: UploadFile = File(...),
) -> LibraryImportPreviewResponse:
    """Preview a library import file and get matching statistics.

    Upload a Familiar library export file to see:
    - How many tracks can be matched by file_hash, acoustid, ISRC, etc.
    - Warnings about potential issues
    - Summary of importable data

    Returns a session_id to use with /library/import/execute.
    Supports both .json and .json.gz files.
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
        if len(content) > 500 * 1024 * 1024:  # 500MB limit for library exports
            raise PayloadTooLargeError("File too large (max 500MB)")

        if is_gzipped:
            content = gzip.decompress(content)

        import_data = json.loads(content.decode("utf-8"))

    except gzip.BadGzipFile:
        raise ValidationError("Invalid gzip file")
    except json.JSONDecodeError:
        raise ValidationError("The uploaded file is not valid JSON. Make sure you're uploading a Familiar library export file.")
    except UnicodeDecodeError:
        raise ValidationError("File must be UTF-8 encoded")

    # Validate basic structure
    if not isinstance(import_data, dict):
        raise ValidationError("Invalid export file format")

    if import_data.get("export_type") != "library":
        raise ValidationError("Not a library export file (use /import/preview for profile exports)")

    # Generate preview
    service = LibraryImportService(db)
    session_id, preview = await service.preview_import(import_data)

    return LibraryImportPreviewResponse(
        session_id=preview["session_id"],
        summary=preview["summary"],
        matching=preview["matching"],
        warnings=preview["warnings"],
        exported_at=preview.get("exported_at"),
        familiar_version=preview.get("familiar_version"),
    )


@router.post("/library/import/execute", response_model=LibraryImportExecuteResponse)
async def execute_library_import(
    request: LibraryImportExecuteRequest,
    db: DbSession,
) -> LibraryImportExecuteResponse:
    """Execute a library import from a previewed session.

    Requires a valid session_id from /library/import/preview.

    Modes:
    - match_only: Only apply data to tracks found in library
    - merge: Fill gaps in existing data
    - replace: Overwrite existing data
    """
    service = LibraryImportService(db)

    try:
        results = await service.execute_import(
            session_id=request.session_id,
            mode=request.mode,
            apply_metadata=request.apply_metadata,
            apply_analysis=request.apply_analysis,
            apply_embeddings=request.apply_embeddings,
            apply_user_overrides=request.apply_user_overrides,
        )
    except ValueError as e:
        raise ValidationError(sanitize_error_for_client(e, "Invalid import request"))
    except Exception as e:
        logger.error(f"Library import failed: {e}")
        raise FamiliarError(sanitize_error_for_client(e, "Library import failed unexpectedly. The file may be corrupted or from an incompatible version."))

    return LibraryImportExecuteResponse(
        status=results["status"],
        results=results["results"],
    )
