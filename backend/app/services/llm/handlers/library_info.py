"""Library info tool handlers (get_library_stats, get_library_genres, get_visible_tracks)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select, text

from app.db.models import Track, TrackAnalysis

if TYPE_CHECKING:
    from app.services.llm.executor import ToolExecutor

logger = logging.getLogger(__name__)


class LibraryInfoHandlersMixin:
    """Mixin providing library info tool handlers."""

    async def _get_library_stats(self: "ToolExecutor") -> dict[str, Any]:
        """Get library statistics."""
        total_result = await self.db.execute(
            select(func.count(Track.id)).where(Track.active_filter())
        )
        total_tracks = total_result.scalar() or 0

        artists_result = await self.db.execute(
            select(func.count(func.distinct(Track.artist))).where(Track.active_filter())
        )
        total_artists = artists_result.scalar() or 0

        albums_result = await self.db.execute(
            select(func.count(func.distinct(Track.album))).where(Track.active_filter())
        )
        total_albums = albums_result.scalar() or 0

        genres_result = await self.db.execute(
            select(Track.genre, func.count(Track.id).label("count"))
            .where(Track.active_filter(), Track.genre.isnot(None))
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

    async def _get_visible_tracks(self: "ToolExecutor") -> dict[str, Any]:
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

    async def _get_library_genres(self: "ToolExecutor", limit: int = 50) -> dict[str, Any]:
        """Get all genres in the library with track counts."""
        try:
            limit = int(float(limit)) if limit else 50
        except (ValueError, TypeError):
            limit = 50

        genres_result = await self.db.execute(
            select(Track.genre, func.count(Track.id).label("count"))
            .where(Track.active_filter(), Track.genre.isnot(None))
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

    async def _get_feature_distribution(self: "ToolExecutor", feature: str) -> dict[str, Any]:
        """Get min/max/mean/median for an audio feature across the library."""
        allowed = {
            "energy", "valence", "danceability", "bpm",
            "acousticness", "instrumentalness", "speechiness",
            "brightness", "dynamic_range_db", "harmonic_complexity",
            "swing_ratio", "syncopation", "note_density", "pitch_range",
            "section_count",
        }
        if feature not in allowed:
            return {"error": f"Unknown feature '{feature}'. Allowed: {sorted(allowed)}"}

        col = getattr(TrackAnalysis, feature)

        stmt = select(
            func.min(col).label("min"),
            func.max(col).label("max"),
            func.avg(col).label("mean"),
            func.percentile_cont(0.5).within_group(col).label("median"),
            func.count(col).label("count"),
        ).where(col.isnot(None))

        result = await self.db.execute(stmt)
        row = result.one()

        if row.count == 0:
            return {"feature": feature, "error": "No tracks have this feature analyzed yet"}

        def _round(v: Any) -> Any:
            if v is None:
                return None
            return round(float(v), 3)

        return {
            "feature": feature,
            "min": _round(row.min),
            "max": _round(row.max),
            "mean": _round(row.mean),
            "median": _round(row.median),
            "analyzed_tracks": row.count,
        }

    async def _get_available_mood_tags(
        self: "ToolExecutor", category: str | None = None
    ) -> dict[str, Any]:
        """Get available mood tags with track counts."""
        from sqlalchemy import text

        from app.services.mood_tags import DESCRIPTORS

        # Query distinct tags with counts from JSONB
        query = text("""
            SELECT tag_elem->>'tag' AS tag,
                   tag_elem->>'category' AS category,
                   COUNT(*) AS track_count
            FROM track_analysis,
                 jsonb_array_elements(mood_tags) AS tag_elem
            WHERE mood_tags IS NOT NULL
            GROUP BY tag, category
            ORDER BY track_count DESC
        """)
        result = await self.db.execute(query)
        rows = result.fetchall()

        tags = []
        for row in rows:
            if category and row.category != category:
                continue
            tags.append({
                "tag": row.tag,
                "category": row.category,
                "track_count": row.track_count,
            })

        # Also include tags with 0 tracks if not in DB yet
        existing_tags = {t["tag"] for t in tags}
        for desc in DESCRIPTORS:
            if desc["tag"] not in existing_tags:
                if category and desc["category"] != category:
                    continue
                tags.append({
                    "tag": desc["tag"],
                    "category": desc["category"],
                    "track_count": 0,
                })

        return {
            "tags": tags,
            "total_tags": len(tags),
            "total_tagged_tracks": sum(t["track_count"] for t in tags if t["track_count"] > 0),
        }
