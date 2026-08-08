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

    FAMILIAR_MCP_URL=http://openmediavault:4400/mcp \\
    uv run --project backend python backend/scripts/mcp_bridge.py

`FAMILIAR_MCP_PROFILE_ID` is optional — send it only if the server has more than one profile.
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


async def main() -> None:
    headers = {"X-Profile-ID": PROFILE} if PROFILE else {}
    http_client = httpx2.AsyncClient(headers=headers, timeout=180.0)

    async with streamable_http_client(URL, http_client=http_client) as (read, write):
        async with ClientSession(read, write) as upstream:
            init = await upstream.initialize()
            print(f"[familiar-mcp] bridging {URL} ({init.server_info.name})", file=sys.stderr)

            async def on_list_tools(
                _ctx: Any, _params: types.PaginatedRequestParams | None
            ) -> types.ListToolsResult:
                return types.ListToolsResult(tools=(await upstream.list_tools()).tools)

            async def on_call_tool(
                _ctx: Any, params: types.CallToolRequestParams
            ) -> types.CallToolResult:
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
