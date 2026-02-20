"""ZIP download endpoints for playlists and track collections."""

import asyncio
import os
import re
import zipfile
from io import BytesIO
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, RequiredProfile
from app.db.models import Playlist, PlaylistTrack, SmartPlaylist, Track
from app.services.smart_playlists import SmartPlaylistService

router = APIRouter(prefix="/download", tags=["download"])

MAX_TRACKS = 500
MAX_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2GB


def _sanitize_filename(name: str) -> str:
    """Remove characters that are problematic in filenames."""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip('. ')


def _build_zip_bytes(tracks: list[Track], folder_name: str) -> tuple[bytes, int]:
    """Build a ZIP file in memory from a list of tracks.

    Returns (zip_bytes, skipped_count).
    """
    buf = BytesIO()
    skipped = 0
    safe_folder = _sanitize_filename(folder_name)

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as zf:
        for track in tracks:
            if not track.file_path or not os.path.isfile(track.file_path):
                skipped += 1
                continue

            # Build a clean filename: "01 Artist - Title.ext"
            ext = os.path.splitext(track.file_path)[1]
            num = f"{track.track_number:02d}" if track.track_number else "00"
            artist = _sanitize_filename(track.artist or "Unknown")
            title = _sanitize_filename(track.title or "Unknown")
            filename = f"{num} {artist} - {title}{ext}"

            arcname = f"{safe_folder}/{filename}"
            zf.write(track.file_path, arcname)

    return buf.getvalue(), skipped


async def _get_playlist_tracks(db: DbSession, playlist_id: UUID, profile_id: UUID) -> tuple[list[Track], str]:
    """Get tracks and name for a playlist."""
    playlist = await db.get(Playlist, playlist_id)
    if not playlist or playlist.profile_id != profile_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    result = await db.execute(
        select(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .order_by(PlaylistTrack.position)
        .options(selectinload(PlaylistTrack.track))
    )
    playlist_tracks = result.scalars().all()
    tracks = [pt.track for pt in playlist_tracks if pt.track_id and pt.track]
    return tracks, playlist.name


def _check_limits(tracks: list[Track]) -> None:
    """Raise 413 if track list exceeds limits."""
    if len(tracks) > MAX_TRACKS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Too many tracks ({len(tracks)}). Maximum is {MAX_TRACKS}.",
        )

    estimated_size = sum(t.file_size or 0 for t in tracks)
    if estimated_size > MAX_SIZE_BYTES:
        size_gb = estimated_size / (1024 * 1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Estimated size ({size_gb:.1f} GB) exceeds 2 GB limit.",
        )


@router.get("/playlist/{playlist_id}")
async def download_playlist_zip(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> StreamingResponse:
    """Download all tracks in a playlist as a ZIP file."""
    tracks, name = await _get_playlist_tracks(db, playlist_id, profile.id)

    if not tracks:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No downloadable tracks in playlist")

    _check_limits(tracks)

    zip_bytes, skipped = await asyncio.to_thread(_build_zip_bytes, tracks, name)

    safe_name = _sanitize_filename(name)
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}.zip"',
    }
    if skipped > 0:
        headers["X-Skipped-Tracks"] = str(skipped)

    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers=headers,
    )


@router.get("/smart-playlist/{playlist_id}")
async def download_smart_playlist_zip(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> StreamingResponse:
    """Download all tracks matching a smart playlist as a ZIP file."""
    service = SmartPlaylistService(db)
    playlist = await service.get_by_id(playlist_id, profile.id)

    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Smart playlist not found")

    raw_tracks, _total = await service.get_tracks_unified(playlist, limit=MAX_TRACKS + 1, offset=0)
    # Filter to local Track objects only
    tracks = [t for t in raw_tracks if isinstance(t, Track)]

    if not tracks:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No downloadable tracks in smart playlist")

    _check_limits(tracks)

    zip_bytes, skipped = await asyncio.to_thread(_build_zip_bytes, tracks, playlist.name)

    safe_name = _sanitize_filename(playlist.name)
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}.zip"',
    }
    if skipped > 0:
        headers["X-Skipped-Tracks"] = str(skipped)

    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers=headers,
    )


class TrackDownloadRequest(BaseModel):
    """Request to download arbitrary tracks as ZIP."""

    track_ids: list[str] = Field(..., min_length=1)
    name: str = Field(default="Tracks", max_length=255)


@router.post("/tracks")
async def download_tracks_zip(
    request: TrackDownloadRequest,
    db: DbSession,
    profile: RequiredProfile,
) -> StreamingResponse:
    """Download a set of tracks as a ZIP file."""
    track_uuids = []
    for tid in request.track_ids:
        try:
            track_uuids.append(UUID(tid))
        except ValueError:
            continue

    if not track_uuids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid track IDs provided")

    result = await db.execute(
        select(Track).where(Track.id.in_(track_uuids))
    )
    tracks = list(result.scalars().all())

    if not tracks:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No tracks found")

    _check_limits(tracks)

    zip_bytes, skipped = await asyncio.to_thread(_build_zip_bytes, tracks, request.name)

    safe_name = _sanitize_filename(request.name)
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}.zip"',
    }
    if skipped > 0:
        headers["X-Skipped-Tracks"] = str(skipped)

    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers=headers,
    )
