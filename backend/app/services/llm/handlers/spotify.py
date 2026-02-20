"""Spotify tool handlers (status, favorites, sync stats, playlists)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.db.models import (
    SpotifyFavorite,
    SpotifyProfile,
    Track,
)

if TYPE_CHECKING:
    from app.services.llm.executor import ToolExecutor

logger = logging.getLogger(__name__)


class SpotifyHandlersMixin:
    """Mixin providing Spotify-related tool handlers."""

    async def _get_spotify_status(self: ToolExecutor) -> dict[str, Any]:
        """Check if Spotify is connected."""
        if not self.profile_id:
            return {
                "connected": False,
                "message": "No profile ID provided. User can connect via Settings.",
            }

        result = await self.db.execute(
            select(SpotifyProfile).where(SpotifyProfile.profile_id == self.profile_id)
        )
        profile = result.scalar_one_or_none()

        if not profile:
            return {
                "connected": False,
                "message": "Spotify not connected. User can connect via Settings.",
            }

        return {
            "connected": True,
            "spotify_user_id": profile.spotify_user_id,
            "last_sync": profile.last_sync_at.isoformat() if profile.last_sync_at else None,
        }

    async def _get_spotify_favorites(self: ToolExecutor, limit: int = 50) -> dict[str, Any]:
        """Get Spotify favorites that are matched to local library."""
        try:
            limit = int(float(limit)) if limit else 50
        except (ValueError, TypeError):
            limit = 50

        if not self.profile_id:
            return {"tracks": [], "count": 0, "note": "No profile ID provided"}

        result = await self.db.execute(
            select(SpotifyFavorite, Track)
            .join(Track, SpotifyFavorite.matched_track_id == Track.id)
            .where(
                SpotifyFavorite.profile_id == self.profile_id,
                SpotifyFavorite.matched_track_id.isnot(None),
            )
            .order_by(SpotifyFavorite.added_at.desc())
            .limit(limit)
        )
        rows = result.all()

        tracks = []
        for favorite, track in rows:
            track_dict = self._track_to_dict(track)
            track_dict["spotify_added_at"] = (
                favorite.added_at.isoformat() if favorite.added_at else None
            )
            tracks.append(track_dict)

        return {
            "tracks": tracks,
            "count": len(tracks),
            "note": "These are Spotify favorites that match tracks in your local library",
        }

    async def _get_unmatched_spotify_favorites(self: ToolExecutor, limit: int = 50) -> dict[str, Any]:
        """Get Spotify favorites that don't have local matches."""
        try:
            limit = int(float(limit)) if limit else 50
        except (ValueError, TypeError):
            limit = 50

        if not self.profile_id:
            return {"tracks": [], "count": 0, "note": "No profile ID provided"}

        result = await self.db.execute(
            select(SpotifyFavorite)
            .where(
                SpotifyFavorite.profile_id == self.profile_id,
                SpotifyFavorite.matched_track_id.is_(None),
            )
            .order_by(SpotifyFavorite.added_at.desc())
            .limit(limit)
        )
        favorites = result.scalars().all()

        unmatched = []
        for f in favorites:
            data = f.track_data or {}
            unmatched.append({
                "spotify_id": f.spotify_track_id,
                "name": data.get("name"),
                "artist": data.get("artist"),
                "album": data.get("album"),
                "added_at": f.added_at.isoformat() if f.added_at else None,
                "spotify_url": data.get("external_url"),
            })

        return {
            "tracks": unmatched,
            "count": len(unmatched),
            "note": "These are Spotify favorites you don't have in your local library",
        }

    async def _get_spotify_sync_stats(self: ToolExecutor) -> dict[str, Any]:
        """Get Spotify sync statistics."""
        if not self.profile_id:
            return {
                "total_favorites": 0,
                "matched": 0,
                "unmatched": 0,
                "match_rate": 0,
                "last_sync": None,
                "connected": False,
            }

        total = (
            await self.db.scalar(
                select(func.count(SpotifyFavorite.id)).where(
                    SpotifyFavorite.profile_id == self.profile_id
                )
            )
            or 0
        )

        matched = (
            await self.db.scalar(
                select(func.count(SpotifyFavorite.id)).where(
                    SpotifyFavorite.profile_id == self.profile_id,
                    SpotifyFavorite.matched_track_id.isnot(None),
                )
            )
            or 0
        )

        profile_result = await self.db.execute(
            select(SpotifyProfile).where(SpotifyProfile.profile_id == self.profile_id)
        )
        profile = profile_result.scalar_one_or_none()

        return {
            "total_favorites": total,
            "matched": matched,
            "unmatched": total - matched,
            "match_rate": round(matched / total * 100, 1) if total > 0 else 0,
            "last_sync": (
                profile.last_sync_at.isoformat() if profile and profile.last_sync_at else None
            ),
            "connected": profile is not None,
        }

    async def _list_spotify_playlists(self: ToolExecutor, limit: int = 20) -> dict[str, Any]:
        """List user's Spotify playlists."""
        try:
            limit = int(float(limit)) if limit else 20
        except (ValueError, TypeError):
            limit = 20

        if not self.profile_id:
            return {
                "playlists": [],
                "count": 0,
                "error": "No profile ID provided. User needs to be logged in.",
            }

        from app.services.spotify import SpotifyPlaylistService

        try:
            service = SpotifyPlaylistService(self.db)
            playlists = await service.list_playlists(self.profile_id, limit=limit)

            return {
                "playlists": playlists,
                "count": len(playlists),
                "note": "Use get_spotify_playlist_tracks to see tracks in a playlist, or import_spotify_playlist to import one.",
            }
        except ValueError as e:
            return {
                "playlists": [],
                "count": 0,
                "error": str(e),
                "note": "User needs to connect Spotify in Settings first.",
            }
        except Exception as e:
            logger.error(f"Error listing Spotify playlists: {e}")
            return {
                "playlists": [],
                "count": 0,
                "error": "Failed to fetch Spotify playlists",
            }

    async def _get_spotify_playlist_tracks(
        self: ToolExecutor,
        playlist_id: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Get tracks from a Spotify playlist with local match info."""
        try:
            limit = int(float(limit)) if limit else 50
        except (ValueError, TypeError):
            limit = 50

        if not self.profile_id:
            return {
                "tracks": [],
                "error": "No profile ID provided.",
            }

        from app.services.spotify import SpotifyPlaylistService

        try:
            service = SpotifyPlaylistService(self.db)
            result = await service.get_playlist_tracks(
                self.profile_id,
                playlist_id,
                limit=limit,
            )

            return {
                "playlist_name": result.get("playlist_name"),
                "tracks": result.get("tracks", []),
                "total": result.get("total", 0),
                "in_library": result.get("in_library", 0),
                "missing": result.get("missing", 0),
                "match_rate": result.get("match_rate", "0%"),
                "note": "Use import_spotify_playlist to import this playlist to Familiar.",
            }
        except ValueError as e:
            return {
                "tracks": [],
                "error": str(e),
            }
        except Exception as e:
            logger.error(f"Error getting Spotify playlist tracks: {e}")
            return {
                "tracks": [],
                "error": "Failed to fetch playlist tracks",
            }

    async def _import_spotify_playlist(
        self: ToolExecutor,
        spotify_playlist_id: str,
        name: str | None = None,
        include_missing: bool = True,
    ) -> dict[str, Any]:
        """Import a Spotify playlist to Familiar."""
        if not self.profile_id:
            return {
                "error": "No profile ID provided.",
                "imported": False,
            }

        from app.services.spotify import SpotifyPlaylistService

        try:
            service = SpotifyPlaylistService(self.db)
            playlist = await service.import_playlist(
                profile_id=self.profile_id,
                spotify_playlist_id=spotify_playlist_id,
                name=name,
                include_missing=include_missing,
            )

            # Get track counts
            from sqlalchemy import func, select

            from app.db.models import PlaylistTrack

            total_count = await self.db.scalar(
                select(func.count(PlaylistTrack.id)).where(
                    PlaylistTrack.playlist_id == playlist.id
                )
            ) or 0

            local_count = await self.db.scalar(
                select(func.count(PlaylistTrack.id)).where(
                    PlaylistTrack.playlist_id == playlist.id,
                    PlaylistTrack.track_id.isnot(None),
                )
            ) or 0

            return {
                "imported": True,
                "playlist_id": str(playlist.id),
                "playlist_name": playlist.name,
                "total_tracks": total_count,
                "local_tracks": local_count,
                "missing_tracks": total_count - local_count,
                "message": f"Successfully imported playlist '{playlist.name}' with {total_count} tracks ({local_count} local, {total_count - local_count} missing).",
            }
        except ValueError as e:
            return {
                "error": str(e),
                "imported": False,
            }
        except Exception as e:
            logger.error(f"Error importing Spotify playlist: {e}")
            return {
                "error": "Failed to import playlist",
                "imported": False,
            }
