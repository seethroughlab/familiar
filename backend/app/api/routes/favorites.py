"""Favorites management endpoints for profile-based track favorites."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbSession, RequiredProfile
from app.api.routes.tracks import TrackResponse
from app.db.models import ExternalTrack, ProfileExternalFavorite, ProfileFavorite, Track

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/favorites", tags=["favorites"])


class FavoriteTrackResponse(TrackResponse):
    """Track in favorites list — full track data plus favorited_at."""

    favorited_at: str = ""


class ExternalFavoriteTrackResponse(BaseModel):
    """External track in favorites list."""

    id: UUID
    type: str = "external"
    title: str
    artist: str
    album: str | None = None
    duration_seconds: float | None = None
    year: int | None = None
    source: str
    is_matched: bool = False
    matched_track_id: UUID | None = None
    preview_url: str | None = None
    external_links: dict[str, str] = {}
    favorited_at: str = ""


class FavoritesListResponse(BaseModel):
    """Response for favorites list."""

    favorites: list[FavoriteTrackResponse]
    external_favorites: list[ExternalFavoriteTrackResponse] = []
    total: int


class FavoriteStatusResponse(BaseModel):
    """Response for favorite status check."""

    track_id: UUID
    is_favorite: bool


class ExternalFavoriteStatusResponse(BaseModel):
    """Response for external favorite status check."""

    external_track_id: UUID
    is_favorite: bool
    redirected_to_local: bool = False
    local_track_id: UUID | None = None


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


def _build_external_links(ext: ExternalTrack) -> dict[str, str]:
    """Build external links dict from an ExternalTrack."""
    links: dict[str, str] = {}
    if ext.spotify_id:
        links["spotify"] = f"https://open.spotify.com/track/{ext.spotify_id}"
    if ext.external_data:
        for key in ("spotify_url", "external_url"):
            if ext.external_data.get(key):
                links.setdefault("spotify", ext.external_data[key])
    return links


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

    favorites = []
    for favorite, track in rows:
        resp = FavoriteTrackResponse.model_validate(
            track, from_attributes=True
        )
        resp.favorited_at = favorite.favorited_at.isoformat()
        favorites.append(resp)

    # Get external favorites (graceful degradation if table doesn't exist yet)
    external_favorites = []
    ext_count = 0
    try:
        ext_result = await db.execute(
            select(ProfileExternalFavorite, ExternalTrack)
            .join(ExternalTrack, ProfileExternalFavorite.external_track_id == ExternalTrack.id)
            .where(ProfileExternalFavorite.profile_id == profile.id)
            .order_by(ProfileExternalFavorite.favorited_at.desc())
        )
        ext_rows = ext_result.all()

        for ext_fav, ext_track in ext_rows:
            external_favorites.append(
                ExternalFavoriteTrackResponse(
                    id=ext_track.id,
                    title=ext_track.title,
                    artist=ext_track.artist,
                    album=ext_track.album,
                    duration_seconds=ext_track.duration_seconds,
                    year=ext_track.year,
                    source=ext_track.source.value,
                    is_matched=ext_track.matched_track_id is not None,
                    matched_track_id=ext_track.matched_track_id,
                    preview_url=ext_track.external_data.get("itunes_preview_url") if ext_track.external_data else None,
                    external_links=_build_external_links(ext_track),
                    favorited_at=ext_fav.favorited_at.isoformat(),
                )
            )
        ext_count = len(ext_rows)
    except Exception:
        logger.warning("Failed to query external favorites (table may not exist yet)")
        await db.rollback()

    return FavoritesListResponse(
        favorites=favorites,
        external_favorites=external_favorites,
        total=local_count + ext_count,
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


@router.post("/external/{external_track_id}/toggle", response_model=ExternalFavoriteStatusResponse)
async def toggle_external_favorite(
    external_track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> ExternalFavoriteStatusResponse:
    """Toggle an external track's favorite status.

    If the external track is matched to a local track, redirects to toggle
    the local track favorite instead (avoids duplicates).
    """
    try:
        ext_track = await db.get(ExternalTrack, external_track_id)
    except Exception:
        logger.warning("External favorites table not available")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External favorites not available (migration pending)",
        )
    if not ext_track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="External track not found",
        )

    # If matched to a local track, toggle the local favorite instead
    if ext_track.matched_track_id:
        is_fav = await _toggle_local_favorite(db, profile.id, ext_track.matched_track_id)
        return ExternalFavoriteStatusResponse(
            external_track_id=external_track_id,
            is_favorite=is_fav,
            redirected_to_local=True,
            local_track_id=ext_track.matched_track_id,
        )

    # Toggle external favorite
    try:
        result = await db.execute(
            select(ProfileExternalFavorite).where(
                ProfileExternalFavorite.profile_id == profile.id,
                ProfileExternalFavorite.external_track_id == external_track_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            await db.delete(existing)
            await db.commit()
            return ExternalFavoriteStatusResponse(
                external_track_id=external_track_id,
                is_favorite=False,
            )
        else:
            ext_fav = ProfileExternalFavorite(
                profile_id=profile.id,
                external_track_id=external_track_id,
            )
            db.add(ext_fav)
            await db.commit()
            return ExternalFavoriteStatusResponse(
                external_track_id=external_track_id,
                is_favorite=True,
            )
    except HTTPException:
        raise
    except Exception:
        logger.warning("Failed to toggle external favorite (table may not exist)")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External favorites not available (migration pending)",
        )


@router.get("/external/{external_track_id}", response_model=ExternalFavoriteStatusResponse)
async def check_external_favorite(
    external_track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> ExternalFavoriteStatusResponse:
    """Check if an external track is in favorites.

    If matched to a local track, checks the local favorite instead.
    """
    try:
        ext_track = await db.get(ExternalTrack, external_track_id)
    except Exception:
        logger.warning("External favorites table not available")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External favorites not available (migration pending)",
        )
    if not ext_track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="External track not found",
        )

    # If matched, check local favorite
    if ext_track.matched_track_id:
        result = await db.execute(
            select(ProfileFavorite).where(
                ProfileFavorite.profile_id == profile.id,
                ProfileFavorite.track_id == ext_track.matched_track_id,
            )
        )
        is_fav = result.scalar_one_or_none() is not None
        return ExternalFavoriteStatusResponse(
            external_track_id=external_track_id,
            is_favorite=is_fav,
            redirected_to_local=True,
            local_track_id=ext_track.matched_track_id,
        )

    # Check external favorite
    try:
        result = await db.execute(
            select(ProfileExternalFavorite).where(
                ProfileExternalFavorite.profile_id == profile.id,
                ProfileExternalFavorite.external_track_id == external_track_id,
            )
        )
        is_fav = result.scalar_one_or_none() is not None
        return ExternalFavoriteStatusResponse(
            external_track_id=external_track_id,
            is_favorite=is_fav,
        )
    except Exception:
        logger.warning("Failed to check external favorite (table may not exist)")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External favorites not available (migration pending)",
        )


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

    is_fav = await _toggle_local_favorite(db, profile.id, track_id)
    return FavoriteStatusResponse(track_id=track_id, is_favorite=is_fav)
