"""Favorites management endpoints for profile-based track favorites."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession, RequiredProfile
from app.db.models import ProfileFavorite, Track

router = APIRouter(prefix="/favorites", tags=["favorites"])


class FavoriteTrackResponse(BaseModel):
    """Track in favorites list."""

    id: UUID
    title: str | None
    artist: str | None
    album: str | None
    duration_seconds: float | None
    genre: str | None
    year: int | None
    favorited_at: str


class FavoritesListResponse(BaseModel):
    """Response for favorites list."""

    favorites: list[FavoriteTrackResponse]
    total: int


class FavoriteStatusResponse(BaseModel):
    """Response for favorite status check."""

    track_id: UUID
    is_favorite: bool


@router.get("", response_model=FavoritesListResponse)
async def list_favorites(
    db: DbSession,
    profile: RequiredProfile,
    limit: int = 100,
    offset: int = 0,
) -> FavoritesListResponse:
    """List all favorite tracks for the current profile."""
    # Get favorites with track data
    result = await db.execute(
        select(ProfileFavorite, Track)
        .join(Track, ProfileFavorite.track_id == Track.id)
        .where(ProfileFavorite.profile_id == profile.id)
        .order_by(ProfileFavorite.favorited_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.all()

    # Get total count
    count_result = await db.execute(
        select(ProfileFavorite)
        .where(ProfileFavorite.profile_id == profile.id)
    )
    total = len(count_result.scalars().all())

    favorites = [
        FavoriteTrackResponse(
            id=track.id,
            title=track.title,
            artist=track.artist,
            album=track.album,
            duration_seconds=track.duration_seconds,
            genre=track.genre,
            year=track.year,
            favorited_at=favorite.favorited_at.isoformat(),
        )
        for favorite, track in rows
    ]

    return FavoritesListResponse(favorites=favorites, total=total)


class AutoDownloadResponse(BaseModel):
    """Response for favorites auto-download setting."""

    enabled: bool


class AutoDownloadUpdate(BaseModel):
    """Request to update favorites auto-download setting."""

    enabled: bool


@router.get("/auto-download", response_model=AutoDownloadResponse)
async def get_favorites_auto_download(
    db: DbSession,
    profile: RequiredProfile,
) -> AutoDownloadResponse:
    """Get the auto-download setting for favorites."""
    enabled = (profile.settings or {}).get("favorites_auto_download", False)
    return AutoDownloadResponse(enabled=enabled)


@router.put("/auto-download", response_model=AutoDownloadResponse)
async def set_favorites_auto_download(
    request: AutoDownloadUpdate,
    db: DbSession,
    profile: RequiredProfile,
) -> AutoDownloadResponse:
    """Set the auto-download setting for favorites."""
    settings = dict(profile.settings or {})
    settings["favorites_auto_download"] = request.enabled
    profile.settings = settings
    await db.commit()
    return AutoDownloadResponse(enabled=request.enabled)


@router.post("/{track_id}", status_code=status.HTTP_201_CREATED)
async def add_favorite(
    track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> FavoriteStatusResponse:
    """Add a track to favorites."""
    # Verify track exists
    track = await db.get(Track, track_id)
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found",
        )

    # Check if already favorited
    result = await db.execute(
        select(ProfileFavorite).where(
            ProfileFavorite.profile_id == profile.id,
            ProfileFavorite.track_id == track_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Already favorited, just return success
        return FavoriteStatusResponse(track_id=track_id, is_favorite=True)

    # Add favorite
    favorite = ProfileFavorite(
        profile_id=profile.id,
        track_id=track_id,
    )
    db.add(favorite)
    await db.commit()

    return FavoriteStatusResponse(track_id=track_id, is_favorite=True)


@router.delete("/{track_id}", status_code=status.HTTP_200_OK)
async def remove_favorite(
    track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> FavoriteStatusResponse:
    """Remove a track from favorites."""
    result = await db.execute(
        select(ProfileFavorite).where(
            ProfileFavorite.profile_id == profile.id,
            ProfileFavorite.track_id == track_id,
        )
    )
    favorite = result.scalar_one_or_none()

    if favorite:
        await db.delete(favorite)
        await db.commit()

    return FavoriteStatusResponse(track_id=track_id, is_favorite=False)


@router.get("/{track_id}", response_model=FavoriteStatusResponse)
async def check_favorite(
    track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> FavoriteStatusResponse:
    """Check if a track is in favorites."""
    result = await db.execute(
        select(ProfileFavorite).where(
            ProfileFavorite.profile_id == profile.id,
            ProfileFavorite.track_id == track_id,
        )
    )
    favorite = result.scalar_one_or_none()

    return FavoriteStatusResponse(track_id=track_id, is_favorite=favorite is not None)


@router.post("/{track_id}/toggle", response_model=FavoriteStatusResponse)
async def toggle_favorite(
    track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> FavoriteStatusResponse:
    """Toggle a track's favorite status."""
    # Verify track exists
    track = await db.get(Track, track_id)
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found",
        )

    result = await db.execute(
        select(ProfileFavorite).where(
            ProfileFavorite.profile_id == profile.id,
            ProfileFavorite.track_id == track_id,
        )
    )
    favorite = result.scalar_one_or_none()

    if favorite:
        # Remove favorite
        await db.delete(favorite)
        await db.commit()
        return FavoriteStatusResponse(track_id=track_id, is_favorite=False)
    else:
        # Add favorite
        favorite = ProfileFavorite(
            profile_id=profile.id,
            track_id=track_id,
        )
        db.add(favorite)
        await db.commit()
        return FavoriteStatusResponse(track_id=track_id, is_favorite=True)
