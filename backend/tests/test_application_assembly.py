"""The backend is assembled from explicit dependencies (ADR-0130), Soulseek slice.

`create_app(settings, services)` is the seam; these prove it is a real one — two applications
built with two containers answer the same request differently, with no monkeypatch and no
dependency override — and that the operation behind the route is a plain object a test can
construct.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import Services, build_services
from app.operations.soulseek import ProbeSoulseekStatus
from app.services.soulseek import SoulseekGateway
from tests.test_soulseek import FakeSlskd, FakeSoulseekConfiguration, services_for


def _app(services: Services):
    from app.main import create_app

    return create_app(Settings(), services)


class TestCreateApp:
    def test_the_container_it_is_given_is_the_one_it_holds(self):
        services = Services.unconfigured()
        app = _app(services)
        assert app.state.services is services

    def test_two_containers_two_answers_no_patching(self):
        """The route reads the container, so the container decides the answer."""
        configured = _app(services_for(httpx.MockTransport(FakeSlskd().handler)))
        unconfigured = _app(Services.unconfigured())
        # No `with`: the lifespan (migration preflight, background manager) is not what is
        # under test, and TestClient only runs it inside the context manager.
        yes = TestClient(configured).get("/api/v1/soulseek/status").json()
        no = TestClient(unconfigured).get("/api/v1/soulseek/status").json()
        assert yes["configured"] is True and yes["logged_in"] is True
        assert no == {
            "configured": False, "url": None, "reachable": False, "logged_in": False,
            "username": None, "version": None, "shared_files": None, "error": None,
        }

    def test_the_mcp_app_is_built_over_the_same_container(self):
        from app.mcp.server import MCPDispatch

        app = _app(Services.unconfigured())
        installed = [m for m in app.user_middleware if m.cls is MCPDispatch]
        assert installed and installed[0].kwargs["mcp_app"] is app.state.mcp_app

    def test_production_wiring_reads_the_operator_settings(self, tmp_path, monkeypatch):
        """`build_services` is the one place that reaches the settings singleton."""
        from app.services.app_settings import AppSettingsService

        svc = AppSettingsService(settings_path=tmp_path / "settings.json")
        monkeypatch.setattr("app.services.app_settings.get_app_settings_service", lambda: svc)
        monkeypatch.setattr("app.config.settings.soulseek_url", None)
        services = build_services(Settings())
        assert services.soulseek.configured is False
        svc.update(soulseek_url="http://slskd:5030")
        assert services.soulseek.configured is True, "read per call, not captured at build"


class TestProbeSoulseekStatus:
    @pytest.mark.asyncio
    async def test_unconfigured_is_an_answer_and_no_request(self):
        calls: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(500)

        gateway = SoulseekGateway(
            FakeSoulseekConfiguration(None), transport=httpx.MockTransport(record)
        )
        probe = await ProbeSoulseekStatus(gateway)()
        assert probe.configured is False and probe.status is None
        assert calls == []

    @pytest.mark.asyncio
    async def test_configured_asks_slskd_briefly(self):
        gateway = SoulseekGateway(
            FakeSoulseekConfiguration(), transport=httpx.MockTransport(FakeSlskd().handler)
        )
        probe = await ProbeSoulseekStatus(gateway)()
        assert probe.configured is True
        assert probe.url == "http://slskd:5030"
        assert probe.status is not None and probe.status.username == "otterbad"

    @pytest.mark.asyncio
    async def test_an_unreachable_slskd_is_a_status_not_an_exception(self):
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        gateway = SoulseekGateway(FakeSoulseekConfiguration(), transport=httpx.MockTransport(refuse))
        probe = await ProbeSoulseekStatus(gateway)()
        assert probe.status is not None
        assert probe.status.reachable is False
        assert "Nothing answered" in (probe.status.error or "")
