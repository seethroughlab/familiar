"""Serve Familiar's MCP tools over stdio (ADR-0043 point 1's second entry point).

Same tool set, same handlers, same `ToolExecutor` as the `/mcp` mount — only the transport
differs. This exists because tuning tool descriptions is the work ADR-0043 point 3 says decides
whether the surface is any good, and doing that against the mount means a `make deploy-dev` per
edit. Here it is a file save.

Bind a profile, because there is no header on stdio:

    FAMILIAR_MCP_PROFILE_ID=<uuid> \\
    DATABASE_URL=postgresql+asyncpg://... \\
    uv run --directory backend python scripts/mcp_stdio.py

Register it with Claude Code from the repository root:

    claude mcp add familiar -- uv run --directory backend python scripts/mcp_stdio.py

Note that this runs where you run it. The tools reach the database directly, and `semantic_search`
needs torch — both of which are true inside the server's own environment and often not on a laptop.
For the full surface, use the `/mcp` mount instead.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.mcp.server import PROFILE_ENV, build_server  # noqa: E402


async def main() -> None:
    if not os.environ.get(PROFILE_ENV):
        raise SystemExit(
            f"{PROFILE_ENV} is not set. Familiar's tools are per-listener, so there is no safe "
            f"default profile. GET /api/v1/profiles lists the ids on your server."
        )
    print(f"[familiar-mcp] stdio, profile={os.environ[PROFILE_ENV]}", file=sys.stderr)
    await build_server().run("stdio")


if __name__ == "__main__":
    asyncio.run(main())
