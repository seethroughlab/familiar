"""Enhanced import with preview endpoints."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

from app.api.deps import DbSession
from app.api.exceptions import (
    FileOperationError,
    LibraryImportError,
    ValidationError,
    sanitize_error_for_client,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class ImportTrackPreview(BaseModel):
    """Preview info for a single track."""
    filename: str
    relative_path: str
    detected_artist: str | None
    detected_album: str | None
    detected_title: str | None
    detected_track_num: int | None
    detected_year: int | None = None
    format: str
    duration_seconds: float | None
    file_size_bytes: int
    sample_rate: int | None = None
    bit_depth: int | None = None
    bitrate: int | None = None
    bitrate_mode: str | None = None  # "CBR", "VBR", or None
    # Duplicate detection
    duplicate_of: str | None = None  # ID of existing track if duplicate found
    duplicate_info: str | None = None  # e.g. "Artist - Album - Title"
    # Quality comparison (for duplicates)
    trump_status: str | None = None  # "trumps", "trumped_by", "equal"
    trump_reason: str | None = None  # Human-readable comparison reason
    incoming_quality: dict | None = None  # Quality info for incoming track
    existing_quality: dict | None = None  # Quality info for existing track
    duplicate_match_type: str | None = None  # "exact", "normalized", "artist_title"


class ImportPreviewResponse(BaseModel):
    """Response from import preview endpoint."""
    session_id: str
    tracks: list[ImportTrackPreview]
    total_size_bytes: int
    estimated_sizes: dict[str, int]
    has_convertible_formats: bool


class ImportFromPathRequest(BaseModel):
    """Request body for importing from a local path."""
    source_path: str


# ============================================================================
# Duplicate detection (delegated to shared service)
# ============================================================================

from app.services.duplicate_detection import (  # noqa: E402
    enrich_tracks_with_duplicates as _enrich_tracks_with_duplicates,
)

# ============================================================================
# Endpoints
# ============================================================================


@router.post("/import/preview", response_model=ImportPreviewResponse)
async def import_preview(
    db: DbSession,
    file: UploadFile = File(...),
) -> ImportPreviewResponse:
    """Preview an import - extract and scan files without importing.

    Uploads file to temp location, extracts if zip, scans metadata,
    and returns preview with session_id for later execution.

    Session expires after 24 hours if not executed.
    """
    from app.services.import_service import (
        ImportPreviewService,
        MusicImportError,
        save_upload_to_temp,
    )

    if not file.filename:
        raise ValidationError("No filename provided")

    # Read uploaded file
    content = await file.read()
    if len(content) == 0:
        raise ValidationError("Empty file")

    # Save to temp file
    try:
        temp_path = save_upload_to_temp(content, file.filename)
    except Exception as e:
        raise FileOperationError("Failed to save upload", detail=str(e))

    try:
        preview_service = ImportPreviewService()
        result = preview_service.create_preview_session(temp_path, file.filename)

        tracks = result["tracks"]
        await _enrich_tracks_with_duplicates(db, tracks)

        return ImportPreviewResponse(
            session_id=result["session_id"],
            tracks=[ImportTrackPreview(**t) for t in tracks],
            total_size_bytes=result["total_size_bytes"],
            estimated_sizes=result["estimated_sizes"],
            has_convertible_formats=result["has_convertible_formats"],
        )

    except MusicImportError as e:
        raise ValidationError(sanitize_error_for_client(e, "Preview failed"))
    except Exception:
        raise LibraryImportError("Preview failed")
    finally:
        # Clean up temp file (session has its own copy)
        temp_path.unlink(missing_ok=True)


@router.post("/import/preview-from-path", response_model=ImportPreviewResponse)
async def import_preview_from_path(
    db: DbSession,
    request: ImportFromPathRequest,
) -> ImportPreviewResponse:
    """Preview an import from a local filesystem path.

    Scans audio files at the given path, extracts metadata, detects
    duplicates and compares quality — without copying anything yet.
    Returns a session_id for later execution via POST /import/execute.
    """
    from app.services.import_service import ImportPreviewService, MusicImportError

    try:
        preview_service = ImportPreviewService()
        result = preview_service.create_preview_from_path(Path(request.source_path))

        tracks = result["tracks"]
        await _enrich_tracks_with_duplicates(db, tracks)

        return ImportPreviewResponse(
            session_id=result["session_id"],
            tracks=[ImportTrackPreview(**t) for t in tracks],
            total_size_bytes=result["total_size_bytes"],
            estimated_sizes=result["estimated_sizes"],
            has_convertible_formats=result["has_convertible_formats"],
        )

    except MusicImportError as e:
        raise ValidationError(sanitize_error_for_client(e, "Preview failed"))
    except Exception:
        raise LibraryImportError("Preview failed")
