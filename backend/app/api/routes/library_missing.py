"""Missing tracks management endpoints."""

import logging
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.exceptions import InvalidPathError, TrackNotFoundError, ValidationError
from app.db.models import Track, TrackStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["library"])


class MissingTrack(BaseModel):
    """Missing track info for user review."""

    id: str
    title: str | None
    artist: str | None
    album: str | None
    file_path: str
    status: str  # "missing" or "pending_deletion"
    missing_since: str | None
    days_missing: int


class MissingTracksResponse(BaseModel):
    """List of missing tracks."""

    tracks: list[MissingTrack]
    total_missing: int
    total_pending_deletion: int


class RelocateRequest(BaseModel):
    """Request to search a folder for missing files."""

    search_path: str


class RelocateResult(BaseModel):
    """Result of batch relocation."""

    found: int
    not_found: int
    relocated_tracks: list[dict]


class LocateRequest(BaseModel):
    """Request to manually set new path for a track."""

    new_path: str


class LocateResponse(BaseModel):
    """Response from locating a missing track."""

    status: str
    track_id: str
    old_path: str
    new_path: str


class DeleteTrackResponse(BaseModel):
    """Response from deleting a missing track."""

    status: str
    track_id: str
    title: str


class BatchDeleteRequest(BaseModel):
    """Request to delete multiple tracks."""

    track_ids: list[str]


class BatchDeleteResponse(BaseModel):
    """Response from batch deleting missing tracks."""

    status: str
    deleted: int
    errors: list[str]


@router.get("/missing", response_model=MissingTracksResponse)
async def get_missing_tracks(db: DbSession) -> MissingTracksResponse:
    """Get all tracks with MISSING or PENDING_DELETION status."""
    from datetime import datetime

    result = await db.execute(
        select(Track).where(
            Track.status.in_([TrackStatus.MISSING, TrackStatus.PENDING_DELETION])
        ).order_by(Track.missing_since.desc())
    )
    tracks = result.scalars().all()

    now = datetime.now()
    missing_tracks = []
    total_missing = 0
    total_pending = 0

    for track in tracks:
        days_missing = 0
        if track.missing_since:
            days_missing = (now - track.missing_since).days

        if track.status == TrackStatus.MISSING:
            total_missing += 1
        else:
            total_pending += 1

        missing_tracks.append(
            MissingTrack(
                id=str(track.id),
                title=track.title,
                artist=track.artist,
                album=track.album,
                file_path=track.file_path,
                status=track.status.value,
                missing_since=track.missing_since.isoformat() if track.missing_since else None,
                days_missing=days_missing,
            )
        )

    return MissingTracksResponse(
        tracks=missing_tracks,
        total_missing=total_missing,
        total_pending_deletion=total_pending,
    )


@router.post("/missing/relocate", response_model=RelocateResult)
async def relocate_missing_tracks(
    db: DbSession,
    request: RelocateRequest,
) -> RelocateResult:
    """Search a folder for missing files and relocate them.

    Scans the provided path for audio files and matches them against
    missing tracks by filename. Successfully matched tracks are updated
    with the new path and marked as ACTIVE.
    """
    import os

    from app.config import AUDIO_EXTENSIONS

    search_path = Path(request.search_path)
    if not search_path.exists() or not search_path.is_dir():
        raise InvalidPathError("Search path does not exist or is not a directory")

    # Get all missing tracks
    result = await db.execute(
        select(Track).where(
            Track.status.in_([TrackStatus.MISSING, TrackStatus.PENDING_DELETION])
        )
    )
    missing_tracks = {Path(t.file_path).name.lower(): t for t in result.scalars().all()}

    if not missing_tracks:
        return RelocateResult(found=0, not_found=0, relocated_tracks=[])

    # Build map of filenames in search path
    audio_ext_lower = {ext.lower() for ext in AUDIO_EXTENSIONS}
    found_files: dict[str, Path] = {}

    for root, _, filenames in os.walk(search_path):
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext in audio_ext_lower:
                key = filename.lower()
                if key not in found_files:  # First occurrence wins
                    found_files[key] = Path(root) / filename

    # Match and relocate
    relocated = []
    for filename, track in missing_tracks.items():
        if filename in found_files:
            new_path = found_files[filename]
            track.file_path = str(new_path)
            track.status = TrackStatus.ACTIVE
            track.missing_since = None
            relocated.append({
                "id": str(track.id),
                "title": track.title,
                "old_path": track.file_path,
                "new_path": str(new_path),
            })

    await db.commit()

    return RelocateResult(
        found=len(relocated),
        not_found=len(missing_tracks) - len(relocated),
        relocated_tracks=relocated,
    )


