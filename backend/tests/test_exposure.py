"""ADR-0171: a remotely reachable server is protected by default.

One matrix over what the launchers decide (bind address × token × open by choice × existing
library) and one over who a tokenless server then answers (peer × forwarding × Host), driven
through the real `TokenAuthMiddleware`. Docker, Familiar Server and a bare `python -m app.serve` all
start through `app.serve.main`, so these are every launcher's rules; a bare `uvicorn` records
nothing and gets the default, which is the LOCAL row.
"""

from __future__ import annotations

import pytest

from app import exposure
from app.exposure import Exposure, Start, decide, exposure_for, request_is_local


def _never():
    raise AssertionError("has_tracks consulted")


# ── What a launcher decides ─────────────────────────────────────────────────────────────────────

LAUNCH_MATRIX = [
    # host,        token,  open,  tracks, start,                tokenless exposure
    ("127.0.0.1", None, False, False, Start.LOOPBACK, Exposure.LOCAL),
    ("localhost", None, False, True, Start.LOOPBACK, Exposure.LOCAL),
    ("::1", "t", False, True, Start.LOOPBACK, Exposure.LOCAL),
    ("0.0.0.0", "t", False, True, Start.HAS_TOKEN, Exposure.LOCAL),
    ("0.0.0.0", None, False, False, Start.NEW, Exposure.LOCAL),
    ("0.0.0.0", None, False, True, Start.EXISTING_OPEN, Exposure.OPEN),
    ("0.0.0.0", None, True, False, Start.OPEN_BY_CHOICE, Exposure.OPEN),
    ("192.168.1.5", None, False, False, Start.NEW, Exposure.LOCAL),
    ("nas.local", None, False, False, Start.NEW, Exposure.LOCAL),
]


@pytest.mark.parametrize("host,token,open_server,tracks,start,tokenless", LAUNCH_MATRIX)
def test_launch_matrix(host, token, open_server, tracks, start, tokenless):
    decided = decide(host=host, token=token, open_server=open_server, has_tracks=lambda: tracks)
    assert decided is start
    assert exposure_for(decided) is tokenless


def test_loopback_and_a_token_never_ask_the_database():
    assert (
        decide(host="127.0.0.1", token=None, open_server=False, has_tracks=_never) is Start.LOOPBACK
    )
    assert (
        decide(host="0.0.0.0", token="t", open_server=False, has_tracks=_never) is Start.HAS_TOKEN
    )


def test_only_a_choice_or_an_existing_library_opens_a_tokenless_server():
    """Point 1: absence of a token is not public mode."""
    opened = {s for s in Start if exposure_for(s) is Exposure.OPEN}
    assert opened == {Start.OPEN_BY_CHOICE, Start.EXISTING_OPEN}


def test_without_a_launcher_only_familiar_open_server_opens(monkeypatch):
    """A bare `uvicorn --host 0.0.0.0` records nothing: LOCAL, unless the environment says open."""
    from app.config import settings

    exposure.record(None)
    monkeypatch.setattr(settings, "open_server", False)
    assert exposure.current() is Exposure.LOCAL
    monkeypatch.setattr(settings, "open_server", True)
    assert exposure.current() is Exposure.OPEN


@pytest.mark.parametrize("has_tracks,expected", [(False, Exposure.LOCAL), (True, Exposure.OPEN)])
def test_the_launcher_records_what_it_decided(monkeypatch, has_tracks, expected):
    from app.config import settings
    from app.serve import main

    monkeypatch.setattr(settings, "advertise_port", None)
    monkeypatch.setattr(settings, "open_server", False)
    exposure.record(None)
    main(
        ["--host", "0.0.0.0", "--no-advertise"],
        migrate=lambda: None,
        run=lambda h, p: None,
        token=lambda: None,
        has_tracks=lambda: has_tracks,
        mint=lambda: "minted",
    )
    assert exposure.current() is expected


def test_a_tokenless_loopback_server_says_so(monkeypatch, capsys):
    """Point 3: explicit loopback development may stay tokenless, and identifies itself."""
    from app.serve import main

    main([], migrate=lambda: None, run=lambda h, p: None, token=lambda: None)
    assert "only this machine" in capsys.readouterr().err


