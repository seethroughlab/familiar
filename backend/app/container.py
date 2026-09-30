"""The application's long-lived resources, assembled once and handed in (ADR-0130 point 2).

`Services` is what `create_app` receives and what routes, the MCP executor and the background
manager are given — never something they look up. Today it holds one entry, because the migration
follows touched domains (point 8) and Soulseek is the first: an external HTTP service, settings-
gated presence, a background poller and a route surface, which is every boundary the record names.
Redis, the engine, executors and the other provider adapters join as their domains are moved; the
`get_*_service()` getters they sit behind today stay until then.

`build_services` is the composition root. It is the one place allowed to reach a singleton
(`get_app_settings_service`) on the domain's behalf, so that `SoulseekGateway` itself only knows
a `SoulseekConfiguration` — and a test can give it one made of two strings.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.services.soulseek import SoulseekGateway


@dataclass(frozen=True)
class Services:
    soulseek: SoulseekGateway

    @classmethod
    def unconfigured(cls) -> Services:
        """A container in which no integration is set up — the named null capability.

        What a `ToolExecutor` gets when constructed without one (most executor tests), so a
        Soulseek tool answers "no slskd is configured" exactly as a real server without one
        would, rather than failing on a missing attribute.
        """
        return cls(soulseek=SoulseekGateway(NoSoulseek()))

    async def aclose(self) -> None:
        """Called from the application's lifespan on shutdown."""
        await self.soulseek.aclose()


class NoSoulseek:
    """`SoulseekConfiguration` for a server with no slskd."""

    def soulseek_url(self) -> str | None:
        return None

    def soulseek_api_key(self) -> str | None:
        return None


class SettingsBackedSoulseekConfiguration:
    """`SoulseekConfiguration` over the operator's settings — JSON over environment over default."""

    def soulseek_url(self) -> str | None:
        from app.services.app_settings import get_app_settings_service

        return get_app_settings_service().get_effective("soulseek_url") or None

    def soulseek_api_key(self) -> str | None:
        from app.services.app_settings import get_app_settings_service

        return get_app_settings_service().get_effective("soulseek_api_key") or None


def build_services(settings: Settings) -> Services:
    """Production wiring. `settings` is unused until a moved domain needs a value from it."""
    del settings
    return Services(soulseek=SoulseekGateway(SettingsBackedSoulseekConfiguration()))
