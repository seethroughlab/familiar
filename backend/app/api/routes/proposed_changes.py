"""Proposed changes API routes.

Endpoints for managing metadata change proposals: listing, approving,
rejecting, applying, and undoing changes.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import ChangeScope, ChangeSource, ChangeStatus
from app.services.proposed_changes import (
    ApplyResult,
    ChangePreview,
    ChangeStats,
    ProposedChangesService,
)

router = APIRouter(prefix="/proposed-changes", tags=["Proposed Changes"])


# ============================================================================
# Response Models
# ============================================================================


class ProposedChangeResponse(BaseModel):
    """Response model for a proposed change."""

    id: str
    change_type: str
    target_type: str
    target_ids: list[str]
    field: str | None
    old_value: Any
    new_value: Any
    source: str
    source_detail: str | None
    confidence: float
    reason: str | None
    scope: str
    status: str
    created_at: str
    applied_at: str | None
    target_description: str | None = None


class ChangePreviewResponse(BaseModel):
    """Response model for change preview."""

    change_id: str
    target_description: str
    field: str | None
    old_value: Any
    new_value: Any
    tracks_affected: int
    files_affected: list[str]
    scope: str


class ApplyResultResponse(BaseModel):
    """Response model for apply result."""

    change_id: str
    success: bool
    error: str | None
    db_updated: bool
    id3_written: bool
    id3_errors: list[str]
    files_moved: bool
    files_errors: list[str]


class ChangeStatsResponse(BaseModel):
    """Response model for change statistics."""

    pending: int
    rejected: int
    applied: int


class CreateChangeRequest(BaseModel):
    """Request model for creating a change."""

    change_type: str
    target_type: str
    target_ids: list[str]
    field: str | None = None
    old_value: Any = None
    new_value: Any
    source: str = "user_request"
    source_detail: str | None = None
    confidence: float = 1.0
    reason: str | None = None
    scope: str = "db_only"


class BatchApplyRequest(BaseModel):
    """Request for batch apply."""

    change_ids: list[str]
    scope: str | None = None  # Override scope for all changes


# ============================================================================
# Helper Functions
# ============================================================================


def _change_to_response(
    change, target_description: str | None = None
) -> ProposedChangeResponse:
    """Convert ProposedChange model to response."""
    return ProposedChangeResponse(
        id=str(change.id),
        change_type=change.change_type,
        target_type=change.target_type,
        target_ids=change.target_ids,
        field=change.field,
        old_value=change.old_value,
        new_value=change.new_value,
        source=change.source.value if hasattr(change.source, "value") else change.source,
        source_detail=change.source_detail,
        confidence=change.confidence,
        reason=change.reason,
        scope=change.scope.value if hasattr(change.scope, "value") else change.scope,
        status=change.status.value if hasattr(change.status, "value") else change.status,
        created_at=change.created_at.isoformat() if change.created_at else None,
        applied_at=change.applied_at.isoformat() if change.applied_at else None,
        target_description=target_description,
    )


def _preview_to_response(preview: ChangePreview) -> ChangePreviewResponse:
    """Convert ChangePreview to response."""
    return ChangePreviewResponse(
        change_id=str(preview.change_id),
        target_description=preview.target_description,
        field=preview.field,
        old_value=preview.old_value,
        new_value=preview.new_value,
        tracks_affected=preview.tracks_affected,
        files_affected=preview.files_affected,
        scope=str(preview.scope.value if hasattr(preview.scope, "value") else preview.scope),
    )


def _apply_result_to_response(result: ApplyResult) -> ApplyResultResponse:
    """Convert ApplyResult to response."""
    return ApplyResultResponse(
        change_id=str(result.change_id),
        success=result.success,
        error=result.error,
        db_updated=result.db_updated,
        id3_written=result.id3_written,
        id3_errors=result.id3_errors,
        files_moved=result.files_moved,
        files_errors=result.files_errors,
    )


def _stats_to_response(stats: ChangeStats) -> ChangeStatsResponse:
    """Convert ChangeStats to response."""
    return ChangeStatsResponse(
        pending=stats.pending,
        rejected=stats.rejected,
        applied=stats.applied,
    )


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/", response_model=list[ProposedChangeResponse])
async def list_changes(
    status: str | None = Query(None, description="Filter by status: pending, approved, rejected, applied"),
    source: str | None = Query(None, description="Filter by source"),
    target_type: str | None = Query(None, description="Filter by target type: track, album"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[ProposedChangeResponse]:
    """List proposed changes with optional filtering."""
    service = ProposedChangesService(db)

    if status:
        try:
            status_enum = ChangeStatus(status)
            changes = await service.get_by_status(status_enum, limit=limit, offset=offset)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    else:
        changes = await service.get_all(limit=limit, offset=offset)

    descriptions = await service.enrich_with_descriptions(changes)
    return [_change_to_response(c, descriptions.get(c.id)) for c in changes]


@router.get("/stats", response_model=ChangeStatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
) -> ChangeStatsResponse:
    """Get summary statistics for proposed changes."""
    service = ProposedChangesService(db)
    stats = await service.get_stats()
    return _stats_to_response(stats)


@router.get("/{change_id}", response_model=ProposedChangeResponse)
async def get_change(
    change_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ProposedChangeResponse:
    """Get a single proposed change by ID."""
    service = ProposedChangesService(db)
    change = await service.get_by_id(change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return _change_to_response(change)


@router.get("/{change_id}/preview", response_model=ChangePreviewResponse)
async def preview_change(
    change_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ChangePreviewResponse:
    """Preview what applying a change would do."""
    service = ProposedChangesService(db)
    preview = await service.preview(change_id)
    if not preview:
        raise HTTPException(status_code=404, detail="Change not found")
    return _preview_to_response(preview)


@router.get("/track/{track_id}", response_model=list[ProposedChangeResponse])
async def get_track_changes(
    track_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ProposedChangeResponse]:
    """Get all proposed changes affecting a specific track."""
    service = ProposedChangesService(db)
    changes = await service.get_by_track(track_id)
    return [_change_to_response(c) for c in changes]


@router.post("/", response_model=ProposedChangeResponse)
async def create_change(
    request: CreateChangeRequest,
    db: AsyncSession = Depends(get_db),
) -> ProposedChangeResponse:
    """Create a new proposed change."""
    service = ProposedChangesService(db)

    try:
        source_enum = ChangeSource(request.source)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid source: {request.source}")

    try:
        scope_enum = ChangeScope(request.scope)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid scope: {request.scope}")

    change = await service.create_change(
        change_type=request.change_type,
        target_type=request.target_type,
        target_ids=request.target_ids,
        field=request.field,
        old_value=request.old_value,
        new_value=request.new_value,
        source=source_enum,
        source_detail=request.source_detail,
        confidence=request.confidence,
        reason=request.reason,
        scope=scope_enum,
    )
    return _change_to_response(change)


@router.post("/{change_id}/reject", response_model=ProposedChangeResponse)
async def reject_change(
    change_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ProposedChangeResponse:
    """Reject a proposed change."""
    service = ProposedChangesService(db)
    change = await service.reject(change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return _change_to_response(change)


@router.post("/{change_id}/apply", response_model=ApplyResultResponse)
async def apply_change(
    change_id: UUID,
    scope: str | None = Query(None, description="Override scope: db_only, db_and_id3, db_id3_files"),
    db: AsyncSession = Depends(get_db),
) -> ApplyResultResponse:
    """Apply a proposed change."""
    service = ProposedChangesService(db)

    scope_enum = None
    if scope:
        try:
            scope_enum = ChangeScope(scope)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid scope: {scope}")

    result = await service.apply(change_id, scope_override=scope_enum)
    return _apply_result_to_response(result)


@router.post("/{change_id}/undo", response_model=ApplyResultResponse)
async def undo_change(
    change_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ApplyResultResponse:
    """Undo an applied change (reverts database values)."""
    service = ProposedChangesService(db)
    result = await service.undo(change_id)
    return _apply_result_to_response(result)


@router.delete("/{change_id}")
async def delete_change(
    change_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Delete a proposed change."""
    service = ProposedChangesService(db)
    success = await service.delete(change_id)
    if not success:
        raise HTTPException(status_code=404, detail="Change not found")
    return {"status": "deleted"}


@router.post("/batch/apply", response_model=list[ApplyResultResponse])
async def batch_apply(
    request: BatchApplyRequest,
    db: AsyncSession = Depends(get_db),
) -> list[ApplyResultResponse]:
    """Apply multiple approved changes at once."""
    service = ProposedChangesService(db)

    scope_enum = None
    if request.scope:
        try:
            scope_enum = ChangeScope(request.scope)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid scope: {request.scope}")

    change_ids = []
    for change_id_str in request.change_ids:
        try:
            change_ids.append(UUID(change_id_str))
        except ValueError:
            continue  # Skip invalid UUIDs

    results = await service.apply_batch(change_ids, scope_override=scope_enum)
    return [_apply_result_to_response(r) for r in results]
