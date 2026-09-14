"""SoulseekMixin: a settled download folder triggers a library sync (ADR-0117 point 3).

Familiar never moves what slskd downloads. The completed folder is mounted inside the library
(`/music/Inbox`, read-only), so the ordinary sync finds new files there and puts them in Pending
Review. The only Soulseek-specific piece is *when* that sync runs: the cron is every two hours,
and a listener who said "yes, fetch it" should not wait that long. So every two minutes, if a
slskd is configured, this asks it for its downloads and starts a sync when a folder has settled.

**Settled means every file is terminal and at least one succeeded.** Not "a file finished" —
slskd moves files to `complete` one at a time, and a sync on the first would import one track of
eleven and then fire ten more times. Not a filesystem watcher — inotify does not propagate
reliably across bind mounts, and the scanner has nothing to attach one to.

**Each folder triggers once per success count.** The count is remembered in Redis under a
30-day key; a folder that settles again with *more* successes (slskd retried the failures)
triggers again, one that settles the same way does not. Losing Redis costs at most one extra
sync per folder, which the incremental scan makes cheap.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._typing import _BackgroundManagerProtocol as _Base
else:
    _Base = object

logger = logging.getLogger(__name__)

#: Two minutes: a folder is noticed within that of finishing, and the poll is one small GET
#: against a service on the operator's own network — no rate limit to be a good citizen of.
SOULSEEK_POLL_MINUTES = 2

#: How long a folder's "already triggered" mark lives. slskd's own transfer history is pruned on
#: a similar horizon; past it a folder still listed would be one slskd has kept deliberately.
SETTLED_TTL_SECONDS = 30 * 24 * 3600

_KEY_PREFIX = "familiar:soulseek:settled:"


def settled_key(username: str, directory: str) -> str:
    """The Redis key for one folder. Hashed: directories carry backslashes and arbitrary bytes."""
    digest = hashlib.sha1(f"{username}\0{directory}".encode("utf-8", "surrogateescape")).hexdigest()
    return f"{_KEY_PREFIX}{digest}"


def folders_to_trigger(
    transfers: list[dict[str, Any]], already: dict[str, int]
) -> list[dict[str, Any]]:
    """Which settled folders deserve a sync, given what has triggered before.

    `already` maps `settled_key(...)` to the success count that last triggered. Pure, so the
    rule can be tested without Redis or slskd.
    """
    due: list[dict[str, Any]] = []
    for folder in transfers:
        if not folder.get("settled"):
            continue
        key = settled_key(folder.get("username") or "", folder.get("directory") or "")
        if folder.get("completed", 0) > already.get(key, 0):
            due.append(folder)
    return due


class SoulseekMixin(_Base):
    """Poll slskd for settled folders and start a sync when one appears."""

    async def _soulseek_poll(self) -> None:
        """APScheduler entry. Returns at once when no slskd is configured."""
        from app.services.app_settings import get_app_settings_service
        from app.services.soulseek import (
            SoulseekNotConfigured,
            SoulseekService,
            SoulseekUnreachable,
        )

        if not get_app_settings_service().has_soulseek_configured():
            return

        try:
            slsk = SoulseekService.from_settings()
        except SoulseekNotConfigured:
            return
        try:
            transfers = await slsk.downloads()
        except SoulseekUnreachable as e:
            # Debug, not warning: an operator who stopped slskd for the night should not find
            # 240 lines about it in the morning. The settings panel says the same thing louder.
            logger.debug("Soulseek poll: %s", e)
            return
        finally:
            await slsk.close()

        settled = [t for t in transfers if t.get("settled")]
        if not settled:
            return

        already: dict[str, int] = {}
        for folder in settled:
            key = settled_key(folder.get("username") or "", folder.get("directory") or "")
            try:
                raw = self.redis.get(key)
            except Exception:
                raw = None
            if raw:
                try:
                    already[key] = int(raw)
                except (TypeError, ValueError):
                    already[key] = 0

        due = folders_to_trigger(settled, already)
        if not due:
            return

        for folder in due:
            logger.info(
                "Soulseek folder settled: %s / %s (%d files) — triggering library sync",
                folder.get("username"),
                folder.get("directory"),
                folder.get("completed", 0),
            )

        if self.is_sync_running():
            # The running sync may or may not have walked the inbox yet. Leave the marks unset so
            # the next poll triggers again once it finishes; a second incremental pass is cheap.
            logger.info("Soulseek: sync already running; will re-check next poll")
            return

        await self.run_sync()
        for folder in due:
            key = settled_key(folder.get("username") or "", folder.get("directory") or "")
            try:
                self.redis.set(key, str(folder.get("completed", 0)), ex=SETTLED_TTL_SECONDS)
            except Exception as e:
                logger.debug("Soulseek: could not record settled folder: %s", e)

    def soulseek_sync_triggered(self, username: str, directory: str) -> bool:
        """Has a sync been started for this folder? For `get_soulseek_transfers` to report."""
        try:
            return bool(self.redis.get(settled_key(username, directory)))
        except Exception:
            return False
