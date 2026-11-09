"""Favourite use cases shared by REST and the LLM/MCP tools (ADR-0173 point 3).

`add` and `remove` are idempotent on purpose: a tool call that is retried, which happens
routinely, must not flip the state back, which is why the tool never used the toggle.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProfileFavorite, Track
from app.operations.errors import TrackNotFound


async def _favorite(db: AsyncSession, profile_id: UUID, track_id: UUID) -> ProfileFavorite | None:
    return (
        await db.execute(
            select(ProfileFavorite).where(
                ProfileFavorite.profile_id == profile_id, ProfileFavorite.track_id == track_id
            )
        )
    ).scalar_one_or_none()


async def add(db: AsyncSession, profile_id: UUID, track_id: UUID) -> None:
    """Make a track a favourite. Already one: nothing changes. Raises `TrackNotFound`."""
    if await db.get(Track, track_id) is None:
        raise TrackNotFound(track_id)
    if await _favorite(db, profile_id, track_id) is None:
        db.add(ProfileFavorite(profile_id=profile_id, track_id=track_id))
        await db.commit()


async def remove(db: AsyncSession, profile_id: UUID, track_id: UUID) -> None:
    """Stop a track being a favourite. Not one: nothing changes."""
    favorite = await _favorite(db, profile_id, track_id)
    if favorite is not None:
        await db.delete(favorite)
        await db.commit()
