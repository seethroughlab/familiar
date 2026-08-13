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

import base64
import logging
import time
from copy import deepcopy
from typing import Any
from uuid import UUID, uuid4

import mcp.types as types

from app.services.now_playing import get_registry as get_now_playing_registry
from app.services.playback_commands import (
    ArtifactTimeout,
    NoPlayerAttached,
    get_artifact_store,
    get_channel,
)

logger = logging.getLogger(__name__)

#: Handled here rather than dispatched to `ToolExecutor`.
PLAYBACK_TOOLS = {
    "queue_tracks",
    "control_playback",
    "list_players",
    "get_now_playing",
    # ADR-0053: driving and photographing the interface, not just the audio.
    "navigate_app",
    "capture_screenshot",
}

#: The destinations a client can be rooted on. Mirrors `LibraryRoute` in FamiliarKit — a closed
#: list on purpose, so an unknown destination is refused by the schema instead of accepted and
#: quietly dropped (ADR-0053 point 2).
NAVIGATION_DESTINATIONS = [
    "home",
    "tracks",
    "albums",
    "artists",
    "playlists",
    "smart_playlists",
    "music_map",
    "discover",
    "pending_review",
    "proposed_changes",
    "mixtapes",
    "favorites",
    "downloads",
    "settings",
]

#: What a client must have declared to receive each command (ADR-0044 point 12).
_REQUIRES = {
    "queue_tracks": "queue",
    "control_playback": "play",
    "navigate_app": "navigate",
    "capture_screenshot": "screenshot",
}

#: How long to wait for a client to send a screenshot back. Generous — the app has to draw and
#: encode a window — but bounded, because a tool that never answers is the defect ADR-0044 point 5
#: exists to prevent.
_CAPTURE_TIMEOUT_SECONDS = 15.0

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


def navigate_tool() -> types.Tool:
    return types.Tool(
        name="navigate_app",
        description=(
            "Show a particular screen in the listener's Familiar app — the Mac or phone client, "
            "not the web page. Use it to put the app somewhere before asking about it or "
            "photographing it, or when the listener asks to be taken to a part of their library. "
            "Delivered to a running client, so it needs one attached; call list_players if this "
            "reports none. This roots the app on a destination and does not open a specific album "
            "or playlist."
        ),
        input_schema=add_target_property(
            "target",
            {
                "type": "object",
                "properties": {
                    "destination": {
                        "type": "string",
                        "enum": NAVIGATION_DESTINATIONS,
                        "description": "Which screen to show.",
                    }
                },
                "required": ["destination"],
            },
        ),
    )


def capture_screenshot_tool() -> types.Tool:
    return types.Tool(
        name="capture_screenshot",
        description=(
            "Photograph the listener's Familiar app window and return the image. The app draws "
            "its own window, so this captures Familiar and nothing else on their machine — no "
            "other applications, no desktop, no menu bar. Use it to see what a screen actually "
            "looks like, to check your own work after navigating, or to produce images of the "
            "interface. Pair it with navigate_app to choose the screen first."
        ),
        input_schema=add_target_property("target", {"type": "object", "properties": {}}),
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

    if name == "navigate_app":
        destination = str(arguments.get("destination", "")).strip()
        if destination not in NAVIGATION_DESTINATIONS:
            # Refused rather than sent. A destination the app has no case for would arrive, be
            # decoded to nothing, and leave the tool reporting success against a screen that never
            # changed (ADR-0053 point 2).
            return {
                "error": f"Unknown destination {destination!r}.",
                "destinations": NAVIGATION_DESTINATIONS,
            }
        try:
            player = channel.send(
                profile_id,
                {"type": "navigate", "destination": destination},
                target=target,
                requires=_REQUIRES[name],
            )
        except NoPlayerAttached as exc:
            return _no_player_answer(exc, profile_id)
        return {"delivered": True, "destination": destination, "player": player.describe()}

    if name == "capture_screenshot":
        request_id = uuid4().hex
        store = get_artifact_store()
        # Opened *before* the command goes out, or a fast client could answer into nothing.
        store.open(request_id, profile_id)
        try:
            player = channel.send(
                profile_id,
                {"type": "screenshot", "request_id": request_id},
                target=target,
                requires=_REQUIRES[name],
            )
        except NoPlayerAttached as exc:
            store.cancel(request_id)
            return _no_player_answer(exc, profile_id)

        try:
            data, content_type = await store.wait(request_id, _CAPTURE_TIMEOUT_SECONDS)
        except ArtifactTimeout as exc:
            # Answers rather than hanging (ADR-0044 point 5). The client is attached and declared
            # the capability, so this is worth reporting as a fault rather than as "unavailable".
            return {
                "error": str(exc),
                "player": player.describe(),
                "note": (
                    "The client is attached and says it can take screenshots, so it either failed "
                    "to draw its window or could not upload the result."
                ),
            }

        return {
            "image": {
                "data": base64.b64encode(data).decode("ascii"),
                "mime_type": content_type,
                "bytes": len(data),
            },
            "player": player.describe(),
            "note": (
                "This is the Familiar window as the app drew it — no other application, desktop "
                "or menu bar is in it."
            ),
        }

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
        # Ids, not track objects. The clients already fetch tracks by id through the generated
        # client — `ServerTrackMetadataSource.loadTracks(ids:)` on the Mac, fifty at a time — and
        # putting a second, untyped copy of the Track shape on this channel is exactly the
        # hand-parsed surface ADR-0007 exists to prevent, which already cost ADR-0022 a bug. The
        # tool's *reply* still carries the resolved tracks, because that is for the model to read.
        player = channel.send(
            profile_id,
            {"type": "queue", "track_ids": [t["id"] for t in tracks], "clear": clear},
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