@router.post("/missing/{track_id}/locate", response_model=LocateResponse)
async def locate_single_track(
    db: DbSession,
    track_id: str,
    request: LocateRequest,
) -> LocateResponse:
    """Manually set a new path for a missing track.

    Use this when you know exactly where the file has moved to.
    """
    from uuid import UUID

    new_path = Path(request.new_path)
    if not new_path.exists():
        raise InvalidPathError("File does not exist at specified path")
    if not new_path.is_file():
        raise InvalidPathError("Path is not a file")

    try:
        track_uuid = UUID(track_id)
    except ValueError:
        raise ValidationError("Invalid track ID")

    track = await db.get(Track, track_uuid)
    if not track:
        raise TrackNotFoundError()

    if track.status not in (TrackStatus.MISSING, TrackStatus.PENDING_DELETION):
        raise ValidationError("Track is not missing")

    old_path = track.file_path
    track.file_path = str(new_path)
    track.status = TrackStatus.ACTIVE
    track.missing_since = None

    await db.commit()

    return LocateResponse(
        status="relocated",
        track_id=track_id,
        old_path=old_path,
        new_path=str(new_path),
    )


@router.delete("/missing/{track_id}", response_model=DeleteTrackResponse)
async def delete_missing_track(
    db: DbSession,
    track_id: str,
) -> DeleteTrackResponse:
    """Permanently delete a missing track from the database.

    This is irreversible - the track and all its analysis data will be removed.
    """
    from uuid import UUID

    try:
        track_uuid = UUID(track_id)
    except ValueError:
        raise ValidationError("Invalid track ID")

    track = await db.get(Track, track_uuid)
    if not track:
        raise TrackNotFoundError()

    if track.status not in (TrackStatus.MISSING, TrackStatus.PENDING_DELETION):
        raise ValidationError("Track is not missing - cannot delete active tracks")

    title = track.title or Path(track.file_path).name
    await db.delete(track)
    await db.commit()

    return DeleteTrackResponse(
        status="deleted",
        track_id=track_id,
        title=title,
    )


@router.delete("/missing/batch", response_model=BatchDeleteResponse)
async def delete_missing_tracks_batch(
    db: DbSession,
    request: BatchDeleteRequest,
) -> BatchDeleteResponse:
    """Permanently delete multiple missing tracks from the database.

    This is irreversible - the tracks and all their analysis data will be removed.
    Only tracks with MISSING or PENDING_DELETION status can be deleted.
    """
    from uuid import UUID

    deleted = 0
    errors = []

    for track_id in request.track_ids:
        try:
            track_uuid = UUID(track_id)
            track = await db.get(Track, track_uuid)

            if not track:
                errors.append(f"{track_id}: not found")
                continue

            if track.status not in (TrackStatus.MISSING, TrackStatus.PENDING_DELETION):
                errors.append(f"{track_id}: not missing")
                continue

            await db.delete(track)
            deleted += 1

        except ValueError:
            errors.append(f"{track_id}: invalid ID")

    await db.commit()

    return BatchDeleteResponse(
        status="completed",
        deleted=deleted,
        errors=errors,
    )
