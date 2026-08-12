"""Service for managing proposed metadata changes.

Handles the lifecycle of proposed changes: create, preview, approve, reject, apply, undo.
Changes update database records only.
"""

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChangeScope,
    ChangeSource,
    ChangeStatus,
    ProposedChange,
    Track,
)
from app.services import metadata_overrides
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


@dataclass
class ChangePreview:
    """Preview of what applying a change would do."""

    change_id: UUID
    target_description: str  # "Track: Song Name by Artist" or "Album: Album Name"
    field: str | None
    old_value: Any
    new_value: Any
    tracks_affected: int
    files_affected: list[str]  # File paths that would be modified
    scope: ChangeScope


@dataclass
class ApplyResult:
    """Result of applying a single change."""

    change_id: UUID
    success: bool
    error: str | None = None
    db_updated: bool = False


@dataclass
class ChangeStats:
    """Summary statistics for proposed changes."""

    pending: int
    rejected: int
    applied: int


class ProposedChangesService:
    """Manages the lifecycle of proposed metadata changes."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_change(
        self,
        change_type: str,
        target_type: str,
        target_ids: list[str],
        source: ChangeSource,
        new_value: Any,
        field: str | None = None,
        old_value: Any = None,
        source_detail: str | None = None,
        confidence: float = 1.0,
        reason: str | None = None,
        scope: ChangeScope = ChangeScope.DB_ONLY,
    ) -> ProposedChange:
        """Create a new proposed change."""
        change = ProposedChange(
            change_type=change_type,
            target_type=target_type,
            target_ids=target_ids,
            field=field,
            old_value=old_value,
            new_value=new_value,
            source=source,
            source_detail=source_detail,
            confidence=confidence,
            reason=reason,
            scope=scope,
            status=ChangeStatus.PENDING,
        )
        self.db.add(change)
        await self.db.commit()
        await self.db.refresh(change)
        logger.info(f"Created proposed change {change.id}: {change_type} for {len(target_ids)} targets")
        return change

    async def get_by_id(self, change_id: UUID) -> ProposedChange | None:
        """Get a single change by ID."""
        result = await self.db.execute(
            select(ProposedChange).where(ProposedChange.id == change_id)
        )
        return result.scalar_one_or_none()

    async def get_pending(self, limit: int = 50, offset: int = 0) -> list[ProposedChange]:
        """Get pending changes, ordered by creation date."""
        result = await self.db.execute(
            select(ProposedChange)
            .where(ProposedChange.status == ChangeStatus.PENDING)
            .order_by(ProposedChange.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_by_status(
        self,
        status: ChangeStatus,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProposedChange]:
        """Get changes by status."""
        result = await self.db.execute(
            select(ProposedChange)
            .where(ProposedChange.status == status)
            .order_by(ProposedChange.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_all(self, limit: int = 50, offset: int = 0) -> list[ProposedChange]:
        """Get all changes regardless of status, ordered by created_at desc."""
        result = await self.db.execute(
            select(ProposedChange)
            .order_by(ProposedChange.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_track(self, track_id: UUID) -> list[ProposedChange]:
        """Get all changes affecting a specific track."""
        track_id_str = str(track_id)
        result = await self.db.execute(
            select(ProposedChange)
            .where(ProposedChange.target_ids.contains([track_id_str]))
            .order_by(ProposedChange.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_stats(self) -> ChangeStats:
        """Get summary statistics for all changes."""
        result = await self.db.execute(
            select(
                ProposedChange.status,
                func.count(ProposedChange.id).label("count"),
            ).group_by(ProposedChange.status)
        )
        rows = result.all()
        counts: dict[ChangeStatus, int] = {}
        for row in rows:
            counts[row.status] = row.count  # type: ignore[assignment]
        return ChangeStats(
            pending=counts.get(ChangeStatus.PENDING, 0),
            rejected=counts.get(ChangeStatus.REJECTED, 0),
            applied=counts.get(ChangeStatus.APPLIED, 0),
        )

    async def reject(self, change_id: UUID) -> ProposedChange | None:
        """Reject a change."""
        change = await self.get_by_id(change_id)
        if not change:
            return None

        if change.status != ChangeStatus.PENDING:
            logger.warning(f"Cannot reject change {change_id}: status is {change.status}")
            return change

        change.status = ChangeStatus.REJECTED
        await self.db.commit()
        await self.db.refresh(change)
        logger.info(f"Rejected change {change_id}")
        return change

    @staticmethod
    def _build_target_description(change: ProposedChange, tracks: list[Track]) -> str:
        """Build a human-readable description of a change's target."""
        if change.target_type == "album" and tracks:
            first_track = tracks[0]
            return f"Album: {first_track.album} by {first_track.album_artist or first_track.artist}"
        elif tracks:
            if len(tracks) == 1:
                t = tracks[0]
                return f"Track: {t.title} by {t.artist}"
            else:
                return f"{len(tracks)} tracks"
        else:
            return f"{len(change.target_ids)} items"

    async def enrich_with_descriptions(
        self, changes: list[ProposedChange]
    ) -> dict[UUID, str]:
        """Batch-load tracks and build target descriptions for a list of changes.

        Returns a dict mapping change ID -> target_description string.
        """
        if not changes:
            return {}

        # Collect all unique track IDs across all changes
        all_track_ids: set[UUID] = set()
        for change in changes:
            for tid in change.target_ids:
                all_track_ids.add(UUID(tid))

        # Single batch query for all tracks
        tracks_by_id: dict[UUID, Track] = {}
        if all_track_ids:
            result = await self.db.execute(
                select(Track).where(Track.id.in_(list(all_track_ids)))
            )
            for track in result.scalars().all():
                tracks_by_id[track.id] = track

        # Build descriptions
        descriptions: dict[UUID, str] = {}
        for change in changes:
            change_tracks = [
                tracks_by_id[UUID(tid)]
                for tid in change.target_ids
                if UUID(tid) in tracks_by_id
            ]
            descriptions[change.id] = self._build_target_description(
                change, change_tracks
            )

        return descriptions

    async def preview(self, change_id: UUID) -> ChangePreview | None:
        """Generate a preview of what applying a change would do."""
        change = await self.get_by_id(change_id)
        if not change:
            return None

        # Get the tracks affected
        track_ids = [UUID(tid) for tid in change.target_ids]
        result = await self.db.execute(
            select(Track).where(Track.id.in_(track_ids))
        )
        tracks = list(result.scalars().all())

        description = self._build_target_description(change, tracks)

        return ChangePreview(
            change_id=change.id,
            target_description=description,
            field=change.field,
            old_value=change.old_value,
            new_value=change.new_value,
            tracks_affected=len(tracks),
            files_affected=[t.file_path for t in tracks],
            scope=change.scope,
        )

    async def apply(
        self,
        change_id: UUID,
    ) -> ApplyResult:
        """Apply a change (DB-only update)."""
        change = await self.get_by_id(change_id)
        if not change:
            return ApplyResult(
                change_id=change_id,
                success=False,
                error="Change not found",
            )

        if change.status != ChangeStatus.PENDING:
            return ApplyResult(
                change_id=change_id,
                success=False,
                error=f"Cannot apply change with status {change.status.value}",
            )

        result = ApplyResult(change_id=change_id, success=True)

        try:
            # Get affected tracks
            track_ids = [UUID(tid) for tid in change.target_ids]
            db_result = await self.db.execute(
                select(Track).where(Track.id.in_(track_ids))
            )
            tracks = list(db_result.scalars().all())

            if not tracks:
                return ApplyResult(
                    change_id=change_id,
                    success=False,
                    error="No tracks found for this change",
                )

            # Update database
            if change.change_type == "metadata" and change.field:
                await self._apply_metadata_to_db(tracks, change.field, change.new_value)
                result.db_updated = True

            # Mark change as applied
            change.status = ChangeStatus.APPLIED
            change.applied_at = utcnow()
            await self.db.commit()

            logger.info(f"Applied change {change_id}")

        except Exception as e:
            logger.error(f"Failed to apply change {change_id}: {e}")
            result.success = False
            result.error = str(e)
            await self.db.rollback()

        return result

    async def _apply_metadata_to_db(
        self,
        tracks: list[Track],
        field: str,
        new_value: Any,
    ) -> None:
        """Update the database with new metadata values."""
        for track in tracks:
            if hasattr(track, field):
                setattr(track, field, new_value)
                # Accepting a suggestion is a choice, so it outranks the file like any other edit
                # (ADR-0051 point 7). Without this, a corrected artist name from an accepted change
                # was undone by the next rescan of a re-tagged file — the same defect as a hand
                # edit, reached by a different route.
                track.metadata_overrides = metadata_overrides.record(
                    track.metadata_overrides, {field: new_value}
                )
        await self.db.commit()

    async def apply_batch(
        self,
        change_ids: list[UUID],
    ) -> list[ApplyResult]:
        """Apply multiple changes."""
        results = []
        for change_id in change_ids:
            result = await self.apply(change_id)
            results.append(result)
        return results

    async def undo(self, change_id: UUID) -> ApplyResult:
        """Undo an applied change by reverting to old values.

        Note: Only reverts database changes. File changes require re-syncing.
        """
        change = await self.get_by_id(change_id)
        if not change:
            return ApplyResult(
                change_id=change_id,
                success=False,
                error="Change not found",
            )

        if change.status != ChangeStatus.APPLIED:
            return ApplyResult(
                change_id=change_id,
                success=False,
                error=f"Cannot undo change with status {change.status.value}",
            )

        if not change.old_value:
            return ApplyResult(
                change_id=change_id,
                success=False,
                error="No old value stored - cannot undo",
            )

        try:
            # Get affected tracks
            track_ids = [UUID(tid) for tid in change.target_ids]
            db_result = await self.db.execute(
                select(Track).where(Track.id.in_(track_ids))
            )
            tracks = list(db_result.scalars().all())

            # Revert database values
            if change.change_type == "metadata" and change.field:
                # old_value might be a dict mapping track_id -> old_value
                # or a single value for all tracks
                if isinstance(change.old_value, dict):
                    for track in tracks:
                        old_val = change.old_value.get(str(track.id))
                        if old_val is not None and hasattr(track, change.field):
                            setattr(track, change.field, old_val)
                            track.metadata_overrides = metadata_overrides.forget(
                                track.metadata_overrides, [change.field]
                            )
                else:
                    for track in tracks:
                        if hasattr(track, change.field):
                            setattr(track, change.field, change.old_value)
                            track.metadata_overrides = metadata_overrides.forget(
                                track.metadata_overrides, [change.field]
                            )

                # **An undo is a retraction, not a new opinion** (ADR-0051 point 7). The field goes
                # back to following the file rather than being pinned to a value nobody chose —
                # otherwise the first accepted suggestion would freeze it forever and this button
                # would be a lie. This is currently the only way a field stops being overridden.

            # Mark as pending again (can be re-applied if needed)
            change.status = ChangeStatus.PENDING
            change.applied_at = None
            await self.db.commit()

            logger.info(f"Undid change {change_id}")
            return ApplyResult(
                change_id=change_id,
                success=True,
                db_updated=True,
            )

        except Exception as e:
            logger.error(f"Failed to undo change {change_id}: {e}")
            await self.db.rollback()
            return ApplyResult(
                change_id=change_id,
                success=False,
                error=str(e),
            )

    async def delete(self, change_id: UUID) -> bool:
        """Delete a proposed change."""
        change = await self.get_by_id(change_id)
        if not change:
            return False

        await self.db.delete(change)
        await self.db.commit()
        logger.info(f"Deleted change {change_id}")
        return True
