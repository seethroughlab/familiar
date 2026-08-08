"""Familiar's MCP server (ADR-0043).

The LLM surface. Familiar exposes its analysis tools over MCP rather than shipping a chat client,
so the host the listener already uses — Claude Desktop, Claude Code — drives them.

**This is an adapter, not a reimplementation.** `ToolExecutor.execute(name, arguments)` already
takes a tool name and a dict, which is exactly what MCP's `tools/call` provides, so the tool schemas
come straight from `MUSIC_TOOLS` and the handlers from `services/llm/handlers/` unchanged. Nothing
here can drift from the chat path, because there is nothing here to drift.

Two entry points over one tool set (ADR-0043 point 1): this module is mounted in-process by
`app.main`, and `scripts/mcp_stdio.py` serves the same tools over stdio for local development.
"""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from typing import Any
from uuid import UUID

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.server import ServerRequestContext
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select

from app.config import settings as app_config
from app.db.models import Profile
from app.db.session import async_session_maker
from app.mcp.guidance import GUIDANCE, INSTRUCTIONS
from app.services.llm.tools import MUSIC_TOOLS

logger = logging.getLogger(__name__)

SERVER_NAME = "familiar"
PROFILE_HEADER = "x-profile-id"
PROFILE_ENV = "FAMILIAR_MCP_PROFILE_ID"

#: Requires a Familiar client to mean anything — ADR-0043 point 2 defers these to ADR-0044.
#: `get_visible_tracks` answers only because a chat client uploaded its viewport; `queue_tracks`
#: and `control_playback` write to in-memory fields that never reach the server's state.
_CLIENT_BOUND = {"get_visible_tracks", "queue_tracks", "control_playback"}

#: Dropped outright. A server-side URL fetcher on an API with no inbound authentication is an SSRF
#: primitive, and the host's own web access does the job better (ADR-0043 point 2).
_WITHHELD = {"fetch_webpage"}

EXCLUDED = _CLIENT_BOUND | _WITHHELD


class ProfileNotBound(Exception):
    """No profile is bound to this connection.

    ADR-0043 point 9: the profile is configured per connection rather than passed per call, because
    nine handler paths depend on it and a tool that took it as a parameter would let a model guess
    at another listener's favourites.
    """


def exposed_tools() -> list[types.Tool]:
    """The tool surface, taken from MUSIC_TOOLS so it cannot drift."""
    tools: list[types.Tool] = []
    for spec in MUSIC_TOOLS:
        name = spec["name"]
        if name in EXCLUDED:
            continue
        schema = deepcopy(spec["input_schema"])
        if name == "create_playlist_from_items":
            # ADR-0043 point 9. The handler stores `user_message` as Playlist.generation_prompt,
            # and an MCP host never passes the listener's raw turn — so it becomes an argument or
            # every MCP-created playlist has an empty one.
            schema.setdefault("properties", {})["generation_prompt"] = {
                "type": "string",
                "description": (
                    "What the listener asked for, in their words where you have them. Stored with "
                    "the playlist as the record of why it exists."
                ),
            }
        tools.append(
            types.Tool(
                name=name,
                description=str(spec["description"]) + GUIDANCE.get(name, ""),
                input_schema=schema,
            )
        )
    return tools


def _header_profile(ctx: ServerRequestContext[Any]) -> str | None:
    request = getattr(ctx, "request", None)
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    try:
        return headers.get(PROFILE_HEADER)
    except Exception:  # noqa: BLE001 - a header bag that does not behave is simply absent
        return None


async def resolve_profile(ctx: ServerRequestContext[Any]) -> UUID:
    """The profile this connection acts as.

    Header first so one server can serve several listeners; the environment variable is how the
    stdio entry point binds a single one. Raises rather than defaulting: acting as *some* profile
    because none was named is how a model ends up reading the wrong person's favourites.
    """
    raw = _header_profile(ctx) or os.environ.get(PROFILE_ENV)
    if not raw:
        raise ProfileNotBound(
            f"No profile is bound to this connection. Send the {PROFILE_HEADER} header, or set "
            f"{PROFILE_ENV} for stdio. Familiar's tools are per-listener — favourites, play history "
            f"and playlists all depend on it — so there is no safe default."
        )
    try:
        profile_id = UUID(raw)
    except ValueError as exc:
        raise ProfileNotBound(f"Profile id {raw!r} is not a UUID.") from exc

    async with async_session_maker() as session:
        exists = await session.scalar(select(Profile.id).where(Profile.id == profile_id))
    if exists is None:
        raise ProfileNotBound(
            f"Profile {profile_id} does not exist on this server. GET /api/v1/profiles lists them."
        )
    return profile_id


