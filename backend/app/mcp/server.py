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
from app.mcp import playback as playback_tools
from app.mcp.guidance import GUIDANCE, INSTRUCTIONS
from app.mcp.playback import (
    PLAYBACK_TOOLS,
    add_target_property,
    capture_screenshot_tool,
    list_players_tool,
    navigate_tool,
    now_playing_tool,
)
from app.services.llm.tools import MUSIC_TOOLS

logger = logging.getLogger(__name__)

SERVER_NAME = "familiar"
PROFILE_HEADER = "x-profile-id"
PROFILE_ENV = "FAMILIAR_MCP_PROFILE_ID"

#: Tools withheld from MCP hosts. **Empty, and that is the finished state rather than a gap.**
#:
#: ADR-0043 point 2 defined the exposed surface as everything in `MUSIC_TOOLS` minus the
#: client-bound and the withheld, and there were one of each:
#:
#: - `get_visible_tracks` was client-bound — it answered only because a chat client uploaded its
#:   viewport with the request, and no MCP host has a viewport to upload.
#: - `fetch_webpage` was withheld — a server-side URL fetcher on an API with no inbound
#:   authentication is an SSRF primitive, and a host's own web access does the job better.
#:
#: Point 5 retired the chat clients, which left both tools with no caller at all, so they were
#: deleted rather than left excluded. `queue_tracks` and `control_playback` were once here too,
#: until ADR-0044's command channel gave them a destination.
#:
#: Keep this set rather than deleting it: it is the seam where a future client-bound tool goes, and
#: `exposed_tools()` reads it. A tool that needs a Familiar client in front of it belongs here, not
#: in an `if` somewhere.
EXCLUDED: frozenset[str] = frozenset()


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
                input_schema=add_target_property(name, schema),
            )
        )
    # Not in MUSIC_TOOLS: the chat client never needed to ask which players it could reach,
    # because it was the player. An MCP host has to ask (ADR-0044 point 4).
    tools.append(list_players_tool())
    tools.append(now_playing_tool())
    # ADR-0053: the channel drives and observes the interface, not only the audio.
    tools.append(navigate_tool())
    tools.append(capture_screenshot_tool())
    return tools


def _request_profile(ctx: ServerRequestContext[Any]) -> str | None:
    """The profile named by the request, by header or by query string.

    The query string exists because **hosts cannot all set headers.** Claude Desktop's custom
    connector takes a URL and nothing else, so a header-only server cannot be added to it at all.
    A profile id is not a secret — `GET /api/v1/profiles` lists them unauthenticated — so carrying
    it in the URL gives nothing away that the API does not already.
    """
    request = getattr(ctx, "request", None)
    if request is None:
        return None
    try:
        headers = getattr(request, "headers", None)
        if headers is not None:
            named = headers.get(PROFILE_HEADER)
            if named:
                return str(named)
        params = getattr(request, "query_params", None)
        if params is not None:
            named = params.get("profile")
            if named:
                return str(named)
    except Exception:  # noqa: BLE001 - a request object that does not behave is simply silent
        return None
    return None


async def _sole_profile() -> UUID | None:
    """The only profile, when there is exactly one.

    ADR-0043 point 9 refuses a *default* profile because a model must not guess at another
    listener's favourites. With exactly one profile there is nothing to guess: the single
    possibility is the correct one, and requiring configuration to state the obvious is how a
    working server looks broken. Add a second profile and this returns None immediately, so
    connections must name one from that moment on.
    """
    async with async_session_maker() as session:
        ids = (await session.scalars(select(Profile.id).limit(2))).all()
    return ids[0] if len(ids) == 1 else None


async def resolve_profile(ctx: ServerRequestContext[Any]) -> UUID:
    """The profile this connection acts as.

    Request first, so one server can serve several listeners; then the environment variable, which
    is how the stdio entry point binds one; then the sole profile, if there is only one.
    """
    raw = _request_profile(ctx) or os.environ.get(PROFILE_ENV)
    if not raw:
        only = await _sole_profile()
        if only is not None:
            return only
        raise ProfileNotBound(
            f"No profile is bound to this connection, and this server has more than one. Send the "
            f"{PROFILE_HEADER} header, add ?profile=<uuid> to the URL, or set {PROFILE_ENV} for "
            f"stdio. Familiar's tools are per-listener — favourites, play history and playlists all "
            f"depend on it — so with several profiles there is no safe default. "
            f"GET /api/v1/profiles lists them."
        )
    try:
        profile_id = UUID(raw)
    except ValueError as exc:
        raise ProfileNotBound(f"Profile id {raw!r} is not a UUID.") from exc

    if await _verify_profile(profile_id) is None:
        raise ProfileNotBound(
            f"Profile {profile_id} does not exist on this server. GET /api/v1/profiles lists them."
        )
    return profile_id


async def _verify_profile(profile_id: UUID) -> UUID | None:
    """The profile id if it exists, else None. A named profile is checked, never assumed."""
    async with async_session_maker() as session:
        return await session.scalar(select(Profile.id).where(Profile.id == profile_id))


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
        if name in PLAYBACK_TOOLS:
            # Actuation, not a query: these travel the command channel to a subscribed client.
            # The executor is still handed over, because resolving track ids to tracks is its
            # job and has nothing to do with delivery.
            result = await playback_tools.handle(
                name, arguments, profile_id=profile_id, execute=executor.execute
            )
        else:
            result = await executor.execute(name, arguments)

    # Every call is logged with its arguments, because the arguments are the interesting part.
    # ADR-0043 point 3 rests on a host calling get_feature_distribution *before* it thresholds,
    # and there is otherwise no way to see whether it did: the tool sequence lives in the host's
    # conversation, not here. `docker logs familiar-api | grep mcp_tool_call` is the record.
    is_error = isinstance(result, dict) and "error" in result
    matched = result.get("count") if isinstance(result, dict) else None
    logger.info(
        "mcp_tool_call",
        extra={
            "tool": name,
            "arguments": json.dumps(arguments, default=str)[:400],
            "profile_id": str(profile_id),
            "matched": matched,
            "is_error": is_error,
        },
    )
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
