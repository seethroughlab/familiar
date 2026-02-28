"""Metadata correction tool handlers (lookup, propose changes, album tracks, artwork, duplicates)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import func, or_, select

from app.db.models import (
    ChangeScope,
    ChangeSource,
    ChangeStatus,
    ProposedChange,
    Track,
)
from app.services.metadata.lookup import get_metadata_lookup_service

if TYPE_CHECKING:
    from app.services.llm.executor import ToolExecutor

logger = logging.getLogger(__name__)


class MetadataHandlersMixin:
    """Mixin providing metadata correction tool handlers."""

    async def _lookup_correct_metadata(self: "ToolExecutor", track_id: str) -> dict[str, Any]:
        """Look up correct metadata from external sources."""
        try:
            track_uuid = UUID(track_id)
        except ValueError:
            return {"error": "Invalid track ID"}

        stmt = select(Track).where(Track.id == track_uuid)
        result = await self.db.execute(stmt)
        track = result.scalar_one_or_none()

        if not track:
            return {"error": "Track not found"}

        lookup_service = get_metadata_lookup_service()
        candidates = await lookup_service.lookup_track(
            title=track.title or "",
            artist=track.artist or "",
            album=track.album,
            duration_ms=int(track.duration_seconds * 1000) if track.duration_seconds else None,
        )

        return {
            "track": {
                "id": str(track.id),
                "title": track.title,
                "artist": track.artist,
                "album": track.album,
                "album_artist": track.album_artist,
                "year": track.year,
                "genre": track.genre,
            },
            "candidates": [
                {
                    "source": c.source,
                    "confidence": round(c.confidence, 2),
                    "metadata": c.metadata,
                    "match_details": c.match_details,
                }
                for c in candidates[:5]
            ],
            "note": "Use propose_metadata_change to suggest corrections based on these results",
        }

    async def _propose_metadata_change(
        self: "ToolExecutor",
        track_ids: list[str],
        field: str,
        new_value: str,
        reason: str,
        source: str = "user_request",
    ) -> dict[str, Any]:
        """Create a proposed change for user review."""
        if not track_ids:
            return {"error": "No track IDs provided"}

        valid_fields = ["title", "artist", "album", "album_artist", "year", "genre"]
        if field not in valid_fields:
            return {"error": f"Invalid field. Must be one of: {', '.join(valid_fields)}"}

        # Get current values for all tracks
        valid_uuids = self._safe_parse_uuids(track_ids)
        if not valid_uuids:
            return {"error": "No valid track IDs provided"}
        stmt = select(Track).where(Track.id.in_(valid_uuids))
        result = await self.db.execute(stmt)
        tracks = list(result.scalars().all())

        if not tracks:
            return {"error": "No tracks found with those IDs"}

        # Build old_value map
        old_values = {}
        for track in tracks:
            current_value = getattr(track, field, None)
            old_values[str(track.id)] = current_value

        # Convert year to int if needed
        final_new_value: Any = new_value
        if field == "year":
            try:
                final_new_value = int(new_value)
            except ValueError:
                return {"error": f"Invalid year value: {new_value}"}

        # Determine source enum
        source_enum = ChangeSource.USER_REQUEST
        if source == "llm_suggestion":
            source_enum = ChangeSource.LLM_SUGGESTION

        # Create the proposed change
        change = ProposedChange(
            change_type="metadata",
            target_type="track",
            target_ids=track_ids,
            field=field,
            old_value=old_values,
            new_value=final_new_value,
            source=source_enum,
            source_detail="LLM tool call",
            confidence=1.0 if source == "user_request" else 0.9,
            reason=reason,
            scope=ChangeScope.DB_ONLY,
            status=ChangeStatus.PENDING,
        )
        self.db.add(change)
        await self.db.commit()
        await self.db.refresh(change)

        logger.info(f"Created proposed change {change.id}: {field} -> {new_value} for {len(track_ids)} tracks")

        return {
            "status": "proposed",
            "change_id": str(change.id),
            "field": field,
            "new_value": final_new_value,
            "tracks_affected": len(tracks),
            "message": f"Proposed changing '{field}' to '{new_value}' for {len(tracks)} track(s). Opening the Proposed Changes view for review.",
            "_navigate": "proposed-changes",  # Triggers frontend navigation
        }

    async def _get_album_tracks(
        self: "ToolExecutor",
        album: str,
        artist: str | None = None,
    ) -> dict[str, Any]:
        """Get all tracks from a specific album."""
        stmt = select(Track).where(Track.album.ilike(f"%{album}%"))

        if artist:
            stmt = stmt.where(
                or_(
                    Track.artist.ilike(f"%{artist}%"),
                    Track.album_artist.ilike(f"%{artist}%"),
                )
            )

        stmt = stmt.order_by(Track.disc_number, Track.track_number)
        result = await self.db.execute(stmt)
        tracks = list(result.scalars().all())

        if not tracks:
            return {"tracks": [], "count": 0, "note": f"No tracks found for album '{album}'"}

        # Group info
        artists_on_album = list(set(t.artist for t in tracks if t.artist))
        album_artist = tracks[0].album_artist

        return {
            "album": tracks[0].album,
            "album_artist": album_artist,
            "artists_on_album": artists_on_album,
            "is_multi_artist": len(artists_on_album) > 1,
            "tracks": [
                {
                    "id": str(t.id),
                    "title": t.title,
                    "artist": t.artist,
                    "track_number": t.track_number,
                    "disc_number": t.disc_number,
                }
                for t in tracks
            ],
            "count": len(tracks),
            "track_ids": [str(t.id) for t in tracks],
            "note": "Use propose_metadata_change with track_ids to suggest changes for all these tracks",
        }

    async def _mark_album_as_compilation(
        self: "ToolExecutor",
        album: str,
        album_artist: str,
        reason: str,
    ) -> dict[str, Any]:
        """Mark an album as a compilation by setting album_artist for all tracks."""
        # First get all tracks for this album
        album_result = await self._get_album_tracks(album)

        if album_result.get("count", 0) == 0:
            return {"error": f"No tracks found for album '{album}'"}

        track_ids = album_result.get("track_ids", [])

        # Propose the album_artist change
        return await self._propose_metadata_change(
            track_ids=track_ids,
            field="album_artist",
            new_value=album_artist,
            reason=reason,
            source="user_request",
        )

    async def _propose_album_artwork(
        self: "ToolExecutor",
        artist: str,
        album: str,
        reason: str,
    ) -> dict[str, Any]:
        """Search for album artwork and propose a change."""
        # First get the tracks for this album to get their IDs
        album_result = await self._get_album_tracks(album, artist)

        if album_result.get("count", 0) == 0:
            return {"error": f"No tracks found for album '{album}' by '{artist}'"}

        track_ids = album_result.get("track_ids", [])

        # Search for artwork options
        lookup_service = get_metadata_lookup_service()
        artwork_options = await lookup_service.search_artwork(artist, album, limit=5)

        if not artwork_options:
            return {
                "error": f"No artwork found for '{album}' by '{artist}'",
                "note": "Try searching for the album on Cover Art Archive manually",
            }

        # Use the best match
        best_option = artwork_options[0]

        # Create the proposed change
        change = ProposedChange(
            change_type="artwork",
            target_type="album",
            target_ids=track_ids,
            field="artwork_url",
            old_value=None,
            new_value={
                "url": best_option["url"],
                "source": best_option["source"],
                "source_id": best_option.get("source_id"),
                "album": best_option.get("album"),
                "artist": best_option.get("artist"),
            },
            source=ChangeSource.USER_REQUEST,
            source_detail=f"Cover Art Archive: {best_option.get('source_id', 'unknown')}",
            confidence=best_option.get("confidence", 0.8),
            reason=reason,
            scope=ChangeScope.DB_ONLY,
            status=ChangeStatus.PENDING,
        )
        self.db.add(change)
        await self.db.commit()
        await self.db.refresh(change)

        logger.info(f"Created artwork proposed change {change.id} for album '{album}'")

        return {
            "status": "proposed",
            "change_id": str(change.id),
            "artwork_url": best_option["url"],
            "source": best_option["source"],
            "tracks_affected": len(track_ids),
            "artwork_options_found": len(artwork_options),
            "message": f"Found artwork for '{album}' and proposed the change. User can review in Settings > Proposed Changes.",
        }

    def _normalize_artist_for_comparison(self: "ToolExecutor", artist: str) -> str:
        """Normalize artist name for duplicate detection.

        Handles common variations:
        - Case: "Artist Name" vs "artist name"
        - Separators: "_" vs " ", "-" vs " "
        - Conjunctions: "and" vs "&" vs "+"
        - Whitespace: extra spaces
        """
        if not artist:
            return ""

        s = artist.lower().strip()

        # Normalize separators to spaces
        s = s.replace("_", " ")
        s = s.replace("-", " ")

        # Normalize conjunctions
        s = s.replace(" & ", " and ")
        s = s.replace(" + ", " and ")
        s = s.replace("&", " and ")
        s = s.replace("+", " and ")

        # Collapse whitespace
        s = " ".join(s.split())

        return s

    async def _find_duplicate_artists(
        self: "ToolExecutor",
        artist_hint: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Find artists that are likely duplicates based on normalized names."""
        from collections import defaultdict

        # Get all distinct artists
        stmt = (
            select(Track.artist, func.count(Track.id).label("track_count"))
            .where(Track.artist.isnot(None), Track.artist != "")
            .group_by(Track.artist)
            .order_by(func.count(Track.id).desc())
        )
        result = await self.db.execute(stmt)
        artists = [(row.artist, row.track_count) for row in result.all()]

        # Group by normalized name
        normalized_groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for artist, count in artists:
            normalized = self._normalize_artist_for_comparison(artist)
            normalized_groups[normalized].append((artist, count))

        # Find groups with more than one variant
        duplicates = []
        for normalized, variants in normalized_groups.items():
            if len(variants) > 1:
                # If artist_hint provided, only include groups that match
                if artist_hint:
                    hint_normalized = self._normalize_artist_for_comparison(artist_hint)
                    if hint_normalized != normalized:
                        continue

                # Sort by track count (most common first)
                variants.sort(key=lambda x: x[1], reverse=True)
                total_tracks = sum(v[1] for v in variants)

                duplicates.append({
                    "canonical": variants[0][0],  # Most common spelling
                    "variants": [{"name": v[0], "track_count": v[1]} for v in variants],
                    "total_tracks": total_tracks,
                })

        # Sort by total tracks and limit (total_tracks is always int)
        duplicates.sort(key=lambda x: x["total_tracks"], reverse=True)  # type: ignore[arg-type, return-value]
        duplicates = duplicates[:limit]

        if not duplicates:
            if artist_hint:
                return {
                    "found": 0,
                    "message": f"No duplicates found for artist '{artist_hint}'",
                }
            return {
                "found": 0,
                "message": "No duplicate artists found in the library",
            }

        return {
            "found": len(duplicates),
            "duplicates": duplicates,
            "message": f"Found {len(duplicates)} artist(s) with duplicate spellings. Use merge_duplicate_artists to propose merging them.",
        }

    async def _merge_duplicate_artists(
        self: "ToolExecutor",
        source_artist: str,
        target_artist: str,
        reason: str,
    ) -> dict[str, Any]:
        """Propose merging duplicate artists by changing the artist field."""
        # Find all tracks with the source artist
        stmt = select(Track).where(
            func.lower(Track.artist) == source_artist.lower()
        )
        result = await self.db.execute(stmt)
        tracks = list(result.scalars().all())

        if not tracks:
            return {"error": f"No tracks found with artist '{source_artist}'"}

        track_ids = [str(t.id) for t in tracks]

        # Use the existing propose_metadata_change
        return await self._propose_metadata_change(
            track_ids=track_ids,
            field="artist",
            new_value=target_artist,
            reason=reason,
            source="llm_suggestion",
        )
