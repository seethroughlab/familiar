"""The backend is assembled from explicit dependencies (ADR-0130).

`create_app(settings, services)` is the seam. The container is empty since Soulseek left with
ADR-0154, so what is proved here is the wiring: the application holds the container it was given,
and the MCP app is built over the same one. The proof that two containers give two answers with no
monkeypatch returns with the next domain moved in — that is the test to write first.
"""

from __future__ import annotations

from app.config import Settings
from app.container import Services, build_services


def _app(services: Services):
    from app.main import create_app

    return create_app(Settings(), services)


class TestCreateApp:
    def test_the_container_it_is_given_is_the_one_it_holds(self):
        services = Services.unconfigured()
        app = _app(services)
        assert app.state.services is services

    def test_the_mcp_app_is_built_over_the_same_container(self):
        from app.mcp.server import MCPDispatch

        app = _app(Services.unconfigured())
        installed = [m for m in app.user_middleware if m.cls is MCPDispatch]
        assert installed and installed[0].kwargs["mcp_app"] is app.state.mcp_app

    def test_production_wiring_builds_a_container(self):
        assert isinstance(build_services(Settings()), Services)
