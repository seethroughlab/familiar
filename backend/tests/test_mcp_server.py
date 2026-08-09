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

from types import SimpleNamespace
from typing import Any
from uuid import UUID

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


#: Tools this layer adds that have no MUSIC_TOOLS entry.
MCP_ONLY_TOOLS = {"list_players", "get_now_playing"}


class TestToolSurface:
    def test_excludes_client_bound_and_withheld_tools(self):
        names = {t.name for t in exposed_tools()}
        assert not (names & EXCLUDED), f"excluded tools leaked: {names & EXCLUDED}"
        # `get_visible_tracks` needs a viewport no MCP host has; `fetch_webpage` is an SSRF
        # primitive on an API with no inbound auth. Neither has a route back.
        for withheld in ("get_visible_tracks", "fetch_webpage"):
            assert withheld not in names

    def test_playback_tools_are_exposed_again(self):
        """ADR-0044 gave them a destination, so ADR-0043 point 2's deferral has expired.

        They are served by `app.mcp.playback` over the command channel, not by `ToolExecutor`'s
        in-memory fields — which is what made them useless over MCP in the first place.
        """
        names = {t.name for t in exposed_tools()}
        assert {"queue_tracks", "control_playback"} <= names

    def test_mcp_only_tools_are_added(self):
        """Neither is in MUSIC_TOOLS, and neither could have been.

        `list_players` answers a question that only exists because commands go to a subscribed
        client — the chat client never had to ask, because it *was* the player.
        `get_now_playing` reads a fact ADR-0030 already gave the server, which the chat client
        also never needed, for the same reason.
        """
        assert MCP_ONLY_TOOLS <= {t.name for t in exposed_tools()}

    def test_exposes_everything_else(self):
        """The surface is MUSIC_TOOLS minus exclusions, plus the MCP-only tool — never a list."""
        names = {t.name for t in exposed_tools()}
        expected = ({t["name"] for t in MUSIC_TOOLS} - EXCLUDED) | MCP_ONLY_TOOLS
        assert names == expected

    def test_schemas_come_from_music_tools_unchanged(self):
        """ADR-0043 point 2: re-hosted, not reimplemented. Drift here is the thing to prevent."""
        by_name = {t["name"]: t for t in MUSIC_TOOLS}
        # Each of these gains exactly one MCP-only property, covered by its own test below.
        widened = {"create_playlist_from_items", "queue_tracks", "control_playback"}
        for tool in exposed_tools():
            if tool.name in widened or tool.name in MCP_ONLY_TOOLS:
                continue
            assert tool.input_schema == by_name[tool.name]["input_schema"]

    def test_widened_schemas_add_one_property_and_no_more(self):
        """A widened schema must still be the MUSIC_TOOLS one underneath."""
        by_name = {t["name"]: t for t in MUSIC_TOOLS}
        for name, added in (
            ("create_playlist_from_items", "generation_prompt"),
            ("queue_tracks", "player"),
            ("control_playback", "player"),
        ):
            tool = next(t for t in exposed_tools() if t.name == name)
            original = set(by_name[name]["input_schema"].get("properties", {}))
            assert set(tool.input_schema["properties"]) == original | {added}

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


ONE = UUID("11111111-1111-1111-1111-111111111111")
TWO = UUID("22222222-2222-2222-2222-222222222222")


class TestProfileBinding:
    """Resolution order: request (header, then query), environment, then a sole profile."""

    @pytest.fixture(autouse=True)
    def _no_database(self, monkeypatch):
        """Keep these off the database; each test says what the server should look like."""
        monkeypatch.delenv(PROFILE_ENV, raising=False)

        async def sole_none():
            return None

        async def exists(profile_id):
            return profile_id

        monkeypatch.setattr("app.mcp.server._sole_profile", sole_none)
        monkeypatch.setattr("app.mcp.server._verify_profile", exists)

    @pytest.mark.asyncio
    async def test_unbound_with_several_profiles_is_refused(self):
        with pytest.raises(ProfileNotBound) as exc:
            await resolve_profile(_ctx())
        assert "no safe default" in str(exc.value)

    @pytest.mark.asyncio
    async def test_malformed_profile_is_refused(self):
        with pytest.raises(ProfileNotBound) as exc:
            await resolve_profile(_ctx({"x-profile-id": "not-a-uuid"}))
        assert "not a UUID" in str(exc.value)

    @pytest.mark.asyncio
    async def test_header_binds_the_connection(self):
        assert await resolve_profile(_ctx({"x-profile-id": str(TWO)})) == TWO

    @pytest.mark.asyncio
    async def test_query_string_binds_the_connection(self):
        """Claude Desktop's custom connector takes a URL and cannot set headers."""
        ctx = SimpleNamespace(request=SimpleNamespace(headers={}, query_params={"profile": str(TWO)}))
        assert await resolve_profile(ctx) == TWO

    @pytest.mark.asyncio
    async def test_header_beats_query_string(self):
        ctx = SimpleNamespace(
            request=SimpleNamespace(
                headers={"x-profile-id": str(ONE)}, query_params={"profile": str(TWO)}
            )
        )
        assert await resolve_profile(ctx) == ONE

    @pytest.mark.asyncio
    async def test_request_beats_environment(self, monkeypatch):
        """stdio's binding must not leak into an HTTP connection that named its own."""
        monkeypatch.setenv(PROFILE_ENV, str(ONE))
        assert await resolve_profile(_ctx({"x-profile-id": str(TWO)})) == TWO

    @pytest.mark.asyncio
    async def test_environment_is_used_when_the_request_names_none(self, monkeypatch):
        monkeypatch.setenv(PROFILE_ENV, str(ONE))
        assert await resolve_profile(_ctx()) == ONE

    @pytest.mark.asyncio
    async def test_sole_profile_needs_no_configuration(self, monkeypatch):
        """With exactly one profile there is nothing to guess, so nothing to configure."""

        async def sole_one():
            return ONE

        monkeypatch.setattr("app.mcp.server._sole_profile", sole_one)
        assert await resolve_profile(_ctx()) == ONE
