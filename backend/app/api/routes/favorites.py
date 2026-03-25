"""Favorites management endpoints for profile-based track favorites."""

import logging
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import TrackNotFoundError
from app.api.schemas.tracks import TrackResponse
from app.db.models import ProfileFavorite, ProfilePlayHistory, Track

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/favorites", tags=["favorites"])


class FavoriteTrackResponse(TrackResponse):
    """Track in favorites list — full track data plus favorited_at."""

    favorited_at: str = ""


class FavoritesListResponse(BaseModel):
    """Response for favorites list."""

    favorites: list[FavoriteTrackResponse]
    total: int


class FavoriteStatusResponse(BaseModel):
    """Response for favorite status check."""

    track_id: UUID
    is_favorite: bool


async def _toggle_local_favorite(
    db: DbSession, profile_id: UUID, track_id: UUID
) -> bool:
    """Toggle a local track's favorite status. Returns new is_favorite state."""
    result = await db.execute(
        select(ProfileFavorite).where(
            ProfileFavorite.profile_id == profile_id,
            ProfileFavorite.track_id == track_id,
        )
    )
    favorite = result.scalar_one_or_none()

    if favorite:
        await db.delete(favorite)
        await db.commit()
        return False
    else:
        favorite = ProfileFavorite(profile_id=profile_id, track_id=track_id)
        db.add(favorite)
        await db.commit()
        return True


@router.get("", response_model=FavoritesListResponse)
async def list_favorites(
    db: DbSession,
    profile: RequiredProfile,
    limit: int = 100,
    offset: int = 0,
) -> FavoritesListResponse:
    """List all favorite tracks for the current profile."""
    # Get local favorites with track data
    result = await db.execute(
        select(ProfileFavorite, Track)
        .join(Track, ProfileFavorite.track_id == Track.id)
        .where(ProfileFavorite.profile_id == profile.id)
        .order_by(ProfileFavorite.favorited_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.all()

    local_count = await db.scalar(
        select(func.count()).select_from(ProfileFavorite).where(
            ProfileFavorite.profile_id == profile.id
        )
    ) or 0

    # Fetch play history for all favorite tracks
    track_ids = [track.id for _, track in rows]
    play_history_map = {}
    if track_ids:
        ph_result = await db.execute(
            select(ProfilePlayHistory).where(
                ProfilePlayHistory.profile_id == profile.id,
                ProfilePlayHistory.track_id.in_(track_ids),
            )
        )
        play_history_map = {ph.track_id: ph for ph in ph_result.scalars().all()}

    favorites = []
    for favorite, track in rows:
        resp = FavoriteTrackResponse.model_validate(
            track, from_attributes=True
        )
        resp.favorited_at = favorite.favorited_at.isoformat()
        if track.id in play_history_map:
            ph = play_history_map[track.id]
            resp.last_played_at = ph.last_played_at
            resp.play_count = ph.play_count
        favorites.append(resp)

    return FavoritesListResponse(
        favorites=favorites,
        total=local_count,
    )


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
        raise TrackNotFoundError()

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
        raise TrackNotFoundError()

    is_fav = await _toggle_local_favorite(db, profile.id, track_id)
    return FavoriteStatusResponse(track_id=track_id, is_favorite=is_fav)
