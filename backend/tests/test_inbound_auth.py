"""Tests for the inbound server token (ADR-0045 phase 1).

The gate is a middleware rather than a dependency, which puts it outside the reach of the usual
route tests, and it fails *open* by design while ADR-0045 ships in phases. Both of those make it
easy for this to look present and do nothing, so what is asserted here is mostly the negative space:

1. **`/mcp` is covered.** It is served by `MCPDispatch` before the router sees the request, so a
   router-level dependency would have protected all 264 REST operations and left the one endpoint
   ADR-0043 exists to expose wide open. This is the reason the middleware ordering exists.
2. **Revocation actually revokes.** `AppSettingsService.update` skips `None` values unless the key
   is declared nullable, so `update(access_token=None)` was a no-op returning success — a revoke
   that reports success while the old token keeps working.
3. **The token is not readable from the unauthenticated settings surface.** `get_masked` masks an
   explicit list of keys, so a new secret is exposed by default.
"""

from __future__ import annotations

import pytest

from app.api.auth import (
    TOKEN_HEADER,
    extract_token,
    generate_token,
    path_requires_token,
    token_matches,
)


def _scope(headers: dict[str, str] | None = None, path: str = "/api/v1/tracks") -> dict:
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    }


class TestTokenComparison:
    def test_a_correct_token_matches(self):
        token = generate_token()
        assert token_matches(token, token)

    def test_a_wrong_token_does_not(self):
        assert not token_matches(generate_token(), generate_token())

    def test_absence_is_never_a_match(self):
        """`None` on either side must not pass.

        The "no token configured" case is a decision for the caller — it means *allow* during the
        phased rollout — and folding it in here would make an unconfigured server indistinguishable
        from a correct password.
        """
        token = generate_token()
        assert not token_matches(None, token)
        assert not token_matches(token, None)
        assert not token_matches(None, None)
        assert not token_matches("", token)

    def test_tokens_are_high_entropy_and_url_safe(self):
        token = generate_token()
        assert len(token) >= 40
        assert token == token.strip()
        assert "/" not in token and "+" not in token
        assert generate_token() != generate_token()


class TestWhichPathsAreGated:
    def test_mcp_is_gated(self):
        """The regression this whole middleware shape exists to prevent."""
        assert path_requires_token("/mcp")
        assert path_requires_token("/mcp/")

    def test_the_api_is_gated(self):
        assert path_requires_token("/api/v1/tracks")
        assert path_requires_token("/api/v1/playlists/abc/tracks")

    def test_the_spa_is_not(self):
        """A browser loading the app shell cannot set a header, and serving it is not the risk."""
        assert not path_requires_token("/")
        assert not path_requires_token("/assets/index-abc123.js")
        assert not path_requires_token("/embed")

    def test_the_bootstrap_endpoint_is_not(self):
        """Otherwise a server with no token has no way to be given one."""
        assert not path_requires_token("/api/v1/auth/token")

    def test_docs_and_health_are_not(self):
        assert not path_requires_token("/health")
        assert not path_requires_token("/openapi.json")
        assert not path_requires_token("/docs")


class TestTokenExtraction:
    def test_reads_the_custom_header(self):
        assert extract_token(_scope({TOKEN_HEADER: "abc"})) == "abc"

    def test_reads_a_bearer_header(self):
        """Some MCP hosts can set Authorization and nothing else."""
        assert extract_token(_scope({"Authorization": "Bearer abc"})) == "abc"
        assert extract_token(_scope({"Authorization": "bearer abc"})) == "abc"

    def test_ignores_other_authorization_schemes(self):
        assert extract_token(_scope({"Authorization": "Basic abc"})) is None

    def test_absent_is_none(self):
        assert extract_token(_scope()) is None
        assert extract_token(_scope({TOKEN_HEADER: "   "})) is None


