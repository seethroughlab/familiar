"""Resilient Redis client with automatic retry and timeout configuration.

Provides a Redis client wrapper that handles transient failures gracefully:
- Automatic retries with exponential backoff
- Configurable socket timeouts
- Graceful degradation when Redis is unavailable
"""

import functools
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

import redis

from app.config import settings

logger = logging.getLogger(__name__)

# Retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY = 0.1  # 100ms base delay
DEFAULT_RETRY_MAX_DELAY = 2.0  # 2 second max delay

# Socket timeout configuration
DEFAULT_SOCKET_CONNECT_TIMEOUT = 5.0  # 5 seconds to establish connection
DEFAULT_SOCKET_TIMEOUT = 5.0  # 5 seconds for read/write operations

T = TypeVar("T")


def with_retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    max_delay: float = DEFAULT_RETRY_MAX_DELAY,
    retryable_exceptions: tuple[type[Exception], ...] = (
        redis.ConnectionError,
        redis.TimeoutError,
        ConnectionResetError,
        BrokenPipeError,
    ),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator that adds retry logic with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Initial delay between retries in seconds (default: 0.1)
        max_delay: Maximum delay between retries in seconds (default: 2.0)
        retryable_exceptions: Exception types that trigger a retry

    Returns:
        Decorated function with retry logic
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    if attempt < max_retries:
                        # Calculate delay with exponential backoff
                        delay = min(base_delay * (2**attempt), max_delay)
                        logger.warning(
                            f"Redis operation {func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                            f"Retrying in {delay:.2f}s..."
                        )
                        time.sleep(delay)  # Note: sync sleep is intentional — sync redis client
                    else:
                        logger.error(
                            f"Redis operation {func.__name__} failed after {max_retries + 1} attempts: {e}"
                        )
                        raise

            # This should never be reached, but satisfies type checker
            if last_exception:
                raise last_exception
            raise RuntimeError("Unexpected retry loop exit")

        return wrapper

    return decorator


class ResilientRedisClient:
    """Redis client wrapper with automatic retry and graceful degradation.

    Wraps common Redis operations with:
    - Automatic retry on transient failures
    - Configurable socket timeouts
    - Error logging for debugging

    Usage:
        client = ResilientRedisClient()
        client.set("key", "value")  # Automatically retries on failure
        value = client.get("key")
    """

    def __init__(
        self,
        redis_url: str | None = None,
        socket_connect_timeout: float = DEFAULT_SOCKET_CONNECT_TIMEOUT,
        socket_timeout: float = DEFAULT_SOCKET_TIMEOUT,
    ) -> None:
        """Initialize the resilient Redis client.

        Args:
            redis_url: Redis connection URL (defaults to settings.redis_url)
            socket_connect_timeout: Timeout for establishing connection
            socket_timeout: Timeout for read/write operations
        """
        url = redis_url or settings.redis_url
        self._client = redis.from_url(
            url,
            socket_connect_timeout=socket_connect_timeout,
            socket_timeout=socket_timeout,
            retry_on_timeout=True,  # Built-in retry on timeout
        )

    @property
    def client(self) -> redis.Redis:
        """Access the underlying Redis client."""
        return self._client

    @with_retry()
    def get(self, key: str) -> bytes | None:
        """Get a value from Redis with retry logic."""
        return self._client.get(key)

    @with_retry()
    def set(
        self,
        key: str,
        value: str | bytes,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool | None:
        """Set a value in Redis with retry logic."""
        return self._client.set(key, value, ex=ex, px=px, nx=nx, xx=xx)

    @with_retry()
    def delete(self, *keys: str) -> int:
        """Delete keys from Redis with retry logic."""
        return self._client.delete(*keys)

    @with_retry()
    def exists(self, *keys: str) -> int:
        """Check if keys exist in Redis with retry logic."""
        return self._client.exists(*keys)

    @with_retry()
    def expire(self, key: str, seconds: int) -> bool:
        """Set key expiration with retry logic."""
        return self._client.expire(key, seconds)

    @with_retry()
    def lpush(self, key: str, *values: str | bytes) -> int:
        """Push values to list with retry logic."""
        return self._client.lpush(key, *values)

    @with_retry()
    def lrange(self, key: str, start: int, end: int) -> list[bytes]:
        """Get list range with retry logic."""
        return self._client.lrange(key, start, end)

    @with_retry()
    def ltrim(self, key: str, start: int, end: int) -> bool:
        """Trim list with retry logic."""
        return self._client.ltrim(key, start, end)

    @with_retry()
    def setex(self, key: str, seconds: int, value: str | bytes) -> bool:
        """Set a value with expiration time in seconds."""
        return self._client.setex(key, seconds, value)

    def scan_iter(self, match: str | None = None, count: int | None = None):
        """Iterate over keys matching a pattern.

        Note: This returns an iterator directly from the underlying client.
        Retry logic is not applied to the iteration itself, but the initial
        connection is handled by the underlying client's retry_on_timeout setting.
        """
        return self._client.scan_iter(match=match, count=count)

    def ping(self) -> bool:
        """Check if Redis is available (no retry, used for health checks)."""
        try:
            return self._client.ping()
        except Exception:
            return False


# Global singleton instance
_resilient_redis: ResilientRedisClient | None = None


def get_resilient_redis() -> ResilientRedisClient:
    """Get the global resilient Redis client instance."""
    global _resilient_redis
    if _resilient_redis is None:
        _resilient_redis = ResilientRedisClient()
    return _resilient_redis


# Convenience alias used throughout the codebase
def get_redis() -> ResilientRedisClient:
    """Get resilient Redis client for progress updates.

    The resilient client automatically retries on transient failures
    and has configured socket timeouts.
    """
    return get_resilient_redis()
