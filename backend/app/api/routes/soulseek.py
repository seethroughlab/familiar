"""Soulseek status — the settings panel's "test connection" (ADR-0116).

One read-only endpoint. Everything that *does* something with slskd (search, enqueue) is on the
MCP surface, where the listener's host drives it in conversation; the web app only needs to know
whether the address the operator typed is a logged-in slskd.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.app_settings import get_app_settings_service
from app.services.soulseek import SoulseekService

router = APIRouter(prefix="/soulseek", tags=["soulseek"])


class SoulseekStatusResponse(BaseModel):
    """What the configured slskd said when asked, or why it could not be asked."""

    configured: bool
    url: str | None = None
    reachable: bool = False
    logged_in: bool = False
    username: str | None = None
    version: str | None = None
    shared_files: int | None = None
    error: str | None = None


@router.get("/status", response_model=SoulseekStatusResponse)
async def get_soulseek_status() -> SoulseekStatusResponse:
    """Probe the configured slskd. Never errors: an unreachable client is a status, not a failure."""
    settings = get_app_settings_service()
    url = settings.get_effective("soulseek_url")
    if not url:
        return SoulseekStatusResponse(configured=False)

    slsk = SoulseekService(url, settings.get_effective("soulseek_api_key"), timeout=5.0)
    try:
        status = await slsk.status()
    finally:
        await slsk.close()
    return SoulseekStatusResponse(configured=True, url=url, **status.to_dict())
