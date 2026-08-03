"""Mix Tape API: create renders, poll status, download bundles."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any
from uuid import UUID

from fastapi import APIRouter, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.api.schemas.common import UTCDateTime
from app.config import settings
from app.db.models import MixTape, Playlist, PlaylistTrack
from app.services.mixtape_export import (
    MAX_TRACKS,
    MIN_TRACKS,
    _redis_key,
    run_mixtape_export,
)
from app.services.smart_playlists import SmartPlaylistService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mixtapes", tags=["mixtapes"])


# ── Request/response schemas ────────────────────────────────────────────────


class MixTapeCreateRequest(BaseModel):
    """Request body for kicking off a mixtape render."""

    name: str = Field(..., min_length=1, max_length=64)
    source_playlist_id: UUID | None = None
    source_smart_playlist_id: UUID | None = None
    crossfade_seconds: int | None = Field(default=None, ge=1, le=10)
    byline: str | None = Field(default=None, max_length=32)


class MixTapeResponse(BaseModel):
    id: UUID
    name: str
    byline: str | None
    source_playlist_id: UUID | None
    source_smart_playlist_id: UUID | None
    track_ids: list[str]
    crossfade_seconds: int | None
    status: str
    error_message: str | None
    duration_seconds: float | None
    file_size_bytes: int | None
    created_at: UTCDateTime
    completed_at: UTCDateTime | None
    progress: dict[str, Any] | None = None


def _serialize(mt: MixTape, progress: dict[str, Any] | None = None) -> MixTapeResponse:
    return MixTapeResponse(
        id=mt.id,
        name=mt.name,
        byline=mt.byline,
        source_playlist_id=mt.source_playlist_id,
        source_smart_playlist_id=mt.source_smart_playlist_id,
        track_ids=list(mt.track_ids or []),
        crossfade_seconds=mt.crossfade_seconds,
        status=mt.status,
        error_message=mt.error_message,
        duration_seconds=mt.duration_seconds,
        file_size_bytes=mt.file_size_bytes,
        created_at=mt.created_at if mt.created_at else "",
        completed_at=mt.completed_at if mt.completed_at else None,
        progress=progress,
    )


# ── Routes ──────────────────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_mixtape(
    request: MixTapeCreateRequest,
    db: DbSession,
    profile: RequiredProfile,
) -> MixTapeResponse:
    """Create a mixtape and kick off the background render."""
    if bool(request.source_playlist_id) == bool(request.source_smart_playlist_id):
        raise ValidationError("Specify exactly one of source_playlist_id or source_smart_playlist_id")

    # Verify source ownership and pre-flight track count.
    if request.source_playlist_id:
        playlist = await db.get(Playlist, request.source_playlist_id)
        if not playlist or playlist.profile_id != profile.id:
            raise NotFoundError("Playlist not found")
        count_q = await db.execute(
            select(PlaylistTrack).where(PlaylistTrack.playlist_id == request.source_playlist_id)
        )
        track_count = len(count_q.scalars().all())
    else:
        service = SmartPlaylistService(db)
        smart = await service.get_by_id(request.source_smart_playlist_id, profile.id)  # type: ignore[arg-type]
        if not smart:
            raise NotFoundError("Smart playlist not found")
        track_count = await service.get_track_count(smart)

    if track_count < MIN_TRACKS:
        raise ValidationError(f"Need at least {MIN_TRACKS} tracks (got {track_count})")
    # Note: smart playlists can have more than MAX_TRACKS — we'll truncate at render time.
    if request.source_playlist_id and track_count > MAX_TRACKS:
        raise ValidationError(f"Playlist has {track_count} tracks; max is {MAX_TRACKS}")

    # One render per profile at a time.
    in_flight = await db.execute(
        select(MixTape).where(
            MixTape.profile_id == profile.id,
            MixTape.status.in_(("pending", "rendering")),
        )
    )
    if in_flight.scalars().first():
        raise ConflictError("Another mixtape is already rendering — wait for it to finish")

    # Empty-string byline is treated as None — the modal sends null but
    # be tolerant of clients that send "".
    byline = request.byline.strip() if request.byline else None
    mixtape = MixTape(
        profile_id=profile.id,
        name=request.name,
        byline=byline or None,
        source_playlist_id=request.source_playlist_id,
        source_smart_playlist_id=request.source_smart_playlist_id,
        track_ids=[],
        crossfade_seconds=request.crossfade_seconds,
        status="pending",
    )
    db.add(mixtape)
    await db.commit()
    await db.refresh(mixtape)

    asyncio.create_task(run_mixtape_export(mixtape.id))
    return _serialize(mixtape)


@router.get("")
async def list_mixtapes(
    db: DbSession,
    profile: RequiredProfile,
) -> list[MixTapeResponse]:
    """List the current profile's mixtapes, newest first.

    For rows that are still pending/rendering, merges live phase + progress
    from Redis so the header indicator can render phase labels without
    polling each id individually.
    """
    result = await db.execute(
        select(MixTape)
        .where(MixTape.profile_id == profile.id)
        .order_by(MixTape.created_at.desc())
    )
    rows = list(result.scalars().all())

    in_flight_ids = [mt.id for mt in rows if mt.status in ("pending", "rendering")]
    progress_by_id: dict[UUID, dict[str, Any]] = {}
    if in_flight_ids:
        from app.services.background import get_background_manager
        bg = get_background_manager()
        for mt_id in in_flight_ids:
            raw = bg.redis.get(_redis_key(mt_id))
            if not raw:
                continue
            try:
                progress_by_id[mt_id] = json.loads(
                    raw.decode() if isinstance(raw, bytes) else raw
                )
            except json.JSONDecodeError:
                continue

    return [_serialize(mt, progress=progress_by_id.get(mt.id)) for mt in rows]


@router.get("/{mixtape_id}")
async def get_mixtape(
    mixtape_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> MixTapeResponse:
    """Fetch one mixtape, merging persisted state with live Redis progress."""
    mixtape = await db.get(MixTape, mixtape_id)
    if not mixtape or mixtape.profile_id != profile.id:
        raise NotFoundError("Mixtape not found")

    progress: dict[str, Any] | None = None
    if mixtape.status in ("pending", "rendering"):
        from app.services.background import get_background_manager
        bg = get_background_manager()
        raw = bg.redis.get(_redis_key(mixtape_id))
        if raw:
            try:
                progress = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            except json.JSONDecodeError:
                progress = None

    return _serialize(mixtape, progress=progress)


@router.get(
    "/{mixtape_id}/download",
    response_class=FileResponse,
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "Mixtape bundle: audio, cover image and tracklist.",
        }
    },
)
async def download_mixtape(
    mixtape_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> FileResponse:
    """Stream the bundled ZIP once status is 'ready'."""
    mixtape = await db.get(MixTape, mixtape_id)
    if not mixtape or mixtape.profile_id != profile.id:
        raise NotFoundError("Mixtape not found")
    if mixtape.status != "ready" or not mixtape.bundle_path:
        raise ConflictError(f"Mixtape not ready (status: {mixtape.status})")
    if not os.path.isfile(mixtape.bundle_path):
        raise NotFoundError("Bundle file missing on disk")

    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in mixtape.name).strip() or "Mixtape"
    return FileResponse(
        path=mixtape.bundle_path,
        media_type="application/zip",
        filename=f"{safe}.zip",
    )


@router.delete("/{mixtape_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mixtape(
    mixtape_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> JSONResponse:
    """Delete a mixtape row and its on-disk artifacts."""
    mixtape = await db.get(MixTape, mixtape_id)
    if not mixtape or mixtape.profile_id != profile.id:
        raise NotFoundError("Mixtape not found")
    if mixtape.status in ("pending", "rendering"):
        raise ConflictError("Cannot delete a mixtape that's currently rendering")

    workdir = settings.mixtapes_path / str(mixtape_id)
    if workdir.is_dir():
        for child in workdir.iterdir():
            try:
                child.unlink()
            except Exception as e:  # pragma: no cover
                logger.warning("Failed to remove %s: %s", child, e)
        try:
            workdir.rmdir()
        except OSError:
            pass

    await db.delete(mixtape)
    await db.commit()
    return JSONResponse(status_code=204, content=None)