class TestTheMiddlewareGate:
    """Exercises the middleware directly, since it sits outside the router."""

    @staticmethod
    async def _call(monkeypatch, configured: str | None, headers: dict[str, str], path: str):
        from app.api.auth import TokenAuthMiddleware

        class FakeSettings:
            access_token = configured

        class FakeService:
            def get(self):
                return FakeSettings()

        monkeypatch.setattr(
            "app.services.app_settings.get_app_settings_service", lambda: FakeService()
        )

        passed_through = False

        async def downstream(scope, receive, send):
            nonlocal passed_through
            passed_through = True

        sent: list[dict] = []

        async def send(message):
            sent.append(message)

        await TokenAuthMiddleware(downstream)(_scope(headers, path), None, send)
        status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
        return passed_through, status

    @pytest.mark.asyncio
    async def test_unconfigured_server_lets_everything_through(self, monkeypatch):
        """ADR-0045 ships in phases; enforcement before clients hold a token is an outage."""
        passed, status = await self._call(monkeypatch, None, {}, "/api/v1/tracks")
        assert passed and status is None

    @pytest.mark.asyncio
    async def test_configured_server_refuses_a_missing_token(self, monkeypatch):
        passed, status = await self._call(monkeypatch, "secret", {}, "/api/v1/tracks")
        assert not passed
        assert status == 401

    @pytest.mark.asyncio
    async def test_configured_server_refuses_a_wrong_token(self, monkeypatch):
        passed, status = await self._call(
            monkeypatch, "secret", {TOKEN_HEADER: "wrong"}, "/api/v1/tracks"
        )
        assert not passed and status == 401

    @pytest.mark.asyncio
    async def test_configured_server_accepts_the_right_token(self, monkeypatch):
        passed, status = await self._call(
            monkeypatch, "secret", {TOKEN_HEADER: "secret"}, "/api/v1/tracks"
        )
        assert passed and status is None

    @pytest.mark.asyncio
    async def test_mcp_is_refused_without_a_token(self, monkeypatch):
        """`MCPDispatch` answers /mcp before the router, so only the middleware can catch this."""
        passed, status = await self._call(monkeypatch, "secret", {}, "/mcp")
        assert not passed and status == 401

    @pytest.mark.asyncio
    async def test_preflight_is_never_refused(self, monkeypatch):
        """A browser asking which headers it may send cannot yet be sending one."""
        from app.api.auth import TokenAuthMiddleware

        class FakeSettings:
            access_token = "secret"

        monkeypatch.setattr(
            "app.services.app_settings.get_app_settings_service",
            lambda: type("S", (), {"get": lambda self: FakeSettings()})(),
        )
        passed = False

        async def downstream(scope, receive, send):
            nonlocal passed
            passed = True

        scope = _scope({}, "/api/v1/tracks")
        scope["method"] = "OPTIONS"
        await TokenAuthMiddleware(downstream)(scope, None, lambda m: None)
        assert passed, "preflight must reach CORS, or every cross-origin call fails opaquely"

    @pytest.mark.asyncio
    async def test_the_refusal_names_the_scheme(self, monkeypatch):
        from app.api.auth import TokenAuthMiddleware

        class FakeSettings:
            access_token = "secret"

        monkeypatch.setattr(
            "app.services.app_settings.get_app_settings_service",
            lambda: type("S", (), {"get": lambda self: FakeSettings()})(),
        )

        sent: list[dict] = []

        async def send(message):
            sent.append(message)

        async def downstream(scope, receive, send):
            pass

        await TokenAuthMiddleware(downstream)(_scope({}, "/api/v1/tracks"), None, send)
        start = next(m for m in sent if m["type"] == "http.response.start")
        headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
        assert "www-authenticate" in headers
        body = next(m for m in sent if m["type"] == "http.response.body")["body"]
        assert b'"error": true' in body.replace(b"True", b"true")


class TestRevocationActuallyRevokes:
    """`update()` skips None unless the key is declared nullable — so this was a silent no-op."""

    def test_setting_the_token_to_none_clears_it(self, tmp_path):
        from app.services.app_settings import AppSettingsService

        service = AppSettingsService(settings_path=tmp_path / "settings.json")
        service.update(access_token="a-real-token")
        assert service.get().access_token == "a-real-token"

        service.update(access_token=None)
        assert service.get().access_token is None, (
            "revoke reported success but the old token would still authenticate"
        )

    def test_revocation_survives_a_reload(self, tmp_path):
        from app.services.app_settings import AppSettingsService

        path = tmp_path / "settings.json"
        AppSettingsService(settings_path=path).update(access_token="a-real-token")
        AppSettingsService(settings_path=path).update(access_token=None)
        assert AppSettingsService(settings_path=path).get().access_token is None


class TestTheTokenIsNotLeaked:
    def test_masked_settings_do_not_contain_it(self, tmp_path):
        """`/api/v1/settings` is one of the operations with no security requirement today."""
        from app.services.app_settings import AppSettingsService

        service = AppSettingsService(settings_path=tmp_path / "settings.json")
        token = generate_token()
        service.update(access_token=token)

        masked = service.get_masked()
        assert token not in str(masked)
        # Not even a prefix: unlike the outbound keys, no part of this one aids an operator.
        assert token[:4] not in str(masked["access_token"])
