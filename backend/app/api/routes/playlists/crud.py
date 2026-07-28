"""Playlist CRUD endpoints (list, create, get, update, delete, duplicate)."""

from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import PlaylistNotFoundError
from app.db.models import Playlist, PlaylistTrack, ProfilePlayHistory, Track
from app.utils.time import to_rfc3339

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class PlaylistCreate(BaseModel):
    """Request to create a playlist."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    track_ids: list[str] = Field(default_factory=list)
    is_auto_generated: bool = False
    generation_prompt: str | None = None


class PlaylistUpdate(BaseModel):
    """Request to update a playlist."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    auto_download: bool | None = None


class TrackInPlaylist(BaseModel):
    """Track in a playlist response.

    Can be either a local track or an external (missing) track.
    """

    id: str  # The track_id
    playlist_track_id: str  # The PlaylistTrack.id (for reordering/removal)
    type: str  # "local" or "external"
    title: str | None
    artist: str | None
    album: str | None
    duration_seconds: float | None
    position: int

    # Full track fields (local tracks only)
    format: str | None = None
    year: int | None = None
    genre: str | None = None
    track_number: int | None = None
    disc_number: int | None = None
    album_artist: str | None = None
    album_type: str | None = None
    analysis_version: int | None = None
    last_played_at: str | None = None
    play_count: int | None = None


class PlaylistResponse(BaseModel):
    """Playlist response."""

    id: str
    name: str
    description: str | None
    is_auto_generated: bool
    generation_prompt: str | None
    track_count: int
    auto_download: bool = False
    created_at: str
    updated_at: str


class PlaylistDetailResponse(BaseModel):
    """Playlist detail response with tracks."""

    id: str
    name: str
    description: str | None
    is_auto_generated: bool
    generation_prompt: str | None
    tracks: list[TrackInPlaylist]
    auto_download: bool = False
    created_at: str
    updated_at: str


# ============================================================================
# Endpoints
# ============================================================================


async def list_playlists(
    db: DbSession,
    profile: RequiredProfile,
    include_auto: bool = Query(True, description="Include auto-generated playlists"),
) -> list[PlaylistResponse]:
    """List all playlists for the current profile."""
    query = select(Playlist).where(Playlist.profile_id == profile.id)

    if not include_auto:
        query = query.where(Playlist.is_auto_generated.is_(False))

    query = query.order_by(Playlist.updated_at.desc())

    result = await db.execute(query)
    playlists = result.scalars().all()

    # Batch all track counts in a single GROUP BY query instead of 2N queries
    playlist_ids = [p.id for p in playlists]
    counts: dict[UUID, tuple[int, int]] = {}
    if playlist_ids:
        count_result = await db.execute(
            select(
                PlaylistTrack.playlist_id,
                func.count(PlaylistTrack.id).label("total"),
                func.count(PlaylistTrack.track_id).label("local"),  # count() ignores NULLs
            )
            .where(PlaylistTrack.playlist_id.in_(playlist_ids))
            .group_by(PlaylistTrack.playlist_id)
        )
        for row in count_result.all():
            counts[row.playlist_id] = (row.total, row.local)

    responses = []
    for playlist in playlists:
        total_count, local_count = counts.get(playlist.id, (0, 0))

        responses.append(PlaylistResponse(
            id=str(playlist.id),
            name=playlist.name,
            description=playlist.description,
            is_auto_generated=playlist.is_auto_generated,
            generation_prompt=playlist.generation_prompt,
            track_count=total_count,
            auto_download=playlist.auto_download,
            created_at=to_rfc3339(playlist.created_at),
            updated_at=to_rfc3339(playlist.updated_at),
        ))

    return responses


async def create_playlist(
    request: PlaylistCreate,
    db: DbSession,
    profile: RequiredProfile,
) -> PlaylistDetailResponse:
    """Create a new playlist with optional tracks."""
    # Create the playlist
    playlist = Playlist(
        profile_id=profile.id,
        name=request.name,
        description=request.description,
        is_auto_generated=request.is_auto_generated,
        generation_prompt=request.generation_prompt,
    )
    db.add(playlist)
    await db.flush()  # Get the playlist ID

    # Add tracks if provided — batch-fetch all tracks in one query
    tracks_added = []
    valid_track_ids = []
    for track_id_str in request.track_ids:
        try:
            valid_track_ids.append(UUID(track_id_str))
        except ValueError:
            continue

    tracks_by_id: dict[UUID, Track] = {}
    if valid_track_ids:
        result = await db.execute(
            select(Track)
            .where(Track.id.in_(valid_track_ids))
            .options(selectinload(Track.analyses))
        )
        tracks_by_id = {t.id: t for t in result.scalars().all()}

    for position, track_id in enumerate(valid_track_ids):
        track = tracks_by_id.get(track_id)
        if not track:
            continue

        playlist_track = PlaylistTrack(
            playlist_id=playlist.id,
            track_id=track_id,
            position=position,
        )
        db.add(playlist_track)
        tracks_added.append(TrackInPlaylist(
            id=str(track.id),
            playlist_track_id=str(playlist_track.id),
            type="local",
            title=track.title,
            artist=track.artist,
            album=track.album,
            duration_seconds=track.duration_seconds,
            position=position,
            format=track.format,
            year=track.year,
            genre=track.genre,
            track_number=track.track_number,
            disc_number=track.disc_number,
            album_artist=track.album_artist,
            album_type=track.album_type.value if track.album_type else None,
            analysis_version=track.analysis_version,
        ))

    await db.commit()
    await db.refresh(playlist)

    return PlaylistDetailResponse(
        id=str(playlist.id),
        name=playlist.name,
        description=playlist.description,
        is_auto_generated=playlist.is_auto_generated,
        generation_prompt=playlist.generation_prompt,
        tracks=tracks_added,
        auto_download=playlist.auto_download,
        created_at=to_rfc3339(playlist.created_at),
        updated_at=to_rfc3339(playlist.updated_at),
    )