# ── Who a tokenless server answers ──────────────────────────────────────────────────────────────


def _scope(
    client="127.0.0.1", host="localhost:4400", headers=None, path="/api/v1/tracks", method="GET"
):
    raw = [(b"host", host.encode())] if host is not None else []
    raw += [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": raw,
        "client": (client, 50000) if client else None,
    }


REQUEST_MATRIX = [
    # description,                   scope kwargs,                                       local?
    ("browser on this machine", {}, True),
    ("127.0.0.1 Host", {"host": "127.0.0.1:4400"}, True),
    ("IPv6 loopback", {"client": "::1", "host": "[::1]:4400"}, True),
    ("no Host header", {"host": None}, True),
    ("phone on the LAN", {"client": "192.168.1.20", "host": "192.168.1.5:4400"}, False),
    ("tailnet peer", {"client": "100.64.0.7", "host": "nas:4400"}, False),
    ("Docker bridge", {"client": "172.17.0.1"}, False),
    ("reverse proxy, X-Forwarded-For", {"headers": {"X-Forwarded-For": "203.0.113.9"}}, False),
    ("reverse proxy, Forwarded", {"headers": {"Forwarded": "for=203.0.113.9"}}, False),
    ("reverse proxy, X-Real-IP", {"headers": {"X-Real-IP": "203.0.113.9"}}, False),
    ("DNS rebinding", {"host": "evil.example:4400"}, False),
    ("no peer at all", {"client": None}, False),
]


@pytest.mark.parametrize(
    "description,kwargs,local", REQUEST_MATRIX, ids=[r[0] for r in REQUEST_MATRIX]
)
def test_request_matrix(description, kwargs, local):
    assert request_is_local(_scope(**kwargs)) is local


async def _through_gate(monkeypatch, scope, *, token=None, mode=Exposure.LOCAL, mcp_hosts=""):
    from app.api.auth import TokenAuthMiddleware
    from app.config import settings

    monkeypatch.setattr(
        "app.services.app_settings.get_app_settings_service",
        lambda: type("S", (), {"get": lambda self: type("A", (), {"access_token": token})()})(),
    )
    monkeypatch.setattr(settings, "mcp_allowed_hosts", mcp_hosts)
    exposure.record(mode)

    passed = False
    sent: list[dict] = []

    async def downstream(scope, receive, send):
        nonlocal passed
        passed = True

    async def send(message):
        sent.append(message)

    await TokenAuthMiddleware(downstream)(scope, None, send)
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    body = next((m["body"] for m in sent if m["type"] == "http.response.body"), b"")
    return passed, status, body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "description,kwargs,local", REQUEST_MATRIX, ids=[r[0] for r in REQUEST_MATRIX]
)
async def test_a_local_tokenless_server_answers_only_its_own_machine(
    monkeypatch, description, kwargs, local
):
    passed, status, body = await _through_gate(monkeypatch, _scope(**kwargs))
    assert passed is local
    if not local:
        assert status == 401
        assert b"app.token --create" in body, "a refused caller is told how the owner recovers"


@pytest.mark.asyncio
async def test_an_open_tokenless_server_answers_anyone(monkeypatch):
    """Point 4: an existing installation is not locked out by the upgrade."""
    scope = _scope(client="192.168.1.20", host="192.168.1.5:4400")
    passed, status, _ = await _through_gate(monkeypatch, scope, mode=Exposure.OPEN)
    assert passed and status is None


@pytest.mark.asyncio
async def test_a_token_decides_whatever_the_exposure(monkeypatch):
    remote = _scope(client="192.168.1.20", host="192.168.1.5:4400")
    for mode in Exposure:
        assert (await _through_gate(monkeypatch, remote, token="s", mode=mode))[1] == 401
        with_token = _scope(client="192.168.1.20", host="nas", headers={"X-Familiar-Token": "s"})
        assert (await _through_gate(monkeypatch, with_token, token="s", mode=mode))[0]
    # And a token is still asked of this machine: it does not exempt loopback.
    assert (await _through_gate(monkeypatch, _scope(), token="s"))[1] == 401


