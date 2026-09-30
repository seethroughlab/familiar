"""Pause and resume background work, with a reason (ADR-0138 point 1).

Familiar Server pauses the server when its Mac is on battery, in Low Power Mode or running hot, and
the owner can pause it by hand. The NAS gets the same control, whether or not anything calls it.

What a pause means:
- **No new analysis is dispatched.** The sync's phase loops wait at the top of each pass, and their
  time cap and stall detector stop counting while they wait, so a pause is never mistaken for a
  stall.
- **Scheduled background jobs skip their run** and record that they did. A periodic sync skipped
  while paused runs once on resume, not once per missed slot (ADR-0138 point 5).
- **Work in flight finishes its current track.** `max_tasks_per_child=1` keeps that short.
- **Serving never pauses.** Streams, the API, and transcodes for a phone's downloads all carry on:
  they are what the owner and their phone are waiting for.

Process-local state in the API process, which is where the scheduler and the sync's phase loops
run. The spawned pool workers never consult it.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class BackgroundPause:
    paused: bool = False
    reason: str | None = None
    since: float | None = None  # wall clock, for display
    _since_monotonic: float | None = None
    skipped: set[str] = field(default_factory=set)

    def pause(self, reason: str) -> None:
        """Pause, or change the reason of a pause already in force."""
        if not self.paused:
            self.paused = True
            self.since = time.time()
            self._since_monotonic = time.monotonic()
        self.reason = reason

    def resume(self) -> set[str]:
        """Resume. Returns the jobs that skipped a run while paused, and forgets them."""
        skipped, self.skipped = self.skipped, set()
        self.paused = False
        self.reason = None
        self.since = None
        self._since_monotonic = None
        return skipped

    def note_skipped(self, job: str) -> None:
        self.skipped.add(job)

    async def wait_while_paused(self, poll_seconds: float = 2.0) -> float:
        """Return at once when not paused; otherwise wait for resume. Returns seconds waited."""
        if not self.paused:
            return 0.0
        started = time.monotonic()
        while self.paused:
            await asyncio.sleep(poll_seconds)
        return time.monotonic() - started

    def state(self) -> dict[str, object]:
        return {
            "paused": self.paused,
            "reason": self.reason,
            "since": self.since,
            "skipped_jobs": sorted(self.skipped),
        }


background_pause = BackgroundPause()
