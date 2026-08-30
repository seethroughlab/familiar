"""Update notification endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/updates", tags=["system"])


class UpdateStatus(BaseModel):
    update_available: bool
    current_version: str
    latest_version: str | None = None
    release_url: str | None = None
    release_name: str | None = None
    published_at: str | None = None
    channel: str
    checked_at: str | None = None
    error: str | None = None


@router.get("", response_model=UpdateStatus)
async def get_update_status() -> UpdateStatus:
    """Get cached update check result (no GitHub hit)."""
    from app.services.update_checker import get_cached_result

    cached = get_cached_result()
    if cached:
        return UpdateStatus(**cached)

    from app.config import get_app_version
    from app.services.app_settings import get_app_settings_service

    return UpdateStatus(
        update_available=False,
        current_version=get_app_version(),
        channel=get_app_settings_service().get().update_channel,
    )


@router.post("/check", response_model=UpdateStatus)
async def trigger_update_check() -> UpdateStatus:
    """Trigger a fresh update check against GitHub."""
    from app.services.update_checker import check_for_updates

    result = await check_for_updates()
    return UpdateStatus(**result)
