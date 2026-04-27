"""Playlist recommendation endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import PlaylistNotFoundError, ValidationError
from app.db.models import Playlist
from app.services.recommendations import RecommendationsService

router = APIRouter()


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
        raise PlaylistNotFoundError()

    if not playlist.is_auto_generated:
        raise ValidationError("Recommendations only available for AI-generated playlists")

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


class ExternalAlbumResponse(BaseModel):
    """An external (not-in-library) album recommendation."""

    id: str
    artist_name: str
    release_name: str
    release_type: str | None
    release_date: str | None
    artwork_url: str
    external_url: str | None
    track_count: int | None
    match_score: float
    seed_artist: str | None
    local_album_match: bool
    dismissed: bool
    discovered_at: str
    purchase_links: dict[str, Any]


class ExternalAlbumsResponse(BaseModel):
    """List of external album recommendations."""

    albums: list[ExternalAlbumResponse]


@router.get(
    "/{playlist_id}/recommendations/external-albums",
    response_model=ExternalAlbumsResponse,
)
async def get_playlist_external_albums(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
    limit: int = Query(12, ge=1, le=50),
    refresh: bool = Query(False),
) -> ExternalAlbumsResponse:
    """External album recommendations (not in library) seeded by this playlist's tracks.

    Available for any playlist (manual, smart, or AI-generated) — unlike the
    sibling ``/recommendations`` endpoint which is AI-only. Recompute is lazy
    with a 24h TTL; pass ``refresh=true`` to force.
    """
    playlist = await db.get(Playlist, playlist_id)

    if not playlist or playlist.profile_id != profile.id:
        raise PlaylistNotFoundError()

    service = RecommendationsService(db)
    try:
        rows = await service.get_playlist_external_albums(
            playlist_id, limit=limit, refresh=refresh
        )
        await db.commit()
        return ExternalAlbumsResponse(
            albums=[ExternalAlbumResponse(**row) for row in rows]
        )
    finally:
        await service.close()
