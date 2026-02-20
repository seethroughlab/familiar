"""Library info tool handlers (get_library_stats, get_library_genres, get_visible_tracks)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select, text

from app.db.models import Track

if TYPE_CHECKING:
    from app.services.llm.executor import ToolExecutor

logger = logging.getLogger(__name__)


class LibraryInfoHandlersMixin:
    """Mixin providing library info tool handlers."""

    async def _get_library_stats(self: ToolExecutor) -> dict[str, Any]:
        """Get library statistics."""
        total_result = await self.db.execute(select(func.count(Track.id)))
        total_tracks = total_result.scalar() or 0

        artists_result = await self.db.execute(
            select(func.count(func.distinct(Track.artist)))
        )
        total_artists = artists_result.scalar() or 0

        albums_result = await self.db.execute(
            select(func.count(func.distinct(Track.album)))
        )
        total_albums = albums_result.scalar() or 0

        genres_result = await self.db.execute(
            select(Track.genre, func.count(Track.id).label("count"))
            .where(Track.genre.isnot(None))
            .group_by(Track.genre)
            .order_by(text("count DESC"))
            .limit(10)
        )
        top_genres = [{"genre": r[0], "count": r[1]} for r in genres_result.all()]

        return {
            "total_tracks": total_tracks,
            "total_artists": total_artists,
            "total_albums": total_albums,
            "top_genres": top_genres,
        }

    async def _get_visible_tracks(self: ToolExecutor) -> dict[str, Any]:
        """Get the tracks currently visible in the user's library view.

        Returns the tracks that the user can see right now in the UI.
        Use this when the user refers to 'these tracks', 'this list',
        'what I'm looking at', or wants to queue/analyze the current view.
        """
        if not self.visible_track_ids:
            return {
                "tracks": [],
                "count": 0,
                "message": "No tracks currently visible in the library view.",
            }

        # Fetch track details from database
        result = await self.db.execute(
            select(Track).where(Track.id.in_(self.visible_track_ids))
        )
        tracks = result.scalars().all()

        # Build a map to preserve order
        track_map = {str(t.id): t for t in tracks}

        # Return in the same order as visible_track_ids
        ordered_tracks = []
        for track_id in self.visible_track_ids:
            if track_id in track_map:
                t = track_map[track_id]
                ordered_tracks.append({
                    "id": str(t.id),
                    "title": t.title,
                    "artist": t.artist or "Unknown Artist",
                    "album": t.album or "Unknown Album",
                    "duration_seconds": t.duration_seconds,
                    "genre": t.genre,
                })

        return {
            "tracks": ordered_tracks,
            "count": len(ordered_tracks),
            "message": f"Found {len(ordered_tracks)} tracks in the current view.",
        }

    async def _get_library_genres(self: ToolExecutor, limit: int = 50) -> dict[str, Any]:
        """Get all genres in the library with track counts."""
        try:
            limit = int(float(limit)) if limit else 50
        except (ValueError, TypeError):
            limit = 50

        genres_result = await self.db.execute(
            select(Track.genre, func.count(Track.id).label("count"))
            .where(Track.genre.isnot(None))
            .where(Track.genre != "")
            .group_by(Track.genre)
            .order_by(text("count DESC"))
            .limit(limit)
        )
        genres = [{"genre": r[0], "count": r[1]} for r in genres_result.all()]

        return {
            "genres": genres,
            "total": len(genres),
            "hint": "Use these genre names in search_library to find tracks.",
        }
