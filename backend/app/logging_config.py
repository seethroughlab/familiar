"""Structured logging configuration for production debugging.

In development: Human-readable colored output
In production: JSON-formatted logs for log aggregation systems

Also provides an in-memory ring buffer of recent logs for diagnostics export.
"""

import json
import logging
import sys
import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any

from app.config import settings

# ============================================================================
# In-Memory Log Buffer for Diagnostics
# ============================================================================

class LogBuffer:
    """Thread-safe ring buffer for recent log entries.

    Used to capture recent logs for diagnostics export when users report issues.
    """

    def __init__(self, maxlen: int = 500):
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, entry: dict[str, Any]) -> None:
        """Add a log entry to the buffer."""
        with self._lock:
            self._buffer.append(entry)

    def get_entries(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Get log entries, optionally limited to the most recent N entries."""
        with self._lock:
            entries = list(self._buffer)
        if limit and limit < len(entries):
            entries = entries[-limit:]
        return entries

    def clear(self) -> None:
        """Clear all entries from the buffer."""
        with self._lock:
            self._buffer.clear()


# Global log buffer instance (500 entries ~= 10-15 minutes of activity)
_log_buffer = LogBuffer(maxlen=500)


class BufferedHandler(logging.Handler):
    """Handler that writes log entries to the in-memory ring buffer."""

    def __init__(self) -> None:
        super().__init__()
        self._formatter = logging.Formatter()

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record to the buffer."""
        try:
            entry: dict[str, Any] = {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }

            # Add request ID if present
            if hasattr(record, "request_id"):
                entry["request_id"] = record.request_id

            # Add exception info if present
            if record.exc_info:
                entry["exception"] = self._formatter.formatException(record.exc_info)

            _log_buffer.add(entry)
        except Exception:
            # Don't let buffer errors break logging
            pass


def get_recent_logs(limit: int = 500) -> list[dict[str, Any]]:
    """Get recent log entries for diagnostics export.

    Args:
        limit: Maximum number of entries to return (default 500)

    Returns:
        List of log entry dicts with timestamp, level, logger, message
    """
    return _log_buffer.get_entries(limit)


# ============================================================================
# Log Formatters
# ============================================================================


class JSONFormatter(logging.Formatter):
    """JSON log formatter for production environments."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields from record
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "track_id"):
            log_data["track_id"] = record.track_id
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add any extra attributes
        extra_keys = set(record.__dict__.keys()) - {
            "name", "msg", "args", "created", "filename", "funcName",
            "levelname", "levelno", "lineno", "module", "msecs",
            "pathname", "process", "processName", "relativeCreated",
            "stack_info", "exc_info", "exc_text", "thread", "threadName",
            "taskName", "message", "request_id", "user_id", "track_id",
            "duration_ms",
        }
        for key in extra_keys:
            value = getattr(record, key)
            if value is not None and not key.startswith("_"):
                log_data[key] = value

        return json.dumps(log_data)


class DevelopmentFormatter(logging.Formatter):
    """Human-readable colored formatter for development."""

    COLORS = {
        "DEBUG": "\033[36m",    # Cyan
        "INFO": "\033[32m",     # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",    # Red
        "CRITICAL": "\033[35m", # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        reset = self.RESET

        # Format time
        time_str = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")

        # Build message
        msg = f"{color}{time_str} {record.levelname:8}{reset} [{record.name}] {record.getMessage()}"

        # Add request ID if present
        if hasattr(record, "request_id"):
            msg = f"{color}{time_str} {record.levelname:8}{reset} [{record.request_id}] [{record.name}] {record.getMessage()}"

        # Add exception if present
        if record.exc_info:
            msg += f"\n{self.formatException(record.exc_info)}"

        return msg


def setup_logging() -> None:
    """Configure logging based on environment."""
    # Determine log level
    log_level = logging.DEBUG if settings.debug else logging.INFO

    # Choose formatter based on environment
    formatter: logging.Formatter
    if settings.debug:
        formatter = DevelopmentFormatter()
    else:
        formatter = JSONFormatter()

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add stdout handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Add buffered handler for diagnostics export
    buffered_handler = BufferedHandler()
    buffered_handler.setLevel(logging.DEBUG)  # Capture all levels for diagnostics
    root_logger.addHandler(buffered_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name.

    Usage:
        from app.logging_config import get_logger
        logger = get_logger(__name__)
        logger.info("Message", extra={"request_id": "abc123"})
    """
    return logging.getLogger(name)