@router.get("/{playlist_id}", response_model=PlaylistDetailResponse)
async def get_playlist(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> PlaylistDetailResponse:
    """Get a playlist by ID with its tracks.

    Returns both local and external tracks mixed together by position.
    """
    playlist = await db.get(Playlist, playlist_id)

    if not playlist or playlist.profile_id != profile.id:
        raise PlaylistNotFoundError()

    result = await db.execute(
        select(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .order_by(PlaylistTrack.position)
        .options(
            selectinload(PlaylistTrack.track).selectinload(Track.analyses),
        )
    )
    playlist_tracks = result.scalars().all()

    # Fetch play history for all tracks in the playlist
    local_track_ids = [pt.track.id for pt in playlist_tracks if pt.track]
    play_history_map = {}
    if local_track_ids:
        ph_result = await db.execute(
            select(ProfilePlayHistory).where(
                ProfilePlayHistory.profile_id == profile.id,
                ProfilePlayHistory.track_id.in_(local_track_ids),
            )
        )
        play_history_map = {ph.track_id: ph for ph in ph_result.scalars().all()}

    tracks = []
    for pt in playlist_tracks:
        if pt.track:
            ph = play_history_map.get(pt.track.id)
            tracks.append(TrackInPlaylist(
                id=str(pt.track.id),
                playlist_track_id=str(pt.id),
                type="local",
                title=pt.track.title,
                artist=pt.track.artist,
                album=pt.track.album,
                duration_seconds=pt.track.duration_seconds,
                position=pt.position,
                format=pt.track.format,
                year=pt.track.year,
                genre=pt.track.genre,
                track_number=pt.track.track_number,
                disc_number=pt.track.disc_number,
                album_artist=pt.track.album_artist,
                album_type=pt.track.album_type.value if pt.track.album_type else None,
                analysis_version=pt.track.analysis_version,
                last_played_at=to_rfc3339(ph.last_played_at) if ph and ph.last_played_at else None,
                play_count=ph.play_count if ph else None,
            ))

    return PlaylistDetailResponse(
        id=str(playlist.id),
        name=playlist.name,
        description=playlist.description,
        is_auto_generated=playlist.is_auto_generated,
        generation_prompt=playlist.generation_prompt,
        tracks=tracks,
        auto_download=playlist.auto_download,
        created_at=to_rfc3339(playlist.created_at),
        updated_at=to_rfc3339(playlist.updated_at),
    )


@router.put("/{playlist_id}", response_model=PlaylistResponse)
async def update_playlist(
    playlist_id: UUID,
    request: PlaylistUpdate,
    db: DbSession,
    profile: RequiredProfile,
) -> PlaylistResponse:
    """Update a playlist's name or description."""
    playlist = await db.get(Playlist, playlist_id)

    if not playlist or playlist.profile_id != profile.id:
        raise PlaylistNotFoundError()

    if request.name is not None:
        playlist.name = request.name
    if request.description is not None:
        playlist.description = request.description
    if request.auto_download is not None:
        playlist.auto_download = request.auto_download

    await db.commit()
    await db.refresh(playlist)

    track_count = await db.scalar(
        select(func.count(PlaylistTrack.id)).where(
            PlaylistTrack.playlist_id == playlist.id
        )
    ) or 0

    return PlaylistResponse(
        id=str(playlist.id),
        name=playlist.name,
        description=playlist.description,
        is_auto_generated=playlist.is_auto_generated,
        generation_prompt=playlist.generation_prompt,
        track_count=track_count,
        auto_download=playlist.auto_download,
        created_at=to_rfc3339(playlist.created_at),
        updated_at=to_rfc3339(playlist.updated_at),
    )


@router.delete("/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_playlist(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> None:
    """Delete a playlist."""
    playlist = await db.get(Playlist, playlist_id)

    if not playlist or playlist.profile_id != profile.id:
        raise PlaylistNotFoundError()

    # Delete playlist tracks first (cascade should handle this, but be explicit)
    from sqlalchemy import delete
    await db.execute(
        delete(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)
    )

    await db.delete(playlist)
    await db.commit()


@router.post("/{playlist_id}/duplicate", response_model=PlaylistDetailResponse, status_code=status.HTTP_201_CREATED)
async def duplicate_playlist(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> PlaylistDetailResponse:
    """Duplicate a playlist with all its tracks."""
    playlist = await db.get(Playlist, playlist_id)

    if not playlist or playlist.profile_id != profile.id:
        raise PlaylistNotFoundError()

    # Create a copy
    new_playlist = Playlist(
        profile_id=profile.id,
        name=f"{playlist.name} (Copy)",
        description=playlist.description,
        is_auto_generated=playlist.is_auto_generated,
        generation_prompt=playlist.generation_prompt,
    )
    db.add(new_playlist)
    await db.flush()

    # Copy all playlist tracks
    result = await db.execute(
        select(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .order_by(PlaylistTrack.position)
    )
    original_tracks = result.scalars().all()

    for pt in original_tracks:
        if not pt.track_id:
            continue
        new_pt = PlaylistTrack(
            playlist_id=new_playlist.id,
            track_id=pt.track_id,
            position=pt.position,
        )
        db.add(new_pt)

    await db.commit()

    return await get_playlist(new_playlist.id, db, profile)
