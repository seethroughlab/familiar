"""The MCP tools that actuate playback (ADR-0044).

`queue_tracks` and `control_playback` were withheld from the MCP surface by
[ADR-0043](../../../docs/decisions/ADR-0043-the-llm-surface-is-an-mcp-server.md) point 2, because
they wrote to in-memory fields on `ToolExecutor` that only a chat client ever drained. With the
command channel they have somewhere to go, so they come back — routed through it rather than
through those fields, which stay dead.

`list_players` is new here rather than in `MUSIC_TOOLS`. It answers a question that only exists
because commands are addressed to a subscribed client: *which players can I reach?* The chat path
never needed it, since it was itself the player.
"""

from __future__ import annotations

import logging
import time
from copy import deepcopy
from typing import Any
from uuid import UUID

import mcp.types as types

from app.services.now_playing import get_registry as get_now_playing_registry
from app.services.playback_commands import NoPlayerAttached, get_channel

logger = logging.getLogger(__name__)

#: Handled here rather than dispatched to `ToolExecutor`.
PLAYBACK_TOOLS = {"queue_tracks", "control_playback", "list_players", "get_now_playing"}

#: What a client must have declared to receive each command (ADR-0044 point 12).
_REQUIRES = {"queue_tracks": "queue", "control_playback": "play"}

_TARGET_PROPERTY = {
    "type": "string",
    "description": (
        "Which player to act on, by name or id, from list_players. Omit to use the most recently "
        "active one, which is almost always what the listener means."
    ),
}


def list_players_tool() -> types.Tool:
    return types.Tool(
        name="list_players",
        description=(
            "List the Familiar clients currently able to play music for this listener, with what "
            "each can do. Commands are delivered to a running client — they are not stored — so "
            "if this returns nothing, playback is unavailable until the listener opens Familiar "
            "somewhere. Call this when a play or queue request reports no player attached, or "
            "when the listener has more than one device and you need to name one."
        ),
        input_schema={"type": "object", "properties": {}},
    )


def now_playing_tool() -> types.Tool:
    return types.Tool(
        name="get_now_playing",
        description=(
            "What the listener most recently started playing, if anything is still credible. "
            "Use it before answering questions about the current track, and before 'more like "
            "this' — it gives you a track_id you can pass straight to find_similar_tracks.\n"
            "Read the answer carefully: the server is told when a track STARTS and is never told "
            "when it stops, so this reports a reported start, not a confirmed state. A track "
            "whose duration has elapsed is not reported at all rather than reported wrongly. If "
            "it returns nothing, say the listener does not appear to be playing anything rather "
            "than guessing."
        ),
        input_schema={"type": "object", "properties": {}},
    )


def add_target_property(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Give a playback tool its optional `player` argument (ADR-0044 point 4)."""
    if name not in _REQUIRES:
        return schema
    widened = deepcopy(schema)
    widened.setdefault("properties", {})["player"] = _TARGET_PROPERTY
    return widened


def _no_player_answer(exc: NoPlayerAttached, profile_id: UUID) -> dict[str, Any]:
    """Report an undeliverable command as an answer, never as a hang or a bare failure.

    ADR-0044 point 5. The reply says what is attached, so the model can tell the listener
    something true — "nothing is running" is actionable, a spinner is not (`familiar` #74).
    """
    return {
        "delivered": False,
        "reason": str(exc),
        "attached_players": [p.describe() for p in get_channel().players(profile_id)],
    }


async def handle(
    name: str,
    arguments: dict[str, Any],
    *,
    profile_id: UUID,
    execute: Any,
) -> dict[str, Any]:
    """Run one playback tool. `execute` runs a `ToolExecutor` tool, for track resolution."""
    channel = get_channel()

    if name == "get_now_playing":
        started = get_now_playing_registry().current(profile_id, time.monotonic())
        if started is None:
            return {
                "playing": None,
                "note": (
                    "Nothing was reported as started recently, so the listener does not appear to "
                    "be playing anything. The server is told when a track starts and never when "
                    "it stops, so this is the absence of a recent start rather than a confirmed "
                    "stop."
                ),
            }
        return {"playing": started.describe(time.monotonic())}

    if name == "list_players":
        players = [p.describe() for p in channel.players(profile_id)]
        return {
            "players": players,
            "note": (
                "No Familiar client is running, so nothing can play right now."
                if not players
                else "Commands go to the first of these unless you name another."
            ),
        }

    target = arguments.pop("player", None) or None

    if name == "control_playback":
        action = str(arguments.get("action", "")).strip()
        if action not in {"play", "pause", "next", "previous"}:
            return {"error": f"Unknown playback action {action!r}."}
        try:
            player = channel.send(
                profile_id, {"type": action}, target=target, requires=_REQUIRES[name]
            )
        except NoPlayerAttached as exc:
            return _no_player_answer(exc, profile_id)
        return {"delivered": True, "action": action, "player": player.describe()}

    # queue_tracks. The executor resolves ids to tracks — that logic is worth reusing and has
    # nothing to do with delivery — and the resolved tracks then travel as the command.
    clear = bool(arguments.pop("clear_existing", True))
    resolved = await execute("queue_tracks", arguments)
    if "error" in resolved:
        return resolved

    tracks = resolved.get("tracks") or []
    if not tracks:
        return {
            "delivered": False,
            "reason": "None of those track ids matched anything in the library.",
        }

    try:
        # `clear` is read here rather than from the executor, whose `clear_existing` never
        # reaches `_clear_queue` — it is accepted, echoed and dropped. Fixing that in the chat
        # path would be fixing a path being retired; this one carries the listener's actual intent.
        player = channel.send(
            profile_id,
            {"type": "queue", "tracks": tracks, "clear": clear},
            target=target,
            requires=_REQUIRES[name],
        )
    except NoPlayerAttached as exc:
        answer = _no_player_answer(exc, profile_id)
        # The tracks were found even though they could not be played, which is worth saying:
        # the model can offer to save them as a playlist instead.
        answer["tracks_found"] = len(tracks)
        return answer

    return {
        "delivered": True,
        "queued": len(tracks),
        "cleared_existing": clear,
        "player": player.describe(),
        "tracks": tracks,
    }
