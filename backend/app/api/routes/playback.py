"""The playback command channel's HTTP surface (ADR-0044).

One endpoint: a client subscribes and receives imperatives until it goes away. There is no send
endpoint — the sender is the MCP tool layer, in-process (ADR-0043), and adding an HTTP way to make
somebody else's music play is a decision nothing has taken.

SSE rather than a WebSocket (point 2): commands are one-way, so a socket's return half would go
unused, and this codebase already runs three SSE endpoints while having no WebSocket route at all.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.api.deps import DbSession, RequiredProfile, release_connection
from app.services.playback_commands import AttachedPlayer, get_channel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/playback", tags=["playback"])

#: Long enough not to be chatter, short enough that a proxy idle timeout is not reached first.
_HEARTBEAT_SECONDS = 20.0


async def _events(request: Request, player: AttachedPlayer) -> AsyncIterator[str]:
    """Commands as they arrive, with a heartbeat between them."""
    channel = get_channel()
    try:
        # Tell the client who it is, so it can be named as a target without guessing.
        yield f"data: {json.dumps({'type': 'attached', 'player': player.describe()})}\n\n"
        while True:
            if await request.is_disconnected():
                return
            try:
                command = await asyncio.wait_for(player.queue.get(), timeout=_HEARTBEAT_SECONDS)
            except TimeoutError:
                # A comment frame: it keeps proxies from closing an idle connection and is
                # ignored by every SSE client.
                yield ": keep-alive\n\n"
                continue
            yield f"data: {json.dumps(command, default=str)}\n\n"
    finally:
        # The connection ending *is* the departure (ADR-0044 point 3). Nothing else marks it, so
        # this must run on every exit path — client disconnect, server shutdown, or error.
        channel.detach(player)


@router.get(
    "/commands",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Playback commands for this profile, until the client disconnects.",
        }
    },
)
async def playback_commands(
    request: Request,
    db: DbSession,
    profile: RequiredProfile,
    client: str = Query("unknown", description="Human-readable client name, e.g. 'Jeff's Mac'."),
    platform: str = Query("unknown", description="e.g. macos, ios, web."),
    capabilities: str = Query(
        "",
        description=(
            "Comma-separated list of what this client can actually do — e.g. "
            "'play,queue,crossfade'. A command needing a capability this client did not declare "
            "goes to a client that did, or is answered as unavailable."
        ),
    ),
) -> StreamingResponse:
    """Subscribe to this profile's playback commands.

    Subscribe while you can act and disconnect when you cannot: the subscription is the claim to
    be a player, and the most recently attached client is the default target.

    Capabilities are declared here rather than assumed (point 12). The clients genuinely differ —
    the Apple clients have no theme, visualizer, normalization or shuffle-weight storage where the
    web app has all four — so without a declaration a perfectly well-formed command reaches a
    client that silently cannot obey it.
    """
    profile_id = profile.id

    # Everything the stream needs is now a plain value, so the connection goes back before a
    # response that stays open indefinitely. A `yield` dependency is held until the response
    # finishes sending, and this one never finishes: without this line every subscribed client
    # would pin a database connection for as long as it is open. That is the failure that
    # exhausted the pool for audio streaming, and a permanent subscription is a worse version of it.
    await release_connection(db)

    declared = frozenset(c.strip() for c in capabilities.split(",") if c.strip())
    player = get_channel().attach(
        profile_id,
        name=client,
        platform=platform,
        capabilities=declared,
        now=time.monotonic(),
    )

    return StreamingResponse(
        _events(request, player),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # nginx and friends buffer by default, which turns a live channel into a stalled one.
            "X-Accel-Buffering": "no",
        },
    )
