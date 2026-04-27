"""Generic external-album endpoints (works across discovery_context values).

Pass 1's ``/new-releases/{id}/dismiss`` is scoped to ``discovery_context='artist_new_release'``.
This file adds a context-agnostic dismiss endpoint usable for both #3
(``artist_new_release``) and #2 (``playlist_recommendation``) rows.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession, RequiredProfile
from app.db.models import ExternalAlbumCache

router = APIRouter(prefix="/external-albums", tags=["external-albums"])


@router.post("/{external_album_id}/dismiss")
async def dismiss_external_album(
    external_album_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> dict[str, Any]:
    """Dismiss an external album record by id (any discovery_context)."""
    result = await db.execute(
        select(ExternalAlbumCache).where(ExternalAlbumCache.id == external_album_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="External album not found")

    row.dismissed = True
    row.dismissed_by_profile_id = profile.id
    await db.commit()

    return {"status": "ok", "message": "External album dismissed"}
