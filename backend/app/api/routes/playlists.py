"""Playlist management endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update

from app.api.deps import DbSession, RequiredProfile
from app.db.models import ExternalTrack, ExternalTrackSource, Playlist, PlaylistTrack, Track
from app.services.external_track_matcher import ExternalTrackMatcher
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

    id: str  # For local tracks: track_id, for external: external_track_id
    playlist_track_id: str  # The PlaylistTrack.id (for reordering/removal)
    type: str  # "local" or "external"
    title: str | None
    artist: str | None
    album: str | None
    duration_seconds: float | None
    position: int

    # External track fields
    is_matched: bool = False
    matched_track_id: str | None = None
    match_confidence: float | None = None
    preview_url: str | None = None
    external_links: dict[str, str] = {}  # spotify, bandcamp, deezer URLs


class PlaylistResponse(BaseModel):
    """Playlist response."""

    id: str
    name: str
    description: str | None
    is_auto_generated: bool
    is_wishlist: bool = False
    generation_prompt: str | None
    track_count: int
    local_track_count: int = 0
    external_track_count: int = 0
    auto_download: bool = False
    created_at: str
    updated_at: str


class PlaylistDetailResponse(BaseModel):
    """Playlist detail response with tracks."""

    id: str
    name: str
    description: str | None
    is_auto_generated: bool
    is_wishlist: bool = False
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
    include_wishlist: bool = Query(True, description="Include wishlist playlist"),
) -> list[PlaylistResponse]:
    """List all playlists for the current profile."""
    query = select(Playlist).where(Playlist.profile_id == profile.id)

    if not include_auto:
        query = query.where(Playlist.is_auto_generated.is_(False))

    if not include_wishlist:
        query = query.where(Playlist.is_wishlist.is_(False))

    # Wishlist first, then by updated_at
    query = query.order_by(Playlist.is_wishlist.desc(), Playlist.updated_at.desc())

    result = await db.execute(query)
    playlists = result.scalars().all()

    # Get track counts (separate local and external)
    responses = []
    for playlist in playlists:
        # Count total tracks
        total_count = await db.scalar(
            select(func.count(PlaylistTrack.id)).where(
                PlaylistTrack.playlist_id == playlist.id
            )
        ) or 0

        # Count local tracks
        local_count = await db.scalar(
            select(func.count(PlaylistTrack.id)).where(
                PlaylistTrack.playlist_id == playlist.id,
                PlaylistTrack.track_id.isnot(None),
            )
        ) or 0

        external_count = total_count - local_count

        responses.append(PlaylistResponse(
            id=str(playlist.id),
            name=playlist.name,
            description=playlist.description,
            is_auto_generated=playlist.is_auto_generated,
            is_wishlist=playlist.is_wishlist,
            generation_prompt=playlist.generation_prompt,
            track_count=total_count,
            local_track_count=local_count,
            external_track_count=external_count,
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

        # Verify track exists
        track = await db.get(Track, track_id)
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
# Wishlist Endpoints (must be defined before /{playlist_id} routes)
# ============================================================================


class WishlistAddRequest(BaseModel):
    """Request to add an item to the wishlist."""

    title: str
    artist: str
    album: str | None = None
    spotify_id: str | None = None
    preview_url: str | None = None
    external_data: dict | None = None


@router.get("/wishlist", response_model=PlaylistDetailResponse)
async def get_wishlist(
    db: DbSession,
    profile: RequiredProfile,
) -> PlaylistDetailResponse:
    """Get the wishlist playlist for the current profile.

    Creates the wishlist if it doesn't exist.
    """
    # Find or create wishlist
    result = await db.execute(
        select(Playlist).where(
            Playlist.profile_id == profile.id,
            Playlist.is_wishlist.is_(True),
        )
    )
    wishlist = result.scalar_one_or_none()

    if not wishlist:
        # Create wishlist
        wishlist = Playlist(
            profile_id=profile.id,
            name="Wishlist",
            description="Tracks I want to add to my library",
            is_wishlist=True,
        )
        db.add(wishlist)
        await db.commit()
        await db.refresh(wishlist)

    return await get_playlist(wishlist.id, db, profile)


@router.post("/wishlist/add", response_model=PlaylistDetailResponse)
async def add_to_wishlist(
    request: WishlistAddRequest,
    db: DbSession,
    profile: RequiredProfile,
) -> PlaylistDetailResponse:
    """Add a track to the wishlist.

    Creates an ExternalTrack and adds it to the wishlist playlist.
    """
    # Find or create wishlist
    result = await db.execute(
        select(Playlist).where(
            Playlist.profile_id == profile.id,
            Playlist.is_wishlist.is_(True),
        )
    )
    wishlist = result.scalar_one_or_none()

    if not wishlist:
        wishlist = Playlist(
            profile_id=profile.id,
            name="Wishlist",
            description="Tracks I want to add to my library",
            is_wishlist=True,
        )
        db.add(wishlist)
        await db.flush()

    # Create external track
    matcher = ExternalTrackMatcher(db)
    external_track = await matcher.create_external_track(
        title=request.title,
        artist=request.artist,
        album=request.album,
        source=ExternalTrackSource.MANUAL,
        spotify_id=request.spotify_id,
        preview_url=request.preview_url,
        preview_source="spotify" if request.preview_url else None,
        external_data=request.external_data,
        source_playlist_id=wishlist.id,
        try_match=True,
    )

    # Get max position
    max_pos = await db.scalar(
        select(func.max(PlaylistTrack.position)).where(
            PlaylistTrack.playlist_id == wishlist.id
        )
    ) or -1

    # Add to wishlist
    playlist_track = PlaylistTrack(
        playlist_id=wishlist.id,
        external_track_id=external_track.id,
        position=max_pos + 1,
    )
    db.add(playlist_track)

    await db.commit()

    return await get_playlist(wishlist.id, db, profile)


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

    # Get all playlist tracks ordered by position
    result = await db.execute(
        select(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .order_by(PlaylistTrack.position)
    )
    playlist_tracks = result.scalars().all()

    tracks = []
    for pt in playlist_tracks:
        if pt.track_id:
            # Local track
            track = await db.get(Track, pt.track_id)
            if track:
                tracks.append(TrackInPlaylist(
                    id=str(track.id),
                    playlist_track_id=str(pt.id),
                    type="local",
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    duration_seconds=track.duration_seconds,
                    position=pt.position,
                    is_matched=False,
                    matched_track_id=None,
                    match_confidence=None,
                    preview_url=None,
                    external_links={},
                ))
        elif pt.external_track_id:
            # External track
            ext = await db.get(ExternalTrack, pt.external_track_id)
            if ext:
                external_links = {}
                if ext.external_data:
                    if ext.external_data.get("spotify_url"):
                        external_links["spotify"] = ext.external_data["spotify_url"]

                tracks.append(TrackInPlaylist(
                    id=str(ext.id),
                    playlist_track_id=str(pt.id),
                    type="external",
                    title=ext.title,
                    artist=ext.artist,
                    album=ext.album,
                    duration_seconds=ext.duration_seconds,
                    position=pt.position,
                    is_matched=ext.matched_track_id is not None,
                    matched_track_id=str(ext.matched_track_id) if ext.matched_track_id else None,
                    match_confidence=ext.match_confidence,
                    preview_url=ext.preview_url,
                    external_links=external_links,
                ))

    return PlaylistDetailResponse(
        id=str(playlist.id),
        name=playlist.name,
        description=playlist.description,
        is_auto_generated=playlist.is_auto_generated,
        is_wishlist=playlist.is_wishlist,
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

    # Get track counts
    total_count = await db.scalar(
        select(func.count(PlaylistTrack.id)).where(
            PlaylistTrack.playlist_id == playlist.id
        )
    ) or 0

    local_count = await db.scalar(
        select(func.count(PlaylistTrack.id)).where(
            PlaylistTrack.playlist_id == playlist.id,
            PlaylistTrack.track_id.isnot(None),
        )
    ) or 0

    return PlaylistResponse(
        id=str(playlist.id),
        name=playlist.name,
        description=playlist.description,
        is_auto_generated=playlist.is_auto_generated,
        is_wishlist=playlist.is_wishlist,
        generation_prompt=playlist.generation_prompt,
        track_count=total_count,
        local_track_count=local_count,
        external_track_count=total_count - local_count,
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
    """Delete a playlist.

    The wishlist playlist cannot be deleted.
    """
    playlist = await db.get(Playlist, playlist_id)

    if not playlist or playlist.profile_id != profile.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        )

    if playlist.is_wishlist:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the wishlist playlist",
        )

    # Delete playlist tracks first (cascade should handle this, but be explicit)
    await db.execute(
        delete(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)
    )

    await db.delete(playlist)
    await db.commit()


@router.post("/{playlist_id}/tracks", response_model=PlaylistDetailResponse)
async def add_tracks_to_playlist(
    playlist_id: UUID,
    track_ids: list[str],
    db: DbSession,
    profile: RequiredProfile,
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
