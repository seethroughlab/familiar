"""External track matching tool handlers (list unmatched, find candidates, confirm match)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import func, select

from app.db.models import ExternalTrack

if TYPE_CHECKING:
    from app.services.llm.executor import ToolExecutor

logger = logging.getLogger(__name__)


class ExternalTrackHandlersMixin:
    """Mixin providing external track matching tool handlers."""

    async def _get_unmatched_external_tracks(
        self: "ToolExecutor",
        artist: str | None = None,
        album: str | None = None,
        source: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List external tracks that haven't been matched to local library tracks."""
        limit = min(int(limit), 200)

        # Total unmatched count (before filters)
        count_stmt = select(func.count(ExternalTrack.id)).where(
            ExternalTrack.matched_track_id.is_(None)
        )
        total_result = await self.db.execute(count_stmt)
        total_unmatched = total_result.scalar() or 0

        # Filtered query
        stmt = select(ExternalTrack).where(
            ExternalTrack.matched_track_id.is_(None)
        )

        if artist:
            stmt = stmt.where(ExternalTrack.artist.ilike(f"%{artist}%"))
        if album:
            stmt = stmt.where(ExternalTrack.album.ilike(f"%{album}%"))
        if source:
            stmt = stmt.where(ExternalTrack.source == source)

        stmt = stmt.order_by(ExternalTrack.artist, ExternalTrack.title).limit(limit)

        result = await self.db.execute(stmt)
        tracks = list(result.scalars().all())

        return {
            "total_unmatched": total_unmatched,
            "returned": len(tracks),
            "tracks": [
                {
                    "id": str(t.id),
                    "title": t.title,
                    "artist": t.artist,
                    "album": t.album,
                    "source": t.source.value if hasattr(t.source, "value") else str(t.source),
                    "duration_seconds": t.duration_seconds,
                    "isrc": t.isrc,
                }
                for t in tracks
            ],
        }

    async def _get_external_track_match_candidates(
        self: "ToolExecutor",
        external_track_id: str,
    ) -> dict[str, Any]:
        """Find potential local library matches for an external track."""
        try:
            ext_uuid = UUID(external_track_id)
        except ValueError:
            return {"error": f"Invalid external track ID: {external_track_id}"}

        # Fetch the external track
        stmt = select(ExternalTrack).where(ExternalTrack.id == ext_uuid)
        result = await self.db.execute(stmt)
        ext_track = result.scalar_one_or_none()

        if not ext_track:
            return {"error": "External track not found"}

        # Early return if already matched
        if ext_track.matched_track_id is not None:
            return {
                "already_matched": True,
                "matched_track_id": str(ext_track.matched_track_id),
                "message": "This external track is already matched to a local track.",
            }

        # Use ExternalTrackMatcher to find candidates
        from app.services.external_track_matcher import ExternalTrackMatcher

        matcher = ExternalTrackMatcher(self.db)
        candidates = await matcher.find_match_candidates(
            title=ext_track.title,
            artist=ext_track.artist,
            album=ext_track.album,
            isrc=ext_track.isrc,
            limit=10,
        )

        return {
            "external_track": {
                "id": str(ext_track.id),
                "title": ext_track.title,
                "artist": ext_track.artist,
                "album": ext_track.album,
                "duration_seconds": ext_track.duration_seconds,
                "isrc": ext_track.isrc,
            },
            "candidates": candidates,
            "candidate_count": len(candidates),
            "note": "Use match_external_track to confirm a match." if candidates else
                    "No candidates found. The track may not be in the local library.",
        }

    async def _match_external_track(
        self: "ToolExecutor",
        external_track_id: str,
        track_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Confirm a match between an external track and a local library track."""
        try:
            ext_uuid = UUID(external_track_id)
        except ValueError:
            return {"error": f"Invalid external track ID: {external_track_id}"}

        try:
            local_uuid = UUID(track_id)
        except ValueError:
            return {"error": f"Invalid local track ID: {track_id}"}

        from app.services.external_track_matcher import ExternalTrackMatcher

        matcher = ExternalTrackMatcher(self.db)

        try:
            matched = await matcher.manual_match(ext_uuid, local_uuid)
        except ValueError as e:
            return {"error": str(e)}

        if not matched:
            return {"error": "External track not found"}

        return {
            "status": "matched",
            "external_track_id": str(ext_uuid),
            "matched_track_id": str(local_uuid),
            "message": "Successfully matched external track to local library. "
                       "Playlist references have been updated.",
        }
