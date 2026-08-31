"""Per-source health for discovery, recorded durably and acted on (ADR-0099 §6, §8, §10).

**Health here is control, not telemetry.** `backoff_until` is both the column the
Server page renders and the value the batch consults before deciding whether to call
a source. That is what makes "one source being down does not stop the others" a real
property rather than a reported one.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.db.models import DiscoverySourceHealth
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

#: Backoff doubles per consecutive failure, capped so a source that recovers is not
#: ignored for hours after the outage ends.
BACKOFF_BASE_SECONDS = 60
BACKOFF_MAX_SECONDS = 3600

#: Failure kinds. `rate_limited` is separated from `http_error` because it is the one
#: that is *expected* and self-correcting — treating a throttle as an outage would put
#: MusicBrainz permanently in backoff on a busy library.
FAILURE_KINDS = (
    "rate_limited",
    "timeout",
    "http_error",
    "bad_response",
    "not_configured",
    "crashed",
)


def backoff_seconds(consecutive_failures: int) -> int:
    """Exponential backoff, capped. One failure is a minute; six or more is an hour."""
    if consecutive_failures <= 0:
        return 0
    return min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (consecutive_failures - 1))


class SourceHealthRecorder:
    """Reads and writes `discovery_source_health`, on its own transaction.

    **The separate session is load-bearing, not tidiness.** ADR-0099 point 9 gives the
    discovery batch a per-artist `rollback()` on failure; if health shared that session,
    the rollback would erase the record of the very failure that caused it, and a
    crashing source would look permanently untouched. Every write here commits
    immediately and independently.
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def _row(self, db: Any, source: str) -> DiscoverySourceHealth:
        existing = (
            await db.execute(
                select(DiscoverySourceHealth).where(DiscoverySourceHealth.source == source)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        # The migration seeds the known sources; this covers one added in code before
        # its migration lands, which must not crash a batch.
        row = DiscoverySourceHealth(source=source)
        db.add(row)
        await db.flush()
        return row

    async def record_success(self, source: str, *, items: int = 0) -> None:
        """A call that reached the source and got a usable answer."""
        try:
            async with self._session_factory() as db:
                row = await self._row(db, source)
                now = utcnow().replace(tzinfo=None)
                row.last_attempt_at = now
                row.last_success_at = now
                row.consecutive_failures = 0
                row.backoff_until = None
                row.items_contributed = (row.items_contributed or 0) + items
                row.updated_at = now
                await db.commit()
        except Exception:
            # Health recording must never be the reason discovery fails. A lost
            # observation is worth less than the batch it would take down.
            logger.warning("source_health_record_failed", exc_info=True)

    async def record_failure(
        self,
        source: str,
        *,
        kind: str,
        detail: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        """A call that did not get a usable answer, and why."""
        try:
            async with self._session_factory() as db:
                row = await self._row(db, source)
                now = utcnow().replace(tzinfo=None)
                row.last_attempt_at = now
                row.last_failure_at = now
                row.last_failure_kind = kind if kind in FAILURE_KINDS else "http_error"
                row.last_failure_detail = (detail or "")[:2000] or None
                row.consecutive_failures = (row.consecutive_failures or 0) + 1
                # An explicit Retry-After is the source telling us when to come back and
                # is always preferred to our guess — including when it is *shorter*.
                wait = (
                    retry_after_seconds
                    if retry_after_seconds is not None
                    else backoff_seconds(row.consecutive_failures)
                )
                row.backoff_until = now + timedelta(seconds=wait)
                row.updated_at = now
                await db.commit()
        except Exception:
            logger.warning("source_health_record_failed", exc_info=True)

    async def should_skip(self, source: str) -> bool:
        """True while a source is backing off, so callers can move to the next one."""
        try:
            async with self._session_factory() as db:
                row = (
                    await db.execute(
                        select(DiscoverySourceHealth).where(
                            DiscoverySourceHealth.source == source
                        )
                    )
                ).scalar_one_or_none()
                if row is None or row.backoff_until is None:
                    return False
                return row.backoff_until > utcnow().replace(tzinfo=None)
        except Exception:
            # If health cannot be read, attempt the call. Skipping on an unknown state
            # would let a database blip silently stop discovery — the failure mode this
            # whole ADR exists to prevent.
            logger.warning("source_health_read_failed", exc_info=True)
            return False


def source_enabled(source: str) -> bool:
    """Whether this source may be contacted at all (ADR-0099 point 12).

    Two gates, and the master one is the point: `discovery_enabled` off means **no
    discovery request leaves the machine**, whichever source is asking. The
    per-source flags exist so that turning one off in response to it misbehaving is
    not the same as turning discovery off entirely.

    Read at call time rather than cached, so a toggle in the admin UI takes effect on
    the next batch rather than at the next restart.

    **Read off the settings object directly, not through `get_effective`.** That
    helper resolves precedence with `if app_value:` — plain truthiness — so a boolean
    explicitly set to `False` falls through every branch and comes back as `None`,
    indistinguishable from unset. It is fine for the API keys it was written for,
    where empty means absent; it cannot express a disabled flag. Every other boolean
    setting in the codebase reads the attribute directly for the same reason.
    """
    from app.services.app_settings import get_app_settings_service

    app_settings = get_app_settings_service().get()
    if not getattr(app_settings, "discovery_enabled", True):
        return False
    # A source with no flag of its own is governed by the master switch alone —
    # `discovery_batch` is the job itself, not an upstream.
    return bool(getattr(app_settings, f"discovery_{source}_enabled", True))


def get_recorder() -> SourceHealthRecorder:
    """A recorder backed by its own engine, per the class docstring."""
    from app.db.session import create_task_engine_session

    _engine, session_factory = create_task_engine_session()
    return SourceHealthRecorder(session_factory)
