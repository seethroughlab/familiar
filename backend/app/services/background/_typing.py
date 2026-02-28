"""Type stubs for cross-mixin dependencies in the background package.

Provides a Protocol that declares the shared interface expected by mixin
classes. Each mixin inherits from this Protocol (under TYPE_CHECKING only)
so mypy can verify attribute access without introducing runtime overhead
or circular imports.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from app.services.redis_client import ResilientRedisClient


class _BackgroundManagerProtocol(Protocol):
    """Protocol describing the interface available to background mixins."""

    @property
    def redis(self) -> ResilientRedisClient: ...
    _scheduler: Any
    _current_track_id: str | None
    _last_task_started_at: float | None
    _executor_disabled: bool
    async def run_cpu_bound(self, func: Callable, *args: Any, max_retries: int = 1) -> Any: ...
    async def run_cpu_bound_ondemand(self, func: Callable, *args: Any) -> Any: ...
    async def _post_sync_backup(self) -> None: ...
