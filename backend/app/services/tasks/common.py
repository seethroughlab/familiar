"""Common utilities shared across task modules.

Redis constants, failure tracking, and memory logging.
"""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

from app.services.redis_client import get_redis

logger = logging.getLogger(__name__)


def get_memory_mb() -> float:
    """Get current process memory usage in MB."""
    try:
        import resource
        # Get memory in KB, convert to MB
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return usage.ru_maxrss / 1024  # macOS returns bytes, Linux returns KB
    except Exception:
        return 0.0


def log_memory(label: str) -> None:
    """Log current memory usage with a label."""
    mem_mb = get_memory_mb()
    logger.info(f"[MEMORY] {label}: {mem_mb:.1f} MB (PID {os.getpid()})")
    sys.stdout.flush()  # Ensure log is written before potential OOM


# Redis keys for progress tracking
SYNC_PROGRESS_KEY = "familiar:sync:progress"
TASK_FAILURES_KEY = "familiar:task:failures"
MAX_FAILURES_STORED = 50


def _record_task_failure(task_name: str, error: str, track_info: str | None = None) -> None:
    """Record a task failure in Redis for UI visibility."""
    try:
        r = get_redis()
        failure = json.dumps({
            "task": task_name,
            "error": error,
            "track": track_info,
            "timestamp": datetime.now().isoformat(),
        })
        r.lpush(TASK_FAILURES_KEY, failure)
        r.ltrim(TASK_FAILURES_KEY, 0, MAX_FAILURES_STORED - 1)
        r.expire(TASK_FAILURES_KEY, 86400)  # 24 hour expiry
    except Exception as e:
        logger.warning(f"Could not record task failure: {e}")


def get_recent_failures(limit: int = 10) -> list[dict[str, Any]]:
    """Get recent task failures from Redis."""
    try:
        r = get_redis()
        failures: list[bytes] = r.lrange(TASK_FAILURES_KEY, 0, limit - 1)  # type: ignore[assignment]
        return [json.loads(f) for f in failures]
    except Exception:
        return []


def clear_task_failures() -> None:
    """Clear all task failures from Redis."""
    try:
        r = get_redis()
        r.delete(TASK_FAILURES_KEY)
    except Exception:
        pass
