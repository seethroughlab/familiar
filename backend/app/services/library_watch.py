"""The server watches its library (ADR-0142).

Music copied into the library is scanned about three minutes after its folder goes quiet, without a
full sync: Familiar Server's behaviour, now in the server, so a Docker server on a NAS has it too.
`watchfiles` uses inotify on Linux and FSEvents on macOS. Measured on the NAS: a container sees the
host's writes into a bind-mounted folder, which is how music copied over SMB arrives.

- **Quiet first** (`FolderClock`): an album being copied produces events for minutes, and acting on
  the first imports one track of eleven (ADR-0117 point 3's measurement, for downloads).
- **Only the changed folders** (`run_folder_scan`): a full sync with nothing new takes about six
  minutes on 28,000 files. Nothing is marked missing; deletions and moves stay with the sync.
- **Never during a sync, never while paused:** folders wait, and are scanned afterwards.
- **`Inbox/` is ignored:** the Soulseek poll knows when a transfer has finished; a file appearing
  does not mean that.
- **If watching fails** (the watch limit, a mount that cannot be watched), the reason is kept for the
  Overview and the periodic sync covers the library, as it always has.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.config import AUDIO_EXTENSIONS

logger = logging.getLogger(__name__)

#: How long a folder must be quiet before it is scanned: three minutes, the period Familiar Server's
#: own watch used before this replaced it. `FAMILIAR_WATCH_QUIET_SECONDS` shortens it for the Mac
#: integration check, which adds a track and waits for it.
QUIET_SECONDS = float(os.environ.get("FAMILIAR_WATCH_QUIET_SECONDS", "180"))
#: How often quiet folders are looked for: never longer than the quiet period itself.
TICK_SECONDS = min(30.0, max(1.0, QUIET_SECONDS / 2))
INBOX_DIRNAME = "Inbox"


class FolderClock:
    """When each changed folder last changed, and which have been quiet long enough."""

    def __init__(self, quiet: float = QUIET_SECONDS) -> None:
        self.quiet = quiet
        self._last: dict[Path, float] = {}

    def touch(self, folder: Path, now: float) -> None:
        self._last[folder] = now

    def due(self, now: float) -> list[Path]:
        """Quiet folders, without any whose ancestor is also due: scanning that covers them."""
        quiet = {f for f, t in self._last.items() if now - t >= self.quiet}
        return sorted(f for f in quiet if not any(a in quiet for a in f.parents))

    def done(self, folders: list[Path]) -> None:
        for folder in folders:
            for f in [f for f in self._last if f == folder or folder in f.parents]:
                self._last.pop(f, None)

    @property
    def pending(self) -> int:
        return len(self._last)


def folder_to_scan(path: Path, roots: list[Path]) -> Path | None:
    """The folder a change should scan, or None: outside every library, inside an inbox, or not
    music. A new audio file means its folder; a new folder means itself (it may hold an album)."""
    for root in roots:
        if path != root and root not in path.parents:
            continue
        inbox = root / INBOX_DIRNAME
        if path == inbox or inbox in path.parents:
            return None
        if path.suffix.lower() in AUDIO_EXTENSIONS:
            return path.parent
        if path.is_dir():
            return path
        return None
    return None


@dataclass
class WatchStatus:
    """What the Overview shows: whether new music is noticed at once or at the next sync."""

    watching: bool = False
    reason: str | None = None
    roots: list[str] = field(default_factory=list)
    pending: int = 0
    last_scan_at: float | None = None
    last_result: dict | None = None


class LibraryWatch:
    def __init__(self) -> None:
        self.clock = FolderClock()
        self.status = WatchStatus(reason="not started")

    async def run(self, stop: asyncio.Event) -> None:
        from watchfiles import Change, awatch

        from app.config import settings

        roots = [Path(p) for p in settings.music_library_paths if Path(p).is_dir()]
        self.status = WatchStatus(roots=[str(r) for r in roots])
        if not roots:
            self.status.reason = "no library folder to watch"
            return
        ticker = asyncio.create_task(self._tick(stop))
        try:
            watcher = awatch(*roots, stop_event=stop, recursive=True, ignore_permission_denied=True)
            self.status.watching = True
            async for changes in watcher:
                now = time.monotonic()
                for change, raw in changes:
                    if change is Change.deleted:
                        continue  # the periodic sync handles deletions (ADR-0142 point 3)
                    folder = folder_to_scan(Path(raw), roots)
                    if folder is not None:
                        self.clock.touch(folder, now)
                self.status.pending = self.clock.pending
        except Exception as e:  # noqa: BLE001 - the watch limit, an unwatchable mount: say so, carry on
            self.status.watching = False
            self.status.reason = f"{type(e).__name__}: {e}"
            logger.warning(
                "Not watching the library (%s); new music is found at the next sync", self.status.reason
            )
        finally:
            ticker.cancel()

    async def _tick(self, stop: asyncio.Event) -> None:
        from app.services.background import get_background_manager
        from app.services.background.pause import background_pause
        from app.services.tasks.library_sync import run_folder_scan

        while not stop.is_set():
            await asyncio.sleep(TICK_SECONDS)
            due = self.clock.due(time.monotonic())
            if not due:
                continue
            await background_pause.wait_while_paused()
            bg = get_background_manager()
            if bg.is_sync_running():
                continue  # it may have passed discovery already; these wait for the next tick
            async with bg.library_lock:
                logger.info("Scanning %d changed folder(s): %s", len(due), ", ".join(str(f) for f in due[:5]))
                try:
                    result = await run_folder_scan(due)
                except Exception as e:  # noqa: BLE001 - the periodic sync is the net
                    result = {"status": "error", "error": str(e)}
                    logger.error("Scan of changed folders failed: %s", e, exc_info=True)
            self.clock.done(due)
            self.status.pending = self.clock.pending
            self.status.last_scan_at = time.time()
            self.status.last_result = result


_library_watch: LibraryWatch | None = None


def get_library_watch() -> LibraryWatch:
    global _library_watch
    if _library_watch is None:
        _library_watch = LibraryWatch()
    return _library_watch
