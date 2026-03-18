"""Library organization API routes."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.exceptions import TrackNotFoundError
from app.services.organizer import (
    TEMPLATES,
    LibraryOrganizer,
    OrganizeResult,
    OrganizeStats,
    get_available_templates,
)

router = APIRouter(prefix="/library/organize", tags=["Library Organization"])


class TemplateInfo(BaseModel):
    """Template information."""
    name: str
    template: str
    example: str


class TemplatesResponse(BaseModel):
    """Available templates response."""
    templates: list[TemplateInfo]


class PreviewRequest(BaseModel):
    """Preview organization request."""
    template: str = TEMPLATES["artist-album"]
    limit: int = 100


class OrganizeRequest(BaseModel):
    """Organization request."""
    template: str = TEMPLATES["artist-album"]
    dry_run: bool = True


class OrganizeTrackRequest(BaseModel):
    """Single track organization request."""
    template: str = TEMPLATES["artist-album"]
    dry_run: bool = False


class OrganizeResultResponse(BaseModel):
    """Single track result."""
    track_id: str
    old_path: str
    new_path: str | None
    status: Literal["moved", "skipped", "error"]
    message: str


class OrganizeStatsResponse(BaseModel):
    """Organization stats response."""
    total: int
    moved: int
    skipped: int
    errors: int
    results: list[OrganizeResultResponse]


def _result_to_response(result: OrganizeResult) -> OrganizeResultResponse:
    """Convert OrganizeResult to response model."""
    return OrganizeResultResponse(
        track_id=str(result.track_id),
        old_path=result.old_path,
        new_path=result.new_path,
        status=result.status,
        message=result.message,
    )


def _stats_to_response(stats: OrganizeStats) -> OrganizeStatsResponse:
    """Convert OrganizeStats to response model."""
    return OrganizeStatsResponse(
        total=stats.total,
        moved=stats.moved,
        skipped=stats.skipped,
        errors=stats.errors,
        results=[_result_to_response(r) for r in stats.results],
    )


@router.get("/templates", response_model=TemplatesResponse)
async def list_templates() -> TemplatesResponse:
    """List available organization templates."""
    templates = get_available_templates()

    # Generate examples
    examples = {
        "artist-album": "Pink Floyd/The Dark Side of the Moon/01 - Speak to Me.flac",
        "artist-album-disc": "Pink Floyd/The Wall/Disc 1/01 - In the Flesh.flac",
        "genre-artist-album": "Rock/Pink Floyd/The Dark Side of the Moon/01 - Speak to Me.flac",
        "year-artist-album": "1973/Pink Floyd/The Dark Side of the Moon/01 - Speak to Me.flac",
        "flat": "Pink Floyd - The Dark Side of the Moon - 01 - Speak to Me.flac",
    }

    return TemplatesResponse(
        templates=[
            TemplateInfo(name=name, template=template, example=examples.get(name, ""))
            for name, template in templates.items()
        ]
    )


@router.post("/preview", response_model=OrganizeStatsResponse)
async def preview_organization(
    request: PreviewRequest,
    db: AsyncSession = Depends(get_db),
) -> OrganizeStatsResponse:
    """Preview what organization would do without moving files.

    Returns a list of tracks and their proposed new paths.
    Limited to first N tracks for performance.
    """
    organizer = LibraryOrganizer(db)
    stats = await organizer.preview_all(
        template=request.template,
        limit=request.limit,
    )
    return _stats_to_response(stats)


@router.post("/run", response_model=OrganizeStatsResponse)
async def run_organization(
    request: OrganizeRequest,
    db: AsyncSession = Depends(get_db),
) -> OrganizeStatsResponse:
    """Organize library files according to template.

    Set dry_run=true to preview without moving files.
    This operation moves files and updates the database.
    """
    organizer = LibraryOrganizer(db)
    stats = await organizer.organize_all(
        template=request.template,
        dry_run=request.dry_run,
    )
    return _stats_to_response(stats)


@router.post("/track/{track_id}", response_model=OrganizeResultResponse)
async def organize_track(
    track_id: UUID,
    request: OrganizeTrackRequest,
    db: AsyncSession = Depends(get_db),
) -> OrganizeResultResponse:
    """Organize a single track."""
    organizer = LibraryOrganizer(db)
    result = await organizer.organize_track(
        track_id=track_id,
        template=request.template,
        dry_run=request.dry_run,
    )

    if result.status == "error" and result.message == "Track not found":
        raise TrackNotFoundError()

    return _result_to_response(result)


@router.get("/track/{track_id}/preview", response_model=OrganizeResultResponse)
async def preview_track(
    track_id: UUID,
    template: str = TEMPLATES["artist-album"],
    db: AsyncSession = Depends(get_db),
) -> OrganizeResultResponse:
    """Preview organization for a single track."""
    organizer = LibraryOrganizer(db)
    result = await organizer.preview_track(track_id, template)

    if result.status == "error" and result.message == "Track not found":
        raise TrackNotFoundError()

    return _result_to_response(result)
