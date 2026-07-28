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


def to_naive_utc(value: datetime | None) -> datetime | None:
    """Normalise a datetime that came from outside to naive UTC.

    Every timestamp in this schema is TIMESTAMP WITHOUT TIME ZONE, and `utcnow()` is
    naive, so an offset-aware value cannot be compared against or stored beside them —
    Python raises `TypeError: can't compare offset-naive and offset-aware datetimes`.

    That is not hypothetical. A browser sending `new Date().toISOString()` produces a
    `Z`-suffixed value, which Pydantic parses as offset-aware, so any endpoint accepting a
    client clock hits this on the first real request while passing tests written with
    naive fixtures.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
