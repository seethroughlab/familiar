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


def to_rfc3339(value: datetime | None) -> str | None:
    """Format a timestamp for the wire, as RFC 3339 UTC.

    Every datetime in this schema is naive UTC, because the columns are TIMESTAMP WITHOUT TIME
    ZONE and `utcnow()` strips tzinfo to match. `datetime.isoformat()` on a naive value therefore
    emits no offset — `2026-03-31T19:33:33.063837` — which is **not** RFC 3339, and clients
    disagree about what it means:

    - Swift's ISO8601 decoder rejects it outright, so a generated client fails to decode a
      response it otherwise understands.
    - JavaScript accepts it and parses it as *local* time, so the web app has been displaying
      every server timestamp shifted by the viewer's UTC offset. `new Date()` on the value above
      yields 23:33Z in a UTC-4 zone — four hours wrong, silently.

    Appending the offset is a statement of fact rather than a conversion: these values already are
    UTC, the wire format simply never said so.
    """
    if value is None:
        return None
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


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
