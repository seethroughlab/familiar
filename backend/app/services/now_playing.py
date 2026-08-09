"""What a listener is hearing right now, in memory, for as long as the claim is credible.

[ADR-0030](../../../docs/decisions/ADR-0030-scrobbling-is-the-servers-job.md) point 6 added
`POST /tracks/{id}/started` and said what it was for:

> Deliberately generic rather than a Last.fm endpoint: "this track just started" is a fact about
> listening, and the server is free to do more with it later — presence, listening-together, a
> recently-started feed. Today it forwards to Last.fm as now-playing and nothing else.

This is the "later". **Every client already sends the signal**, so an MCP host can be told what is
playing without a single client change — and without the command channel gaining a return
direction, which ADR-0044 point 1 keeps it free of.

**It is a claim about the present, and it expires.** The signal says a track *started*; nothing
reports a pause, a stop, or a skip to something else. So a start is trusted for as long as the
track could still be playing and then forgotten. Reporting a track that finished twenty minutes ago
as "now playing" would be worse than saying nothing, because a listener cannot tell a stale answer
from a wrong one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

logger = logging.getLogger(__name__)

#: How long an unknown-length track is credible for. Longer than most songs, short enough that a
#: forgotten session does not answer for the rest of the day.
_DEFAULT_CREDIBLE_SECONDS = 10 * 60

#: Grace on top of a known duration, covering the gap between a track ending and the next start
#: arriving — a client is not obliged to tell us anything the moment a track stops.
_GRACE_SECONDS = 30


@dataclass(frozen=True)
class StartedTrack:
    track_id: UUID
    title: str | None
    artist: str | None
    album: str | None
    duration_seconds: float | None
    started_at: float

    def credible_until(self) -> float:
        span = (
            self.duration_seconds + _GRACE_SECONDS
            if self.duration_seconds
            else _DEFAULT_CREDIBLE_SECONDS
        )
        return self.started_at + span

    def describe(self, now: float) -> dict[str, object]:
        elapsed = max(0.0, now - self.started_at)
        return {
            "track_id": str(self.track_id),
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "duration_seconds": self.duration_seconds,
            "started_seconds_ago": round(elapsed, 1),
            # Said plainly, because the difference matters to whoever reads it: the server knows
            # this track *started* and was never told it stopped.
            "confidence": "reported_start_not_confirmed_still_playing",
        }


class NowPlayingRegistry:
    """Last credible start per profile. In memory, like the command channel, and for the same reason."""

    def __init__(self) -> None:
        self._latest: dict[UUID, StartedTrack] = {}

    def record(self, profile_id: UUID, started: StartedTrack) -> None:
        self._latest[profile_id] = started

    def current(self, profile_id: UUID, now: float) -> StartedTrack | None:
        started = self._latest.get(profile_id)
        if started is None:
            return None
        if now >= started.credible_until():
            # Forget rather than report a stale claim. A wrong answer here is worse than none.
            self._latest.pop(profile_id, None)
            return None
        return started

    def clear(self, profile_id: UUID) -> None:
        self._latest.pop(profile_id, None)


_registry = NowPlayingRegistry()


def get_registry() -> NowPlayingRegistry:
    return _registry
