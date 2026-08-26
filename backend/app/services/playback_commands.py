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

#: The capability vocabulary, named on the server so both ends cannot drift.
#:
#: Freeform strings would have been enough while the Mac is the only client, and would have been a
#: quiet trap the moment there were two: a client declaring "playback" where the server requires
#: "play" matches nothing, and the symptom is commands going somewhere else — or nowhere — with no
#: error anywhere. A closed set makes that a rejection at subscribe time instead.
KNOWN_CAPABILITIES = frozenset(
    {
        "play",  # transport: play, pause, next, previous
        "queue",  # replace or extend the playback queue
        "seek",
        "volume",
        "crossfade",
        "effects",
        "theme",
        "visualizer",
        "shuffle_weights",
        "normalization",
        # ADR-0053. `navigate` roots the client's interface on a `LibraryRoute`; `screenshot` has
        # it draw its own window and upload the result. Both are declared, not assumed, so a tool
        # is offered only where something can actually carry it out.
        "navigate",
        "screenshot",
    }
)


class UnknownCapability(ValueError):
    """A client declared a capability this server has no name for."""

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
        unknown = capabilities - KNOWN_CAPABILITIES
        if unknown:
            # Rejected here, loudly, rather than accepted and never matched. A capability the
            # server has no name for can never route a command, so silence would mean a client
            # that looks attached and cannot be reached for the thing it thinks it can do.
            raise UnknownCapability(
                f"Unknown capabilities: {sorted(unknown)}. "
                f"Known: {sorted(KNOWN_CAPABILITIES)}."
            )
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
        # Checked first, and deliberately. Filtering by target or capability before this would
        # report "no attached player can 'play'" when the truth is that nothing is running at all
        # — a capability problem the listener cannot act on, in place of one they can.
        if not candidates:
            raise NoPlayerAttached(
                "No player is attached to this profile. Open Familiar on a device and try again — "
                "commands are delivered to a running client, not stored for later."
            )
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


# ---------------------------------------------------------------------------
# Artifacts (ADR-0053)
# ---------------------------------------------------------------------------


class ArtifactTimeout(Exception):
    """The client never uploaded what it was asked for.

    Raised so a tool can *answer* — "the client did not respond in time" — rather than hang.
    ADR-0044 point 5's rule, which nothing on this channel is exempt from.
    """


class ArtifactStore:
    """Outstanding requests for something the client has to send back.

    **Held in memory and dropped once read** (ADR-0053 point 8). A screenshot of somebody's
    library is not a thing to accumulate on a server because deleting it was more work than
    keeping it: there is no table, no directory, and therefore no retention rule to get wrong.

    One entry is one unanswered question. The id names the question, not the device — it lives
    for as long as the asking does, which is why this does not reopen ADR-0029 point 5's decision
    to leave device identity uninvented.
    """

    def __init__(self) -> None:
        self._waiting: dict[str, asyncio.Future[tuple[bytes, str]]] = {}
        # Whose question each id belongs to. The upload endpoint is profile-scoped like every
        # other mutating route here, and this is what lets it check rather than merely require:
        # holding *a* profile is not the same as holding the one that asked.
        self._owners: dict[str, UUID] = {}

    def open(self, request_id: str, profile_id: UUID) -> asyncio.Future[tuple[bytes, str]]:
        future: asyncio.Future[tuple[bytes, str]] = asyncio.get_running_loop().create_future()
        self._waiting[request_id] = future
        self._owners[request_id] = profile_id
        return future

    def deliver(
        self, request_id: str, data: bytes, content_type: str, *, profile_id: UUID
    ) -> bool:
        """Hand an upload to whoever asked. False when nobody did — a late or unknown answer.

        **The entry is left in place rather than popped**, and `wait` removes it once it has read
        the result. Popping here looked tidier and lost screenshots: a client fast enough to upload
        before the tool reached its `await` would resolve a future nobody was holding any more, and
        the tool would then find no outstanding request and report a timeout for an image that had
        already arrived. Rare, load-dependent, and invisible — the worst combination.

        A late upload is still discarded. The question it answered has been answered with a
        timeout, and keeping the image would be keeping it forever (point 8).
        """
        future = self._waiting.get(request_id)
        if future is None or future.done():
            return False
        if self._owners.get(request_id) != profile_id:
            # A profile answering somebody else's question. Refused rather than accepted, and
            # reported to the caller the same way a late upload is — there is nothing useful it
            # could do with the difference, and saying "wrong profile" would confirm the id exists.
            return False
        future.set_result((data, content_type))
        return True

    async def wait(self, request_id: str, timeout: float) -> tuple[bytes, str]:
        future = self._waiting.get(request_id)
        if future is None:
            raise ArtifactTimeout(f"No outstanding request {request_id}")
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except TimeoutError as exc:
            raise ArtifactTimeout(
                f"The client did not answer within {timeout:.0f}s"
            ) from exc
        finally:
            # Read or not, the question is over: nothing is kept for a later reader, because there
            # is never a later reader and the artifact is a picture of somebody's library.
            self._waiting.pop(request_id, None)
            self._owners.pop(request_id, None)

    def cancel(self, request_id: str) -> None:
        self._waiting.pop(request_id, None)
        self._owners.pop(request_id, None)


_artifacts = ArtifactStore()


def get_artifact_store() -> ArtifactStore:
    return _artifacts
