"""The application's long-lived resources, assembled once and handed in (ADR-0130 point 2).

`Services` is what `create_app` receives and what routes, the MCP executor and the background
manager are given — never something they look up. **It is empty, and that is a pause, not the
finished state.** Soulseek was the first domain moved in, because it touched every boundary the
record names (an external HTTP service, settings-gated presence, a background poller, a route); it
left Familiar with ADR-0154, and the next domain migrated takes its place. Redis, the engine,
executors and the provider adapters join as their domains are moved; the `get_*_service()` getters
they sit behind today stay until then. ADR-0130's Implementation block has the pattern.

`build_services` is the composition root: the one place allowed to reach a singleton (such as
`get_app_settings_service`) on a domain's behalf, so the domain's own gateway knows only a narrow
configuration protocol a test can satisfy with plain values.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True)
class Services:
    @classmethod
    def unconfigured(cls) -> Services:
        """A container in which no integration is set up — the named null capability.

        What a `ToolExecutor` gets when constructed without one (most executor tests), so a
        gateway-backed tool answers as a real server without that integration would, rather
        than failing on a missing attribute.
        """
        return cls()

    async def aclose(self) -> None:
        """Called from the application's lifespan on shutdown; closes each gateway it holds."""


def build_services(settings: Settings) -> Services:
    """Production wiring. `settings` is unused until a moved domain needs a value from it."""
    del settings
    return Services()
