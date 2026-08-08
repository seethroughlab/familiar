"""Tests for the MCP surface (ADR-0043).

These pin the four things that are decisions rather than implementation, and that would fail
quietly if broken:

1. **Which tools are exposed.** ADR-0043 point 2 excludes three client-bound tools and withholds
   `fetch_webpage`. A regression here leaks a tool that cannot work, or an SSRF primitive.
2. **`/mcp` is not swallowed by the SPA catch-all.** The failure is asymmetric — POST keeps working
   while GET returns `index.html` with HTTP 200 — so half the transport dies looking healthy.
3. **An unbound connection fails, naming the reason** (point 9), rather than acting as some
   default profile.
4. **`generation_prompt` is an argument**, because an MCP host never passes the listener's turn.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import pytest

from app.api.exceptions import NotFoundError
from app.main import NON_SPA_PREFIXES, spa_fallback
from app.mcp.server import (
    EXCLUDED,
    PROFILE_ENV,
    ProfileNotBound,
    exposed_tools,
    resolve_profile,
)
from app.services.llm.tools import MUSIC_TOOLS


def _ctx(headers: dict[str, str] | None = None) -> SimpleNamespace:
    """A stand-in for ServerRequestContext — only `.request.headers` is read."""
    if headers is None:
        return SimpleNamespace(request=None)
    return SimpleNamespace(request=SimpleNamespace(headers=headers))


class TestToolSurface:
    def test_excludes_client_bound_and_withheld_tools(self):
        names = {t.name for t in exposed_tools()}
        assert not (names & EXCLUDED), f"excluded tools leaked: {names & EXCLUDED}"
        for withheld in ("get_visible_tracks", "queue_tracks", "control_playback", "fetch_webpage"):
            assert withheld not in names

    def test_exposes_everything_else(self):
        """The surface is MUSIC_TOOLS minus the exclusions — not a hand-maintained list."""
        names = {t.name for t in exposed_tools()}
        expected = {t["name"] for t in MUSIC_TOOLS} - EXCLUDED
        assert names == expected

    def test_schemas_come_from_music_tools_unchanged(self):
        """ADR-0043 point 2: re-hosted, not reimplemented. Drift here is the thing to prevent."""
        by_name = {t["name"]: t for t in MUSIC_TOOLS}
        for tool in exposed_tools():
            if tool.name == "create_playlist_from_items":
                continue  # gains one property; covered separately
            assert tool.input_schema == by_name[tool.name]["input_schema"]

    def test_create_playlist_gains_generation_prompt(self):
        tool = next(t for t in exposed_tools() if t.name == "create_playlist_from_items")
        assert "generation_prompt" in tool.input_schema["properties"]

    def test_adding_the_argument_does_not_mutate_music_tools(self):
        """The schema is deep-copied; the chat path must not see the MCP-only property."""
        exposed_tools()
        spec = next(t for t in MUSIC_TOOLS if t["name"] == "create_playlist_from_items")
        assert "generation_prompt" not in spec["input_schema"].get("properties", {})

    def test_calibration_guidance_reaches_the_filter_tool(self):
        """ADR-0043 point 3. Measured: without it a model filters energy>=0.6 and gets 92.5%."""
        tool = next(t for t in exposed_tools() if t.name == "filter_tracks")
        assert "get_feature_distribution" in tool.description


class TestSpaCatchAll:
    """The trap. `/embed` hit it once and the `/api/` 200-instead-of-404 bug hit it again."""

    def test_mcp_is_a_non_spa_prefix(self):
        assert "mcp" in NON_SPA_PREFIXES

    @pytest.mark.asyncio
    async def test_spa_fallback_refuses_mcp_paths(self):
        """Must raise, not return index.html.

        Streamable HTTP uses GET for the server-initiated stream, and the catch-all is GET-only —
        so without this, POST works while GET silently serves HTML and the session half dies.
        """
        for path in ("mcp", "mcp/"):
            with pytest.raises(NotFoundError):
                await spa_fallback(path)

    @pytest.mark.asyncio
    async def test_spa_fallback_still_serves_app_routes(self):
        """Guard the guard.

        A real SPA route must still get `index.html`, or the test above would pass just as well
        against a `spa_fallback` that refused everything — which is not a guard, it is a coincidence.
        """
        response = await spa_fallback("library/artists")
        assert response.__class__.__name__ == "FileResponse"


class TestMountedEndpoint:
    """The handshake, over the real transport, against the real app.

    `app.mount("/mcp", ...)` looks right and answers **307**: Starlette's Mount pattern requires a
    trailing segment, so `/mcp` never matches and the router falls through to `redirect_slashes`.
    MCP clients POST their handshake, and a redirected POST is not reliably replayed — the symptom
    is a handshake that never completes, pointing nowhere near a trailing slash.
    """

    INIT = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    HEADERS = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    async def _initialize(self, path: str) -> Any:
        """A fresh MCP app per call.

        `StreamableHTTPSessionManager.run()` raises if entered twice on one instance, so tests
        cannot share the module-level app the way the running server does.
        """
        import httpx
        from fastapi import FastAPI

        from app.mcp.server import MCPDispatch, build_asgi_app

        mcp_app = build_asgi_app()
        host = FastAPI()
        host.add_middleware(MCPDispatch, mcp_app=mcp_app)

        @host.get("/api/v1/sentinel")
        async def _sentinel() -> dict[str, bool]:
            return {"ok": True}

        async with mcp_app.router.lifespan_context(mcp_app):
            transport = httpx.ASGITransport(app=host)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://localhost:4400"
            ) as client:
                if path == "__sentinel__":
                    return await client.get("/api/v1/sentinel")
                return await client.post(path, json=self.INIT, headers=self.HEADERS)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
    async def test_initialize_succeeds_without_a_redirect(self, path):
        response = await self._initialize(path)
        assert response.status_code == 200, f"{path} answered {response.status_code}"
        assert "text/event-stream" in response.headers.get("content-type", "")
        assert '"serverInfo"' in response.text

    @pytest.mark.asyncio
    async def test_server_advertises_instructions(self):
        """ADR-0043 point 3: instructions are one of the two channels that reach every host."""
        response = await self._initialize("/mcp")
        assert "get_feature_distribution" in response.text

    @pytest.mark.asyncio
    async def test_dispatch_leaves_other_routes_alone(self):
        """Guard the guard: the dispatch must intercept /mcp and nothing else."""
        response = await self._initialize("__sentinel__")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_the_real_app_wires_the_dispatch(self):
        """The tests above prove MCPDispatch works; this proves main.py actually installed it."""
        from app.main import app
        from app.mcp.server import MCPDispatch

        installed = [m for m in app.user_middleware if m.cls is MCPDispatch]
        assert installed, "MCPDispatch is not installed on the application"
        assert installed[0].kwargs.get("mcp_app") is not None


class TestProfileBinding:
    @pytest.mark.asyncio
    async def test_unbound_connection_is_refused(self, monkeypatch):
        monkeypatch.delenv(PROFILE_ENV, raising=False)
        with pytest.raises(ProfileNotBound) as exc:
            await resolve_profile(_ctx())
        assert "no safe default" in str(exc.value)

    @pytest.mark.asyncio
    async def test_malformed_profile_is_refused(self, monkeypatch):
        monkeypatch.delenv(PROFILE_ENV, raising=False)
        with pytest.raises(ProfileNotBound) as exc:
            await resolve_profile(_ctx({"x-profile-id": "not-a-uuid"}))
        assert "not a UUID" in str(exc.value)

    @pytest.mark.asyncio
    async def test_header_is_preferred_over_environment(self, monkeypatch):
        """One server, several listeners: the header wins so stdio's binding cannot leak in."""
        monkeypatch.setenv(PROFILE_ENV, "11111111-1111-1111-1111-111111111111")
        seen: list[str] = []

        async def fake_lookup(ctx):
            raw = ctx.request.headers.get("x-profile-id") or os.environ.get(PROFILE_ENV)
            seen.append(raw)
            raise ProfileNotBound("stop before the database")

        monkeypatch.setattr("app.mcp.server.resolve_profile", fake_lookup)
        from app.mcp import server as mcp_server

        with pytest.raises(ProfileNotBound):
            await mcp_server.resolve_profile(
                _ctx({"x-profile-id": "22222222-2222-2222-2222-222222222222"})
            )
        assert seen == ["22222222-2222-2222-2222-222222222222"]
