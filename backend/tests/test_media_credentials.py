"""ADR-0176 Phase 2: media accepts a header, a cookie or a server-signed URL.

Nothing is *required* yet (`MEDIA_ENFORCED` is off until no App Store build lacks the header), so the
gate tests switch enforcement on: they are the exit condition Phase 4 will rely on, written while the
code is fresh. One test pins that, today, media is still served without a credential.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.api import media_credentials as media
from app.api.auth import TOKEN_HEADER, TokenAuthMiddleware

TOKEN = "current-token"
STREAM = "/api/v1/tracks/6f1c2a52-6d4e-4f55-9a0b-2b8f3f0c1d11/stream"
NOW = 1_800_000_000


def _settings(monkeypatch, token):
    monkeypatch.setattr(
        "app.services.app_settings.get_app_settings_service",
        lambda: type("S", (), {"get": lambda self: type("A", (), {"access_token": token})()})(),
    )


def _scope(path=STREAM, method="GET", headers=None, query=b""):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query,
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("192.168.1.20", 50000),
    }


async def _gate(monkeypatch, scope, *, token=TOKEN, enforced=True):
    _settings(monkeypatch, token)
    monkeypatch.setattr(media, "MEDIA_ENFORCED", enforced)
    from app import exposure

    exposure.record(exposure.Exposure.OPEN)  # a tokenless server's own rules are ADR-0171's, not ours
    passed, sent = False, []

    async def downstream(scope, receive, send):
        nonlocal passed
        passed = True

    async def send(message):
        sent.append(message)

    await TokenAuthMiddleware(downstream)(scope, None, send)
    return passed, next((m["status"] for m in sent if m["type"] == "http.response.start"), None)


def _signed_query(path=STREAM, token=TOKEN, lifetime_s=600, now=None):
    return urlsplit(media.sign_url(f"http://nas:4400{path}", token, lifetime_s=lifetime_s, now=now)).query


# ── Signed URLs ─────────────────────────────────────────────────────────────────────────────────


def test_a_signed_url_verifies_until_it_expires():
    query = _signed_query(now=NOW)
    assert media.signature_valid(STREAM, query, TOKEN, now=NOW + 599)
    assert not media.signature_valid(STREAM, query, TOKEN, now=NOW + 601)


def test_a_signature_is_for_one_path():
    other = STREAM.replace("6f1c", "0000")
    assert not media.signature_valid(other, _signed_query(now=NOW), TOKEN, now=NOW)


def test_rotation_invalidates_every_signature():
    assert not media.signature_valid(STREAM, _signed_query(now=NOW), "rotated", now=NOW)


def test_a_moved_expiry_is_refused():
    params = parse_qs(_signed_query(now=NOW))
    forged = f"exp={int(params['exp'][0]) + 86400}&sig={params['sig'][0]}"
    assert not media.signature_valid(STREAM, forged, TOKEN, now=NOW)


def test_signing_keeps_the_query_and_never_duplicates_exp_or_sig():
    url = media.sign_url(f"http://nas:4400{STREAM}?format=aac&exp=1&sig=x", TOKEN, lifetime_s=60, now=NOW)
    params = parse_qs(urlsplit(url).query)
    assert params["format"] == ["aac"]
    assert len(params["exp"]) == len(params["sig"]) == 1
    assert media.signature_valid(STREAM, urlsplit(url).query, TOKEN, now=NOW)


def test_a_url_on_a_proxy_prefix_still_verifies_at_the_route():
    query = urlsplit(media.sign_url(f"https://host/familiar{STREAM}", TOKEN, lifetime_s=60, now=NOW)).query
    assert media.signature_valid(STREAM, query, TOKEN, now=NOW)


def test_a_speaker_url_lasts_the_track_plus_a_margin():
    """The longest track on the NAS is 3 h 14 min; a fixed short lifetime would cut it off."""
    assert media.speaker_url_lifetime(11_626) == 11_626 + media.SIGNED_URL_MARGIN_S
    assert media.speaker_url_lifetime(None) >= 11_626 + 3600
    assert media.speaker_url_lifetime(0) == media.SIGNED_URL_DEFAULT_LIFETIME_S


# ── The cookie ──────────────────────────────────────────────────────────────────────────────────


def test_the_cookie_is_not_the_token_and_changes_with_it():
    assert media.cookie_value(TOKEN) != TOKEN
    assert media.cookie_value(TOKEN) != media.cookie_value("rotated")
    assert media.cookie_value(TOKEN) == media.cookie_value(TOKEN)


# ── The gate, enforced (Phase 4's exit condition) ───────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "credential",
    [
        {"headers": {TOKEN_HEADER: TOKEN}},
        {"headers": {"Authorization": f"Bearer {TOKEN}"}},
        {"headers": {"Cookie": f"other=1; {media.COOKIE_NAME}={media.cookie_value(TOKEN)}"}},
        {"query": _signed_query().encode()},
    ],
    ids=["header", "bearer", "cookie", "signed URL"],
)
async def test_each_credential_reads_media(monkeypatch, credential):
    passed, status = await _gate(monkeypatch, _scope(**credential))
    assert passed and status is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "credential",
    [
        {},
        {"headers": {TOKEN_HEADER: "wrong"}},
        {"headers": {"Cookie": f"{media.COOKIE_NAME}={media.cookie_value('rotated')}"}},
        {"headers": {"Cookie": f"{media.COOKIE_NAME}={TOKEN}"}},
        {"query": _signed_query(token="rotated").encode()},
        {"query": _signed_query(lifetime_s=-1).encode()},
    ],
    ids=["none", "wrong token", "old cookie", "token as cookie", "old signature", "expired signature"],
)
async def test_without_a_valid_credential_media_is_refused(monkeypatch, credential):
    passed, status = await _gate(monkeypatch, _scope(**credential))
    assert not passed and status == 401


@pytest.mark.asyncio
async def test_the_cookie_never_authorizes_an_action(monkeypatch):
    """Point 3: a cookie reads pictures. Uploading artwork is the same path shape, POSTed."""
    cookie = {"Cookie": f"{media.COOKIE_NAME}={media.cookie_value(TOKEN)}"}
    passed, status = await _gate(
        monkeypatch, _scope(path="/api/v1/tracks/x/artwork", method="POST", headers=cookie)
    )
    assert not passed and status == 401
    passed, status = await _gate(monkeypatch, _scope(path="/api/v1/playlists", headers=cookie))
    assert not passed and status == 401


@pytest.mark.asyncio
async def test_a_signature_never_authorizes_anything_but_its_media_read(monkeypatch):
    query = _signed_query(path="/api/v1/playlists").encode()
    passed, status = await _gate(monkeypatch, _scope(path="/api/v1/playlists", query=query))
    assert not passed and status == 401


@pytest.mark.asyncio
async def test_a_tokenless_server_is_left_to_its_exposure_rules(monkeypatch):
    passed, _ = await _gate(monkeypatch, _scope(), token=None)
    assert passed


# ── Today ───────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_until_phase_4_media_is_served_without_a_credential(monkeypatch):
    """App 1.6 and 1.7 send nothing on media. Turning this on early silences every phone."""
    assert media.MEDIA_ENFORCED is False
    passed, status = await _gate(monkeypatch, _scope(), enforced=False)
    assert passed and status is None


# ── The routes ──────────────────────────────────────────────────────────────────────────────────


async def _client(monkeypatch, token):
    from app.main import app

    _settings(monkeypatch, token)
    monkeypatch.setattr(
        "app.api.routes.auth.get_app_settings_service",
        lambda: type("S", (), {"get": lambda self: type("A", (), {"access_token": token})()})(),
    )
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    return httpx.AsyncClient(transport=transport, base_url="http://localhost")


@pytest.mark.asyncio
async def test_the_web_admin_gets_a_media_cookie_with_the_token(monkeypatch):
    async with await _client(monkeypatch, TOKEN) as client:
        refused = await client.post("/api/v1/auth/media-cookie")
        issued = await client.post("/api/v1/auth/media-cookie", headers={TOKEN_HEADER: TOKEN})
    assert refused.status_code == 401
    assert issued.json() == {"issued": True}
    header = issued.headers["set-cookie"]
    assert header.startswith(f"{media.COOKIE_NAME}={media.cookie_value(TOKEN)};")
    for attribute in ("HttpOnly", "SameSite=strict", "Path=/api/v1", "Max-Age="):
        assert attribute in header
    assert "Secure" not in header, "plain http on the tailnet would drop a Secure cookie"


@pytest.mark.asyncio
async def test_a_tokenless_server_issues_no_cookie(monkeypatch):
    async with await _client(monkeypatch, None) as client:
        response = await client.post("/api/v1/auth/media-cookie")
    assert response.json() == {"issued": False}
    assert media.cookie_value("") not in response.headers.get("set-cookie", "")


def test_a_speaker_is_handed_a_signed_url_on_a_tokened_server(monkeypatch):
    from app.api.routes import outputs

    track = "6f1c2a52-6d4e-4f55-9a0b-2b8f3f0c1d11"
    for token, signed in ((TOKEN, True), (None, False)):
        monkeypatch.setattr(
            outputs,
            "get_app_settings_service",
            lambda token=token: type(
                "S",
                (),
                {
                    "get": lambda self: type("A", (), {"access_token": token})(),
                    "get_effective": lambda self, key: "http://192.168.1.5:4400",
                },
            )(),
        )
        url = outputs._device_stream_url("http://nas/x", track, duration_s=300)
        parts = urlsplit(url)
        assert parts.path == STREAM
        if signed:
            assert media.signature_valid(parts.path, parts.query, TOKEN)
            exp = int(parse_qs(parts.query)["exp"][0])
            assert exp - media.SIGNED_URL_MARGIN_S - 300 >= __import__("time").time() - 5
        else:
            assert parts.query == ""


# ── Logs ────────────────────────────────────────────────────────────────────────────────────────


def test_a_signature_never_reaches_the_access_log():
    from app.logging_config import RedactCredentialsFilter

    signed = f"{STREAM}?{_signed_query()}"
    sig = parse_qs(urlsplit(signed).query)["sig"][0]
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("192.168.1.30:50000", "GET", signed, "1.1", 206), None,
    )
    assert RedactCredentialsFilter().filter(record)
    line = record.getMessage()
    assert sig not in line and "sig=[redacted]" in line and "exp=" in line


def test_setup_logging_installs_the_filter_once():
    from app.logging_config import RedactCredentialsFilter, setup_logging

    setup_logging()
    setup_logging()
    filters = logging.getLogger("uvicorn.access").filters
    assert sum(isinstance(f, RedactCredentialsFilter) for f in filters) == 1


def test_the_capability_is_advertised():
    from app.config import SERVER_CAPABILITIES

    assert "media.credentials" in SERVER_CAPABILITIES
