"""Timezone-safe UTC time utilities.

Replaces deprecated datetime.utcnow() with a modern equivalent that
returns naive UTC datetimes (compatible with TIMESTAMP WITHOUT TIME ZONE columns).
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime.

    This is the modern replacement for the deprecated datetime.utcnow().
    Uses datetime.now(UTC) internally but strips tzinfo to stay compatible
    with PostgreSQL TIMESTAMP WITHOUT TIME ZONE columns.
    """
    return datetime.now(UTC).replace(tzinfo=None)
