"""Bridge a remote Familiar `/mcp` to stdio, for hosts that only speak stdio.

Claude Desktop's `claude_desktop_config.json` accepts **stdio servers only** — `command`, `args`,
`env`. There is no `type: http` form; a remote URL has to be added through Settings → Connectors
instead, and that path may refuse a plain `http://` host on a local network. This bridge covers the
gap: a stdio server that forwards to the HTTP one.

It is deliberately in this repository rather than an `npx` of somebody else's proxy. Familiar is
self-hosted software, the `mcp` SDK is already a backend dependency, and downloading a third-party
bridge onto the listener's machine to reach their own music server is the wrong shape.

Tools are the whole surface Familiar exposes, so forwarding `tools/list` and `tools/call` forwards
everything. Add prompts or resources to the server and they need forwarding here too.

**One tool is served here rather than forwarded**, and it is the exception that proves where the
rest belong. ADR-0044's implementation note records the one thing the design cannot do: *the server
cannot open the app.* A command is addressed to a client that is already subscribed, so with
Familiar closed the host correctly reports "no player attached" and has no way to fix it. This
process runs on the listener's own machine, which is the only place that can, so `launch_familiar`
is handled locally. It is offered **only on macOS**, because a tool whose destination is not mounted
failing silently is a defect this project has hit repeatedly — see ADR-0053 point 2.

That is the whole rule for what goes here: **locality has to be the point.** Anything that reads or
writes the library belongs upstream, next to the database, where it cannot drift from `MUSIC_TOOLS`.

    FAMILIAR_MCP_URL=http://openmediavault:4400/mcp \\
    uv run --project backend python backend/scripts/mcp_bridge.py

`FAMILIAR_MCP_PROFILE_ID` is optional — send it only if the server has more than one profile.

`FAMILIAR_APP_PATH` names an explicit `.app` for `launch_familiar` to open. Set it if you build the
app yourself — otherwise the bundle-id lookup may prefer an Xcode build over `/Applications`.

`FAMILIAR_MCP_TOKEN` is the server token (ADR-0045). Optional while the server has none configured;
required once it does, and the failure without it is a 401 at connect rather than a tool error, so
it looks like the server is down rather than like a missing credential. It is read from the
environment rather than passed as an argument because `claude_desktop_config.json` is world-readable
in the user's Library folder either way, but `env` keeps it out of the process list.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import httpx2
import mcp.types as types
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

URL = os.environ.get("FAMILIAR_MCP_URL", "http://localhost:4400/mcp")
PROFILE = os.environ.get("FAMILIAR_MCP_PROFILE_ID", "")
TOKEN = os.environ.get("FAMILIAR_MCP_TOKEN", "")

#: The Mac and phone apps share one App Store Connect record (`familiar-apple`).
BUNDLE_ID = "com.familiar.player"
#: An explicit `.app` to open, overriding the bundle-id lookup.
#:
#: On a machine that has ever built the app, the bundle id is registered several times over —
#: `/Applications`, every Xcode DerivedData build, any `.xcarchive` — and `open -b` launches
#: whichever LaunchServices currently prefers, which is usually the most recently registered rather
#: than the installed one. That is the right default for a listener and the wrong one for whoever
#: is developing the app, so it is an override rather than a hardcoded path.
APP_PATH = os.environ.get("FAMILIAR_APP_PATH", "")
LAUNCH_TOOL = "launch_familiar"
#: `open` returns as soon as the app is handed off to LaunchServices, so this only has to cover a
#: cold process spawn. It is not how long the app takes to attach to the command channel.
LAUNCH_TIMEOUT = 20.0


def _launch_tool() -> types.Tool:
    return types.Tool(
        name=LAUNCH_TOOL,
        description=(
            "Open the Familiar app on this listener's Mac. Use it when a play, queue or navigate "
            "request reports that no player is attached, or when list_players comes back empty — "
            "commands are delivered to a running client and are never stored, so nothing can be "
            "played until Familiar is open somewhere.\n"
            "The app attaches to the command channel by itself a few seconds after launching, so "
            "call list_players again before giving up. This returns as soon as the launch is "
            "handed off, not once the app is ready."
        ),
        input_schema={"type": "object", "properties": {}},
    )


async def _launch() -> types.CallToolResult:
    """Open the app, and say what happened either way.

    Nothing here may spin (ADR-0053 point 5), so the subprocess carries a deadline and a timeout is
    reported as a timeout rather than as a launch that might still be coming.
    """
    target = ["-a", APP_PATH] if APP_PATH else ["-b", BUNDLE_ID]
    try:
        process = await asyncio.create_subprocess_exec(
            "open",
            *target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:  # `open` missing, which should not happen on a Mac
        return _text(f"Could not run `open`: {exc}", is_error=True)

    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=LAUNCH_TIMEOUT)
    except TimeoutError:
        process.kill()
        return _text(
            f"Launching Familiar did not finish within {LAUNCH_TIMEOUT:.0f}s. It may still be "
            "opening — call list_players to check.",
            is_error=True,
        )

    if process.returncode != 0:
        detail = stderr.decode(errors="replace").strip() or f"exit code {process.returncode}"
        # The common case is that Familiar simply is not installed on this machine, and `open`
        # says so in a sentence worth passing through verbatim rather than paraphrasing.
        return _text(f"Could not open Familiar ({APP_PATH or BUNDLE_ID}): {detail}", is_error=True)

    return _text(
        "Familiar is opening. It attaches to the command channel a few seconds later — call "
        "list_players to confirm before sending playback commands."
    )


def _text(message: str, *, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)], is_error=is_error
    )


async def main() -> None:
    headers = {"X-Profile-ID": PROFILE} if PROFILE else {}
    if TOKEN:
        headers["X-Familiar-Token"] = TOKEN
    http_client = httpx2.AsyncClient(headers=headers, timeout=180.0)

    async with streamable_http_client(URL, http_client=http_client) as (read, write):
        async with ClientSession(read, write) as upstream:
            try:
                init = await upstream.initialize()
            except Exception:
                # Without this, a server with a token configured and none supplied fails during the
                # MCP handshake, which Claude Desktop reports as "server could not be loaded" — the
                # same message it gives for a crashed script or a wrong path. Naming the variable
                # here is the difference between a two-minute fix and an evening of debugging the
                # wrong thing.
                if not TOKEN:
                    print(
                        "[familiar-mcp] connect failed and FAMILIAR_MCP_TOKEN is not set. If this "
                        f"server has a token configured (ADR-0045), every request to {URL} is a "
                        "401. Read it from the admin UI or GET /api/v1/auth/token and set "
                        "FAMILIAR_MCP_TOKEN in the `env` block of claude_desktop_config.json.",
                        file=sys.stderr,
                    )
                raise
            print(f"[familiar-mcp] bridging {URL} ({init.server_info.name})", file=sys.stderr)

            # Offered only where it can work, and only if the server has not grown a tool of its
            # own by that name — upstream owns the namespace, and a local tool shadowing a real one
            # would be invisible from the host's side. Settled once per connection rather than per
            # call: the upstream surface is `exposed_tools()`, which does not change under a running
            # process, and the host restarts this bridge whenever it reconnects anyway.
            serve_launch = sys.platform == "darwin" and not any(
                t.name == LAUNCH_TOOL for t in (await upstream.list_tools()).tools
            )
            if serve_launch:
                print(f"[familiar-mcp] serving {LAUNCH_TOOL} locally", file=sys.stderr)

            async def on_list_tools(
                _ctx: Any, _params: types.PaginatedRequestParams | None
            ) -> types.ListToolsResult:
                tools = list((await upstream.list_tools()).tools)
                if serve_launch:
                    tools.append(_launch_tool())
                return types.ListToolsResult(tools=tools)

            async def on_call_tool(
                _ctx: Any, params: types.CallToolRequestParams
            ) -> types.CallToolResult:
                if serve_launch and params.name == LAUNCH_TOOL:
                    return await _launch()
                return await upstream.call_tool(params.name, params.arguments or {})

            # The upstream's instructions are forwarded too. ADR-0043 point 3 leans on them, and a
            # bridge that dropped them would quietly remove half the guidance the host ever sees.
            server = Server(
                name=init.server_info.name,
                instructions=init.instructions,
                on_list_tools=on_list_tools,
                on_call_tool=on_call_tool,
            )
            async with stdio_server() as (stdin, stdout):
                await server.run(stdin, stdout, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
