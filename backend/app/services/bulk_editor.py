"""Bulk metadata editing service.

Provides operations for editing metadata across multiple tracks at once.
"""

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Track

logger = logging.getLogger(__name__)

# Fields that can be bulk edited
EDITABLE_FIELDS = [
    # Basic metadata
    "title",
    "artist",
    "album",
    "album_artist",
    "track_number",
    "disc_number",
    "year",
    "genre",
    # Extended metadata
    "composer",
    "conductor",
    "lyricist",
    "grouping",
    "comment",
    # Sort fields
    "sort_artist",
    "sort_album",
    "sort_title",
    # Lyrics
    "lyrics",
]


@dataclass
class BulkEditError:
    """Error details for a single track in bulk edit."""

    track_id: str
    file_path: str
    error: str


@dataclass
class BulkEditResult:
    """Result of a bulk edit operation."""

    total: int
    successful: int
    failed: int
    errors: list[BulkEditError] = field(default_factory=list)
    fields_updated: list[str] = field(default_factory=list)


class BulkEditorService:
    """Service for bulk metadata editing operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def apply_to_tracks(
        self,
        track_ids: list[UUID],
        metadata: dict[str, Any],
    ) -> BulkEditResult:
        """Apply metadata changes to multiple tracks.

        Args:
            track_ids: List of track UUIDs to update
            metadata: Dict of field -> value to apply. Only non-None values are applied.

        Returns:
            BulkEditResult with success/failure counts and any errors
        """
        # Filter to only include valid, non-None values
        updates = {
            k: v for k, v in metadata.items() if k in EDITABLE_FIELDS and v is not None
        }

        if not updates:
            return BulkEditResult(
                total=len(track_ids),
                successful=0,
                failed=0,
                errors=[],
                fields_updated=[],
            )

        # Fetch all tracks
        stmt = select(Track).where(Track.active_filter(), Track.id.in_(track_ids))
        result = await self.db.execute(stmt)
        tracks = list(result.scalars().all())

        if not tracks:
            return BulkEditResult(
                total=len(track_ids),
                successful=0,
                failed=len(track_ids),
                errors=[
                    BulkEditError(
                        track_id=str(tid), file_path="", error="Track not found"
                    )
                    for tid in track_ids
                ],
                fields_updated=[],
            )

        successful = 0
        errors: list[BulkEditError] = []

        for track in tracks:
            try:
                # Update database
                for field_name, value in updates.items():
                    setattr(track, field_name, value)

                successful += 1

            except Exception as e:
                logger.error(f"Error updating track {track.id}: {e}")
                errors.append(
                    BulkEditError(
                        track_id=str(track.id),
                        file_path=track.file_path,
                        error=str(e),
                    )
                )

        # Commit all database changes
        await self.db.commit()

        return BulkEditResult(
            total=len(track_ids),
            successful=successful,
            failed=len(errors),
            errors=errors,
            fields_updated=list(updates.keys()),
        )

    async def get_common_values(self, track_ids: list[UUID]) -> dict[str, Any]:
        """Get field values that are identical across all tracks.

        For fields with different values across tracks, returns None (indicating "mixed").

        Args:
            track_ids: List of track UUIDs to compare

        Returns:
            Dict of {field: value} where value is the common value or None if mixed
        """
        if not track_ids:
            return {}

        stmt = select(Track).where(Track.active_filter(), Track.id.in_(track_ids))
        result = await self.db.execute(stmt)
        tracks = list(result.scalars().all())

        if not tracks:
            return {}

        # Initialize with first track's values
        common: dict[str, Any] = {}
        first_track = tracks[0]

        for field_name in EDITABLE_FIELDS:
            common[field_name] = getattr(first_track, field_name, None)

        # Compare with remaining tracks
        for track in tracks[1:]:
            for field_name in EDITABLE_FIELDS:
                if common[field_name] is not None:
                    track_value = getattr(track, field_name, None)
                    if track_value != common[field_name]:
                        # Values differ - mark as mixed (None)
                        common[field_name] = None

        return common

    async def get_tracks_metadata(
        self, track_ids: list[UUID]
    ) -> list[dict[str, Any]]:
        """Get full metadata for multiple tracks.

        Args:
            track_ids: List of track UUIDs

        Returns:
            List of dicts with track metadata
        """
        stmt = select(Track).where(Track.active_filter(), Track.id.in_(track_ids))
        result = await self.db.execute(stmt)
        tracks = list(result.scalars().all())

        return [
            {
                "id": str(track.id),
                "file_path": track.file_path,
                **{field: getattr(track, field, None) for field in EDITABLE_FIELDS},
            }
            for track in tracks
        ]
