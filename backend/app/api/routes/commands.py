"""The command channel's HTTP surface (ADR-0044, ADR-0053).

Two endpoints now. A client subscribes and receives imperatives until it goes away; and, since
ADR-0053, it uploads anything a command asked it to produce. There is still no *send* endpoint —
the sender is the MCP tool layer, in-process (ADR-0043), and adding an HTTP way to make somebody
else's music play is a decision nothing has taken.

SSE rather than a WebSocket (ADR-0044 point 2): commands are one-way, so a socket's return half
would go unused. **That is still true of the stream.** A screenshot travels the other way as an
ordinary upload the client makes when it has something to send, which is why the transport did not
have to change to gain a return path (ADR-0053 point 3).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.deps import DbSession, RequiredProfile, release_connection
from app.services.playback_commands import (
    AttachedPlayer,
    UnknownCapability,
    get_artifact_store,
    get_channel,
)

logger = logging.getLogger(__name__)

# A window capture at Retina scale is a few hundred KB; this is a bound, not a target.
_MAX_ARTIFACT_BYTES = 25 * 1024 * 1024

# `commands`, not `playback` (ADR-0075). Nothing here plays anything: the server neither decodes
# audio nor holds a transport, and the thing on the receiving end is the Apple client. The old name
# also collided with `routes/tracks/plays.py` — a command bus and a listening ledger, two modules
# called playback, and the tag belonged to the one that is neither.
router = APIRouter(prefix="/commands", tags=["commands"])

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
    "/stream",
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
    try:
        player = get_channel().attach(
            profile_id,
            name=client,
            platform=platform,
            capabilities=declared,
            now=time.monotonic(),
        )
    except UnknownCapability as exc:
        # 400 rather than a silent partial attach: a client that misspells a capability must be
        # told, at the moment it connects, rather than discovering later that commands it expected
        # never arrive.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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


@router.post("/artifacts/{request_id}", status_code=204)
async def upload_artifact(
    profile: RequiredProfile, request_id: str, file: UploadFile
) -> None:
    """Hand back something a command asked this client to produce (ADR-0053 point 3).

    The return half of the channel, and deliberately not on the channel: the SSE stream stays
    one-way, and this is a request the client makes when it has something to send. That keeps
    ADR-0044 point 2's reasoning intact rather than reversing it.

    `request_id` names one outstanding question. It is minted by the server when it issues the
    command, it is not a device identity, and it dies when the question is answered or times out —
    which is why this does not reopen ADR-0029 point 5.

    **Profile-scoped, and checked rather than merely required.** The store remembers which profile
    asked, so holding *a* profile is not enough to answer somebody else's question. Caught by
    `lint_profile_contracts.py`, which is the rule this route was quietly outside.

    A late or unknown upload is **discarded, not stored** (point 8). The question it answers has
    already been answered with a timeout, and keeping the image would mean keeping it forever.
    204 either way: the client cannot do anything useful with the difference, and telling it its
    screenshot was too slow would only invite a retry nothing is waiting for.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty artifact")
    if len(data) > _MAX_ARTIFACT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Artifact exceeds {_MAX_ARTIFACT_BYTES // 1024 // 1024}MB",
        )

    delivered = get_artifact_store().deliver(
        request_id,
        data,
        file.content_type or "application/octet-stream",
        profile_id=profile.id,
    )
    if not delivered:
        logger.info(
            "playback_artifact_discarded",
            extra={"request_id": request_id, "bytes": len(data)},
        )
