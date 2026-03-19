"""Playback tool handlers (queue_tracks, control_playback, get_track_details)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select

from app.db.models import Track, TrackAnalysis

if TYPE_CHECKING:
    from app.services.llm.executor import ToolExecutor

logger = logging.getLogger(__name__)


class PlaybackHandlersMixin:
    """Mixin providing playback tool handlers."""

    async def _queue_tracks(
        self: "ToolExecutor",
        track_ids: list[str],
        clear_existing: bool = False,
        suggested_tracks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Queue tracks for playback and return ephemeral playlist metadata.

        The playlist is NOT automatically saved - instead we return metadata
        for the frontend to store ephemerally. User must explicitly save.

        Args:
            track_ids: List of local track UUIDs to queue for playback
            clear_existing: Whether to clear the current queue
            suggested_tracks: External tracks to suggest (stored with ephemeral metadata)
        """
        logger.info(f"_queue_tracks called with {len(track_ids)} tracks, {len(suggested_tracks or [])} suggested")

        # Get local tracks for playback queue
        valid_uuids = self._safe_parse_uuids(track_ids)
        if not valid_uuids:
            return {"queued": 0, "clear_existing": clear_existing, "tracks": [], "note": "No valid track IDs provided"}
        stmt = select(Track).where(Track.active_filter(), Track.id.in_(valid_uuids))
        result = await self.db.execute(stmt)
        tracks = result.scalars().all()

        self._queued_tracks = [self._track_to_dict(t) for t in tracks]

        # Generate playlist name for ephemeral metadata (no DB save)
        playlist_name = ""
        if tracks and self.profile_id:
            playlist_name = await self._generate_playlist_name_llm(self._queued_tracks)

        # Build ephemeral playlist metadata for frontend to store temporarily
        self._auto_saved_playlist = {
            "ephemeral": True,
            "name": playlist_name,
            "generation_prompt": self.user_message,
            "track_ids": track_ids,
            "tracks": self._queued_tracks,
            "suggested_tracks": suggested_tracks or [],
        }

        response: dict[str, Any] = {
            "queued": len(tracks),
            "clear_existing": clear_existing,
            "tracks": self._queued_tracks,
        }

        return response

    async def _control_playback(self: "ToolExecutor", action: str) -> dict[str, Any]:
        """Control playback."""
        self._playback_action = action
        return {"action": action, "status": "ok"}

    async def _get_track_details(self: "ToolExecutor", track_id: str) -> dict[str, Any]:
        """Get detailed track info including features."""
        stmt = select(Track).where(Track.active_filter(), Track.id == UUID(track_id))
        result = await self.db.execute(stmt)
        track = result.scalar_one_or_none()

        if not track:
            return {"error": "Track not found"}

        analysis_stmt = (
            select(TrackAnalysis)
            .where(TrackAnalysis.track_id == UUID(track_id))
        )
        analysis_result = await self.db.execute(analysis_stmt)
        analysis = analysis_result.scalar_one_or_none()

        track_dict = self._track_to_dict(track)
        if analysis:
            track_dict["features"] = analysis.to_features_dict()

        return track_dict
