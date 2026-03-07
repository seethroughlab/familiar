"""Data export/import endpoints.

Handles exporting and importing user data for backup and migration.
Also handles full library export/import for machine migration.
"""

import gzip
import json
import logging
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import sanitize_error_for_client
from app.services.export_import import (
    BackupService,
    ExportImportService,
    ImportService,
    LibraryExportService,
    LibraryImportService,
    RestoreService,
)
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export-import", tags=["export-import"])


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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a JSON file",
        )

    # Read and parse file
    try:
        content = await file.read()
        if len(content) > 50 * 1024 * 1024:  # 50MB limit
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File too large (max 50MB)",
            )

        import_data = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is not valid JSON. Make sure you're uploading a Familiar export file.",
        )
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be UTF-8 encoded",
        )

    # Validate basic structure
    if not isinstance(import_data, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid export file format",
        )

    if "version" not in import_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing version field - not a valid Familiar export",
        )

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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=sanitize_error_for_client(e, "Invalid import request"),
        )
    except Exception as e:
        logger.error(f"Import failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=sanitize_error_for_client(e, "Import failed unexpectedly. The file may be corrupted or from an incompatible version."),
        )

    return ImportExecuteResponse(
        status=results["status"],
        results=results["results"],
    )


# ============================================================================
# Library Export/Import Endpoints (for machine migration)
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing filename",
        )

    is_gzipped = file.filename.endswith(".gz")
    if not (file.filename.endswith(".json") or file.filename.endswith(".json.gz")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a JSON or gzipped JSON file",
        )

    # Read and parse file
    try:
        content = await file.read()
        if len(content) > 500 * 1024 * 1024:  # 500MB limit for library exports
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File too large (max 500MB)",
            )

        if is_gzipped:
            content = gzip.decompress(content)

        import_data = json.loads(content.decode("utf-8"))

    except gzip.BadGzipFile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid gzip file",
        )
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is not valid JSON. Make sure you're uploading a Familiar library export file.",
        )
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be UTF-8 encoded",
        )

    # Validate basic structure
    if not isinstance(import_data, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid export file format",
        )

    if import_data.get("export_type") != "library":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not a library export file (use /import/preview for profile exports)",
        )

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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=sanitize_error_for_client(e, "Invalid import request"),
        )
    except Exception as e:
        logger.error(f"Library import failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=sanitize_error_for_client(e, "Library import failed unexpectedly. The file may be corrupted or from an incompatible version."),
        )

    return LibraryImportExecuteResponse(
        status=results["status"],
        results=results["results"],
    )


# ============================================================================
# Backup/Restore Endpoints
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
    chat_history: list[dict[str, Any]] | None = Field(default=None, description="Chat history from frontend IndexedDB")


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
            chat_history=request.chat_history,
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing filename",
        )

    is_gzipped = file.filename.endswith(".gz")
    if not (file.filename.endswith(".json") or file.filename.endswith(".json.gz")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a JSON or gzipped JSON file",
        )

    # Read and parse file
    try:
        content = await file.read()
        if len(content) > 500 * 1024 * 1024:  # 500MB limit
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File too large (max 500MB)",
            )

        if is_gzipped:
            content = gzip.decompress(content)

        import_data = json.loads(content.decode("utf-8"))

    except gzip.BadGzipFile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid gzip file",
        )
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is not valid JSON. Make sure you're uploading a Familiar backup file.",
        )
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be UTF-8 encoded",
        )

    # Validate basic structure
    if not isinstance(import_data, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid backup file format",
        )

    if "version" not in import_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing version field - not a valid Familiar backup",
        )

    # Generate preview
    service = RestoreService(db)

    try:
        session_id, preview = await service.preview_import(import_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=sanitize_error_for_client(e, "Invalid backup file"),
        )

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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=sanitize_error_for_client(e, "Invalid restore request"),
        )
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=sanitize_error_for_client(e, "Restore failed unexpectedly. The backup file may be corrupted or from an incompatible version."),
        )

    return RestoreExecuteResponse(
        status=results["status"],
        results=results["results"],
    )
