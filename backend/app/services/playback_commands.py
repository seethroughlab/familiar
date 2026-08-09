"""The playback command channel (ADR-0044).

An MCP client can find music but cannot play it: the server has never had a path to a player.
This is that path — **one direction, imperatives only, storing nothing.**

**It is not queue sync, and the distinction is the whole design.**
[ADR-0028](../../../docs/decisions/ADR-0028-the-apple-clients-playback-session-is-local.md) deleted
queue sync because *state replication* between devices was unwanted: two queues, reconciled by
timestamp, with an archive for the loser. Nothing here is replicated or stored. A command is an
instruction that is delivered once and forgotten, exactly as a tap on a button is.

**Addressing without device identity.**
[ADR-0029](../../../docs/decisions/ADR-0029-the-server-stores-no-listener-preferences.md) point 5
leaves device identity uninvented, so the server has no key to file a device under. It does not need
one: a command is addressed to *a client that is currently subscribed*, which is a fact the channel
already holds. That is also why a device-local preference can travel here (ADR-0044 point 11) — the
client applies and persists it locally, and the server still stores nothing.

**Ephemeral and in-process** (point 6). A restart drops every subscription and clients resubscribe;
an undelivered command is lost rather than queued. That is correct for imperatives and would be
wrong for anything durable, which is why nothing durable travels here. A multi-worker deployment
would need this revisited — the same caveat ADR-0036 point 8 carries.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

#: Commands are transient. A client so far behind that its buffer is full is not going to be
#: helped by the backlog, so the oldest is dropped rather than the newest refused.
_BUFFER = 32

_ids = itertools.count(1)


@dataclass
class AttachedPlayer:
    """A client that is subscribed, and therefore claiming it can act.

    Subscription *is* the claim (point 3). There is no separate registration and nothing to clean
    up when a device disappears — the connection ending is the departure.
    """

    id: str
    profile_id: UUID
    name: str
    platform: str
    capabilities: frozenset[str]
    attached_at: float
    queue: asyncio.Queue[dict[str, Any]] = field(repr=False)

    def describe(self) -> dict[str, Any]:
        """What the MCP surface shows when asked which players are attached (point 4)."""
        return {
            "id": self.id,
            "name": self.name,
            "platform": self.platform,
            "capabilities": sorted(self.capabilities),
        }


class NoPlayerAttached(Exception):
    """Nobody is subscribed for this profile, or the named target is not.

    Raised so the caller can *answer* — "no player is attached" — rather than hang or fail
    opaquely. ADR-0044 point 5, which is ADR-0017 point 4's rule one layer out: a capability check
    must answer, never throw into the void. A play intent that spins forever is `familiar` #74.
    """


class PlaybackCommandChannel:
    def __init__(self) -> None:
        self._players: dict[UUID, list[AttachedPlayer]] = {}

    def attach(
        self,
        profile_id: UUID,
        *,
        name: str,
        platform: str,
        capabilities: frozenset[str],
        now: float,
    ) -> AttachedPlayer:
        player = AttachedPlayer(
            id=f"p{next(_ids)}",
            profile_id=profile_id,
            name=name,
            platform=platform,
            capabilities=capabilities,
            attached_at=now,
            queue=asyncio.Queue(maxsize=_BUFFER),
        )
        self._players.setdefault(profile_id, []).append(player)
        logger.info(
            "playback_player_attached",
            extra={
                "player_id": player.id,
                "profile_id": str(profile_id),
                "platform": platform,
                "capabilities": sorted(capabilities),
            },
        )
        return player

    def detach(self, player: AttachedPlayer) -> None:
        remaining = self._players.get(player.profile_id, [])
        if player in remaining:
            remaining.remove(player)
        if not remaining:
            self._players.pop(player.profile_id, None)
        logger.info(
            "playback_player_detached",
            extra={"player_id": player.id, "profile_id": str(player.profile_id)},
        )

    def players(self, profile_id: UUID) -> list[AttachedPlayer]:
        """Attached players, most recently attached first.

        Attachment time stands in for "most recently active" (point 4). Clients subscribe when
        they become able to act and drop the subscription when they cannot, so foregrounding an
        app re-attaches it — which is the signal that ordering is trying to capture.
        """
        return sorted(
            self._players.get(profile_id, []), key=lambda p: p.attached_at, reverse=True
        )

    def send(
        self,
        profile_id: UUID,
        command: dict[str, Any],
        *,
        target: str | None = None,
        requires: str | None = None,
    ) -> AttachedPlayer:
        """Deliver one command, and return the player it went to.

        `requires` is the capability the command needs. A client that did not declare it is not a
        candidate — point 12 exists so that a well-formed "set the theme" reaching a client with no
        theme does not silently do nothing, which is the affordance-with-no-destination defect this
        project has hit four times.
        """
        candidates = self.players(profile_id)
        if target is not None:
            candidates = [p for p in candidates if p.id == target or p.name == target]
            if not candidates:
                raise NoPlayerAttached(
                    f"No attached player matches {target!r}. Attached: "
                    f"{[p.name for p in self.players(profile_id)] or 'none'}."
                )
        if requires is not None:
            able = [p for p in candidates if requires in p.capabilities]
            if not able:
                raise NoPlayerAttached(
                    f"No attached player can {requires!r}. Attached: "
                    f"{[(p.name, sorted(p.capabilities)) for p in candidates] or 'none'}."
                )
            candidates = able
        if not candidates:
            raise NoPlayerAttached(
                "No player is attached to this profile. Open Familiar on a device and try again — "
                "commands are delivered to a running client, not stored for later."
            )

        player = candidates[0]
        if player.queue.full():
            # Dropping the oldest keeps the newest instruction, which is the one the listener
            # actually meant. A backlog of stale transport commands helps nobody.
            try:
                player.queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - racing the consumer
                pass
        player.queue.put_nowait(command)
        logger.info(
            "playback_command_sent",
            extra={
                "player_id": player.id,
                "profile_id": str(profile_id),
                "command": command.get("type"),
            },
        )
        return player


#: One channel per process, matching point 6's in-process, ephemeral scope.
_channel = PlaybackCommandChannel()


def get_channel() -> PlaybackCommandChannel:
    return _channel
