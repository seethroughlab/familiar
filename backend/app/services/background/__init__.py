"""In-process background task manager using asyncio and ProcessPoolExecutor.

Re-exports BackgroundManager and get_background_manager so callers can use:
    from app.services.background import BackgroundManager, get_background_manager
"""

from app.services.background.executors import (
    EXECUTOR_AUTO_RECOVERY_DELAY,
    EXECUTOR_MAX_CONSECUTIVE_FAILURES,
    EXECUTOR_RESET_COOLDOWN,
)
from app.services.background.manager import BackgroundManager, get_background_manager
from app.services.background.sync import SYNC_HEARTBEAT_STALE_SECONDS

__all__ = [
    "BackgroundManager",
    "get_background_manager",
    "EXECUTOR_RESET_COOLDOWN",
    "EXECUTOR_MAX_CONSECUTIVE_FAILURES",
    "EXECUTOR_AUTO_RECOVERY_DELAY",
    "SYNC_HEARTBEAT_STALE_SECONDS",
]
