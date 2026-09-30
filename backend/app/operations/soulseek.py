"""Soulseek operations (ADR-0116, restructured under ADR-0130)."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.soulseek import SoulseekGateway, SoulseekStatus


@dataclass(frozen=True)
class SoulseekProbe:
    """What the configured slskd said when asked, or that there is none to ask."""

    configured: bool
    url: str | None = None
    status: SoulseekStatus | None = None


class ProbeSoulseekStatus:
    """The settings panel's "test connection": ask slskd who it is, briefly.

    Never raises for an unreachable or logged-out client — those are answers, carried in
    `SoulseekStatus`, and the panel shows them as such. The five-second timeout is because this
    runs while an operator is watching a button.
    """

    TIMEOUT_SECONDS = 5.0

    def __init__(self, soulseek: SoulseekGateway) -> None:
        self._soulseek = soulseek

    async def __call__(self) -> SoulseekProbe:
        if not self._soulseek.configured:
            return SoulseekProbe(configured=False)
        async with self._soulseek.client(timeout=self.TIMEOUT_SECONDS) as slsk:
            status = await slsk.status()
        return SoulseekProbe(configured=True, url=self._soulseek.url, status=status)