async def on_list_tools(
    ctx: ServerRequestContext[Any], _params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    # Resolving here as well as in call_tool is deliberate. Listing tools is the first thing every
    # host does, so an unbound connection fails immediately and says why — rather than presenting a
    # working-looking surface that fails on the first call (ADR-0043 point 9, and the "Listening
    # Ideas" defect one step later that ADR-0022 point 3 refused).
    await resolve_profile(ctx)
    return types.ListToolsResult(tools=exposed_tools())


async def on_call_tool(
    ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
) -> types.CallToolResult:
    name = params.name
    if name in EXCLUDED or not any(t.name == name for t in exposed_tools()):
        return _error(f"Unknown tool {name!r}.")

    arguments: dict[str, Any] = dict(params.arguments or {})
    # Not an argument the handler takes; it is how `user_message` is supplied outside a chat.
    generation_prompt = str(arguments.pop("generation_prompt", "") or "")

    try:
        profile_id = await resolve_profile(ctx)
    except ProfileNotBound as exc:
        return _error(str(exc))

    # A session per call, never held across calls. A yield-scoped session outliving its handler is
    # how 834 downloads once became 83-byte error bodies here.
    from app.services.llm.executor import ToolExecutor

    async with async_session_maker() as session:
        executor = ToolExecutor(session, profile_id=profile_id, user_message=generation_prompt)
        result = await executor.execute(name, arguments)

    is_error = isinstance(result, dict) and "error" in result
    if is_error:
        logger.info("mcp tool %s returned an error: %s", name, result.get("error"))
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(result, default=str))],
        is_error=is_error,
    )


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)], is_error=True
    )


def build_server() -> Server[Any]:
    return Server(
        name=SERVER_NAME,
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


def _transport_security() -> TransportSecuritySettings:
    """DNS-rebinding protection for the streamable-HTTP transport.

    The SDK enables this and ships **no default allowlist**, so every `Host` — including
    `localhost` — is rejected with `421 Misdirected Request` until named. A 421 reads as a proxy
    fault, which is a bad way to learn about a setting.

    Configure `mcp_allowed_hosts` and the protection is on. Leave it empty and it is off, with a
    warning, because Familiar's actual inbound control is Tailscale today and a token under
    ADR-0045 tomorrow — and a server that 421s every request out of the box teaches people to
    disable security they never understood.
    """
    hosts = [h.strip() for h in (app_config.mcp_allowed_hosts or "").split(",") if h.strip()]
    if hosts:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=hosts,
        )
    logger.warning(
        "MCP DNS-rebinding protection is OFF (mcp_allowed_hosts is unset). Set it to the hosts "
        "this server is reached by — e.g. 'localhost:4400,myserver:4400' — to enable it."
    )
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=False, allowed_hosts=["*"], allowed_origins=["*"]
    )


def build_asgi_app() -> Any:
    """The streamable-HTTP app, served at the mount point itself rather than a nested `/mcp`."""
    return build_server().streamable_http_app(
        streamable_http_path="/",
        transport_security=_transport_security(),
    )


class MCPDispatch:
    """Serves the MCP app at exactly `/mcp`, dispatching before the router sees the request.

    `app.mount("/mcp", ...)` does not work here, and the way it fails is worth recording.
    Starlette's `Mount` compiles to a pattern that requires a trailing segment, so a request to
    `/mcp` never matches the mount; the router then falls through to `redirect_slashes` and answers
    **307 → /mcp/**. MCP clients POST their handshake, a redirected POST is not something every
    client replays correctly, and the symptom — a handshake that simply never completes — points
    nowhere near a trailing slash.

    Dispatching as middleware runs before routing, so both `/mcp` and `/mcp/` are served directly
    with no redirect, and the SPA catch-all never sees either.
    """

    def __init__(self, app: Any, mcp_app: Any = None, path: str = "/mcp") -> None:
        self.app = app
        self.mcp_app = mcp_app
        self.path = path

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if (
            self.mcp_app is not None
            and scope.get("type") == "http"
            and scope.get("path", "").rstrip("/") == self.path
        ):
            await self.mcp_app({**scope, "path": "/", "raw_path": b"/"}, receive, send)
            return
        await self.app(scope, receive, send)
