"""Actionable errors carry a stable `code` (ADR-0129 point 6).

The web client used to decide "prompt for a token" versus "drop the dead profile" by searching the
error's *prose* — and searched the wrong key: the profile 401 goes through the `HTTPException`
handler, which puts its sentence in `message` and omits `detail`, while the interceptor read
`detail`. So the profile branch never fired in production, and the test that "pinned" it faked the
envelope with `detail` set. These tests read the envelope the server actually sends.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.exceptions import ErrorCode, FamiliarError, InvalidProfileError


class TestTheEnvelope:
    def test_a_dead_profile_is_401_with_a_code_and_no_detail(self, client: TestClient) -> None:
        r = client.get(
            "/api/v1/playlists", headers={"X-Profile-ID": "00000000-0000-0000-0000-000000000000"}
        )
        assert r.status_code == 401
        body = r.json()
        assert body["code"] == "INVALID_PROFILE"
        assert "detail" not in body, "the sentence is in `message`; nothing should rely on `detail`"

    def test_an_error_without_a_code_omits_the_key(self, client: TestClient) -> None:
        body = client.get("/api/v1/tracks/00000000-0000-0000-0000-000000000000").json()
        assert body["status_code"] == 404
        assert "code" not in body, "absent, not null — the envelope's rule for optional keys"

    def test_the_codes_the_client_switches_on_exist_and_are_stable(self) -> None:
        assert ErrorCode.SERVER_TOKEN_REQUIRED == "SERVER_TOKEN_REQUIRED"
        assert ErrorCode.INVALID_PROFILE == "INVALID_PROFILE"
        assert InvalidProfileError.code is ErrorCode.INVALID_PROFILE
        assert InvalidProfileError.status_code == 401
        assert FamiliarError.code is None


class TestTheTokenMiddleware:
    @pytest.mark.asyncio
    async def test_a_missing_token_carries_its_code(self, monkeypatch) -> None:
        from app.api.auth import TokenAuthMiddleware

        class FakeSettings:
            access_token = "secret"

        class FakeService:
            def get(self):
                return FakeSettings()

        monkeypatch.setattr(
            "app.services.app_settings.get_app_settings_service", lambda: FakeService()
        )
        sent: list[dict] = []

        async def send(message):
            sent.append(message)

        async def downstream(scope, receive, send):
            raise AssertionError("must not pass through")

        scope = {"type": "http", "path": "/api/v1/tracks", "headers": [], "state": {}}
        await TokenAuthMiddleware(downstream)(scope, None, send)
        body = json.loads(next(m for m in sent if m["type"] == "http.response.body")["body"])
        assert body["status_code"] == 401
        assert body["code"] == "SERVER_TOKEN_REQUIRED"