@pytest.mark.asyncio
async def test_public_paths_and_media_stay_public(monkeypatch):
    """Health and the contract handshake answer before anything is paired; media is ADR-0045's
    exemption, which point 5 leaves for its own milestone."""
    for path in ("/api/v1/health", "/api/v1/contract", "/api/v1/tracks/abc/stream"):
        scope = _scope(client="192.168.1.20", host="nas", path=path)
        assert (await _through_gate(monkeypatch, scope))[0], path


@pytest.mark.asyncio
@pytest.mark.parametrize("method,refused", [("GET", False), ("POST", True), ("DELETE", True)])
async def test_a_remote_caller_cannot_claim_a_local_tokenless_server(monkeypatch, method, refused):
    """`/auth/token` is public so a server can be configured at all; claiming it is not."""
    scope = _scope(client="192.168.1.20", host="nas", path="/api/v1/auth/token", method=method)
    passed, status, _ = await _through_gate(monkeypatch, scope)
    assert passed is not refused
    assert (status == 401) is refused


@pytest.mark.asyncio
async def test_this_machine_can_claim_its_own_server(monkeypatch):
    scope = _scope(path="/api/v1/auth/token", method="POST")
    assert (await _through_gate(monkeypatch, scope))[0]


@pytest.mark.asyncio
async def test_an_open_server_can_still_be_claimed_from_the_web_admin(monkeypatch):
    """How an existing tokenless installation gets its token: Server → Access, from anywhere."""
    scope = _scope(client="192.168.1.20", host="nas", path="/api/v1/auth/token", method="POST")
    assert (await _through_gate(monkeypatch, scope, mode=Exposure.OPEN))[0]


# ── MCP and Host protection (point 7) ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mcp_is_off_on_an_open_tokenless_server_without_a_host_list(monkeypatch):
    """Even from this machine: DNS rebinding arrives from a browser on this machine."""
    for scope in (
        _scope(path="/mcp", method="POST"),
        _scope(client="192.168.1.20", host="nas", path="/mcp", method="POST"),
    ):
        passed, status, body = await _through_gate(monkeypatch, scope, mode=Exposure.OPEN)
        assert not passed and status == 401
        assert b"MCP_ALLOWED_HOSTS" in body


@pytest.mark.asyncio
async def test_a_host_list_turns_mcp_back_on_for_an_open_server(monkeypatch):
    """FastMCP's own DNS-rebinding protection is on once the list is set (`_transport_security`)."""
    scope = _scope(client="192.168.1.20", host="nas", path="/mcp", method="POST")
    passed, _, _ = await _through_gate(monkeypatch, scope, mode=Exposure.OPEN, mcp_hosts="nas")
    assert passed


@pytest.mark.asyncio
async def test_a_local_tokenless_server_refuses_a_rebound_host_for_mcp(monkeypatch):
    rebound = _scope(host="evil.example:4400", path="/mcp", method="POST")
    assert not (await _through_gate(monkeypatch, rebound))[0]
    assert (await _through_gate(monkeypatch, _scope(path="/mcp", method="POST")))[0]


# ── Revoking ────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_remote_caller_cannot_revoke_into_a_lockout(monkeypatch):
    """Revoking on a LOCAL server from elsewhere would leave the caller no way back but a shell."""
    import httpx

    from app.main import app

    state = {"access_token": "current"}

    class Service:
        def get(self):
            return type("A", (), dict(state))()

        def update(self, **kwargs):
            state.update(kwargs)

    monkeypatch.setattr("app.services.app_settings.get_app_settings_service", lambda: Service())
    monkeypatch.setattr("app.api.routes.auth.get_app_settings_service", lambda: Service())
    exposure.record(Exposure.LOCAL)
    # No lifespan, so no database: the route reads only settings.
    transport = httpx.ASGITransport(app=app, client=("192.168.1.20", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://nas:4400") as client:
        headers = {"X-Familiar-Token": "current"}
        refused = await client.delete("/api/v1/auth/token", headers=headers)
    assert refused.status_code == 409
    assert state["access_token"] == "current"

    local = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(transport=local, base_url="http://localhost:4400") as client:
        allowed = await client.delete("/api/v1/auth/token", headers=headers)
    assert allowed.status_code == 200
    assert state["access_token"] is None
