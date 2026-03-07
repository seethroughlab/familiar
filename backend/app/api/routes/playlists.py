"""Playlist management endpoints."""

from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, RequiredProfile
from app.db.models import Playlist, PlaylistTrack, Track
from app.services.recommendations import RecommendationsService

router = APIRouter(prefix="/playlists", tags=["playlists"])


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


@router.get("", response_model=list[PlaylistResponse])
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
            created_at=playlist.created_at.isoformat(),
            updated_at=playlist.updated_at.isoformat(),
        ))

    return responses


@router.post("", response_model=PlaylistDetailResponse, status_code=status.HTTP_201_CREATED)
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

    # Add tracks if provided
    tracks_added = []
    for position, track_id_str in enumerate(request.track_ids):
        try:
            track_id = UUID(track_id_str)
        except ValueError:
            continue

        # Verify track exists (load analyses for analysis_version property)
        track = await db.get(Track, track_id, options=[selectinload(Track.analyses)])
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
        created_at=playlist.created_at.isoformat(),
        updated_at=playlist.updated_at.isoformat(),
    )


# ============================================================================
# Playlist CRUD by ID
# ============================================================================


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        )

    result = await db.execute(
        select(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .order_by(PlaylistTrack.position)
        .options(
            selectinload(PlaylistTrack.track).selectinload(Track.analyses),
        )
    )
    playlist_tracks = result.scalars().all()

    tracks = []
    for pt in playlist_tracks:
        if pt.track:
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
            ))

    return PlaylistDetailResponse(
        id=str(playlist.id),
        name=playlist.name,
        description=playlist.description,
        is_auto_generated=playlist.is_auto_generated,
        generation_prompt=playlist.generation_prompt,
        tracks=tracks,
        auto_download=playlist.auto_download,
        created_at=playlist.created_at.isoformat(),
        updated_at=playlist.updated_at.isoformat(),
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        )

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
        created_at=playlist.created_at.isoformat(),
        updated_at=playlist.updated_at.isoformat(),
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        )

    # Delete playlist tracks first (cascade should handle this, but be explicit)
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        )

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        )

    # Get current max position
    result = await db.execute(
        select(func.max(PlaylistTrack.position)).where(
            PlaylistTrack.playlist_id == playlist_id
        )
    )
    max_position = result.scalar() or -1

    # Add new tracks
    for i, track_id_str in enumerate(track_ids):
        try:
            track_id = UUID(track_id_str)
        except ValueError:
            continue

        # Verify track exists
        track = await db.get(Track, track_id)
        if not track:
            continue

        # Check if already in playlist
        existing = await db.execute(
            select(PlaylistTrack).where(
                PlaylistTrack.playlist_id == playlist_id,
                PlaylistTrack.track_id == track_id,
            )
        )
        if existing.scalar_one_or_none():
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


class ReorderTracksRequest(BaseModel):
    """Request to reorder tracks in a playlist."""

    track_ids: list[str] = Field(default=[], description="Track IDs in the new order (deprecated)")
    playlist_track_ids: list[str] = Field(default=[], description="PlaylistTrack IDs in the new order")


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        )

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        )

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        )

    await db.execute(
        delete(PlaylistTrack).where(
            PlaylistTrack.id == playlist_track_id,
            PlaylistTrack.playlist_id == playlist_id,
        )
    )
    await db.commit()


class RecommendedArtistResponse(BaseModel):
    """A recommended artist."""

    name: str
    source: str
    match_score: float
    image_url: str | None
    external_url: str | None
    local_track_count: int


class RecommendedTrackResponse(BaseModel):
    """A recommended track."""

    title: str
    artist: str
    source: str
    match_score: float
    external_url: str | None
    local_track_id: str | None
    album: str | None = None


class RecommendationsResponse(BaseModel):
    """Recommendations response."""

    artists: list[RecommendedArtistResponse]
    tracks: list[RecommendedTrackResponse]
    sources_used: list[str]


@router.get("/{playlist_id}/recommendations", response_model=RecommendationsResponse)
async def get_playlist_recommendations(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
    artist_limit: int = Query(10, ge=1, le=50),
    track_limit: int = Query(10, ge=1, le=50),
) -> RecommendationsResponse:
    """Get recommendations based on a playlist's content.

    Only available for auto-generated (AI) playlists.
    Uses Last.fm for similar artists/tracks, with Bandcamp as fallback.
    """
    playlist = await db.get(Playlist, playlist_id)

    if not playlist or playlist.profile_id != profile.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        )

    if not playlist.is_auto_generated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recommendations only available for AI-generated playlists",
        )

    service = RecommendationsService(db)
    try:
        recs = await service.get_playlist_recommendations(
            playlist_id, artist_limit, track_limit
        )

        return RecommendationsResponse(
            artists=[
                RecommendedArtistResponse(
                    name=a.name,
                    source=a.source,
                    match_score=a.match_score,
                    image_url=a.image_url,
                    external_url=a.external_url,
                    local_track_count=a.local_track_count,
                )
                for a in recs.artists
            ],
            tracks=[
                RecommendedTrackResponse(
                    title=t.title,
                    artist=t.artist,
                    source=t.source,
                    match_score=t.match_score,
                    external_url=t.external_url,
                    local_track_id=t.local_track_id,
                    album=t.album,
                )
                for t in recs.tracks
            ],
            sources_used=recs.sources_used,
        )
    finally:
        await service.close()
