"""Playlist track management endpoints (add, reorder, remove)."""

from uuid import UUID

from fastapi import APIRouter, Body, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import PlaylistNotFoundError
from app.api.routes.playlists.crud import PlaylistDetailResponse, get_playlist
from app.db.models import Playlist, PlaylistTrack, Track

router = APIRouter()


class ReorderTracksRequest(BaseModel):
    """Request to reorder tracks in a playlist."""

    track_ids: list[str] = Field(default=[], description="Track IDs in the new order (deprecated)")
    playlist_track_ids: list[str] = Field(default=[], description="PlaylistTrack IDs in the new order")


@router.post("/{playlist_id}/tracks", response_model=PlaylistDetailResponse)
async def add_tracks_to_playlist(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
    track_ids: list[str] = Body(...),
) -> PlaylistDetailResponse:
    """Add tracks to an existing playlist."""
    playlist = await db.get(Playlist, playlist_id)

    if not playlist or playlist.profile_id != profile.id:
        raise PlaylistNotFoundError()

    # Get current max position
    result = await db.execute(
        select(func.max(PlaylistTrack.position)).where(
            PlaylistTrack.playlist_id == playlist_id
        )
    )
    max_position = result.scalar() or -1

    # Batch-fetch all candidate tracks and existing playlist memberships
    valid_track_ids = []
    for track_id_str in track_ids:
        try:
            valid_track_ids.append(UUID(track_id_str))
        except ValueError:
            continue

    existing_track_ids: set[UUID] = set()
    tracks_by_id: dict[UUID, Track] = {}
    if valid_track_ids:
        # Fetch existing tracks in one query
        tracks_result = await db.execute(
            select(Track).where(Track.id.in_(valid_track_ids))
        )
        tracks_by_id = {t.id: t for t in tracks_result.scalars().all()}

        # Check which are already in the playlist
        existing_result = await db.execute(
            select(PlaylistTrack.track_id).where(
                PlaylistTrack.playlist_id == playlist_id,
                PlaylistTrack.track_id.in_(valid_track_ids),
            )
        )
        existing_track_ids = {row[0] for row in existing_result.all() if row[0]}

    # Add new tracks
    for i, track_id in enumerate(valid_track_ids):
        if track_id not in tracks_by_id:
            continue
        if track_id in existing_track_ids:
            continue

        playlist_track = PlaylistTrack(
            playlist_id=playlist.id,
            track_id=track_id,
            position=max_position + 1 + i,
        )
        db.add(playlist_track)

    await db.commit()

    # Return updated playlist
    return await get_playlist(playlist_id, db, profile)


@router.put("/{playlist_id}/tracks/reorder", response_model=PlaylistDetailResponse)
async def reorder_playlist_tracks(
    playlist_id: UUID,
    request: ReorderTracksRequest,
    db: DbSession,
    profile: RequiredProfile,
) -> PlaylistDetailResponse:
    """Reorder tracks in a playlist.

    Use playlist_track_ids (preferred) - the PlaylistTrack.id values.
    Falls back to track_ids for backwards compatibility (local tracks only).
    """
    playlist = await db.get(Playlist, playlist_id)

    if not playlist or playlist.profile_id != profile.id:
        raise PlaylistNotFoundError()

    # Prefer playlist_track_ids if provided
    if request.playlist_track_ids:
        # Get current playlist track IDs
        result = await db.execute(
            select(PlaylistTrack.id).where(PlaylistTrack.playlist_id == playlist_id)
        )
        current_pt_ids = {str(row[0]) for row in result.all()}

        # Update positions for each playlist track
        for position, pt_id_str in enumerate(request.playlist_track_ids):
            if pt_id_str not in current_pt_ids:
                continue
            try:
                pt_id = UUID(pt_id_str)
            except ValueError:
                continue

            await db.execute(
                update(PlaylistTrack)
                .where(PlaylistTrack.id == pt_id)
                .values(position=position)
            )
    elif request.track_ids:
        # Backwards compatibility: use track_ids (local tracks only)
        result = await db.execute(
            select(PlaylistTrack.track_id).where(
                PlaylistTrack.playlist_id == playlist_id,
                PlaylistTrack.track_id.isnot(None),
            )
        )
        current_track_ids = {str(row[0]) for row in result.all() if row[0]}

        for position, track_id_str in enumerate(request.track_ids):
            if track_id_str not in current_track_ids:
                continue
            try:
                track_id = UUID(track_id_str)
            except ValueError:
                continue

            await db.execute(
                update(PlaylistTrack)
                .where(
                    PlaylistTrack.playlist_id == playlist_id,
                    PlaylistTrack.track_id == track_id,
                )
                .values(position=position)
            )

    await db.commit()

    # Return updated playlist
    return await get_playlist(playlist_id, db, profile)


@router.delete("/{playlist_id}/tracks/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_track_from_playlist(
    playlist_id: UUID,
    track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> None:
    """Remove a track from a playlist by track_id.

    For backwards compatibility. Use DELETE /playlists/{id}/items/{playlist_track_id}
    for explicit removal of playlist items (handles both local and external tracks).
    """
    playlist = await db.get(Playlist, playlist_id)

    if not playlist or playlist.profile_id != profile.id:
        raise PlaylistNotFoundError()

    await db.execute(
        delete(PlaylistTrack).where(
            PlaylistTrack.playlist_id == playlist_id,
            PlaylistTrack.track_id == track_id,
        )
    )
    await db.commit()


@router.delete("/{playlist_id}/items/{playlist_track_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_playlist_item(
    playlist_id: UUID,
    playlist_track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> None:
    """Remove an item from a playlist by its playlist_track_id.

    Works for both local tracks and external tracks.
    """
    playlist = await db.get(Playlist, playlist_id)

    if not playlist or playlist.profile_id != profile.id:
        raise PlaylistNotFoundError()

    await db.execute(
        delete(PlaylistTrack).where(
            PlaylistTrack.id == playlist_track_id,
            PlaylistTrack.playlist_id == playlist_id,
        )
    )
    await db.commit()
