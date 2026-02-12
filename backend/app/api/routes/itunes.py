"""iTunes preview URL resolution for external tracks."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import DbSession
from app.db.models import ExternalTrack
from app.services.itunes import search_preview

router = APIRouter(prefix="/external-tracks", tags=["external-tracks"])


class PreviewUrlResponse(BaseModel):
    """Preview URL resolution response."""

    preview_url: str | None = None
    preview_source: str | None = None


@router.get("/{external_track_id}/preview-url", response_model=PreviewUrlResponse)
async def resolve_preview_url(
    external_track_id: UUID,
    db: DbSession,
) -> PreviewUrlResponse:
    """Resolve a preview URL for an external track.

    Checks cached value first, otherwise searches iTunes and caches the result.
    """
    ext = await db.get(ExternalTrack, external_track_id)
    if not ext:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="External track not found",
        )

    # Check cache in external_data
    ext_data = ext.external_data or {}
    if "itunes_preview_url" in ext_data:
        return PreviewUrlResponse(
            preview_url=ext_data.get("itunes_preview_url"),
            preview_source="itunes" if ext_data.get("itunes_preview_url") else None,
        )

    # Search iTunes
    result = await search_preview(ext.artist, ext.title)

    # Cache result (even if None, to avoid repeated lookups)
    if ext.external_data is None:
        ext.external_data = {}

    if result:
        ext.external_data = {
            **ext.external_data,
            "itunes_preview_url": result["preview_url"],
            "itunes_track_id": result.get("itunes_track_id"),
            "itunes_url": result.get("itunes_url"),
            "itunes_artwork_url": result.get("artwork_url"),
        }
    else:
        ext.external_data = {
            **ext.external_data,
            "itunes_preview_url": None,
        }

    await db.commit()

    preview_url = result["preview_url"] if result else None
    return PreviewUrlResponse(
        preview_url=preview_url,
        preview_source="itunes" if preview_url else None,
    )
