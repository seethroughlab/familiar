"""Soulseek status — the settings panel's "test connection" (ADR-0116).

One read-only endpoint. Everything that *does* something with slskd (search, enqueue) is on the
MCP surface, where the listener's host drives it in conversation; the web app only needs to know
whether the address the operator typed is a logged-in slskd.

The route is the shape ADR-0130 point 3 asks for: it receives the operation, invokes it, and
serialises the answer. It does not know where slskd is or how to reach it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import probe_soulseek_status
from app.operations.soulseek import ProbeSoulseekStatus

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
async def get_soulseek_status(
    probe: Annotated[ProbeSoulseekStatus, Depends(probe_soulseek_status)],
) -> SoulseekStatusResponse:
    """Probe the configured slskd. Never errors: an unreachable client is a status, not a failure."""
    result = await probe()
    if result.status is None:
        return SoulseekStatusResponse(configured=result.configured, url=result.url)
    return SoulseekStatusResponse(configured=True, url=result.url, **result.status.to_dict())
