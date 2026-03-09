"""Background event timeline utilities for operational diagnostics."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.services.redis_client import get_redis

logger = logging.getLogger(__name__)

BACKGROUND_EVENTS_KEY = "familiar:background:events"
MAX_BACKGROUND_EVENTS_STORED = 200
BACKGROUND_EVENTS_TTL_SECONDS = 48 * 60 * 60  # 48h


def record_background_event(event: str, details: dict[str, Any] | None = None) -> None:
    """Record a background event in Redis for timeline diagnostics."""
    payload = {
        "event": event,
        "details": details or {},
        "timestamp": datetime.now().isoformat(),
    }
    try:
        r = get_redis()
        r.lpush(BACKGROUND_EVENTS_KEY, json.dumps(payload))
        r.ltrim(BACKGROUND_EVENTS_KEY, 0, MAX_BACKGROUND_EVENTS_STORED - 1)
        r.expire(BACKGROUND_EVENTS_KEY, BACKGROUND_EVENTS_TTL_SECONDS)
    except Exception as e:
        logger.warning(f"Could not record background event {event}: {e}")


def get_recent_background_events(limit: int = 20) -> list[dict[str, Any]]:
    """Read recent background timeline events from Redis."""
    try:
        r = get_redis()
        events: list[bytes] = r.lrange(BACKGROUND_EVENTS_KEY, 0, limit - 1)  # type: ignore[assignment]
        return [json.loads(item) for item in events]
    except Exception:
        return []
