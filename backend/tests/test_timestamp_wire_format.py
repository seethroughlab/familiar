"""The wire format must not move when a timestamp field gains its type.

ADR-0007's follow-up called this "a wire-compatible schema change", and it only stays that way
because `UTCDateTime` serialises through `to_rfc3339` — the same function the producers used to
call by hand. These assert the bytes, not the annotation: a naive ISO string without an offset is
rejected outright by Swift's decoder and silently read as *local time* by JavaScript, which is the
defect `to_rfc3339` exists to prevent.
"""

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from app.api.schemas.common import UTCDateTime

NAIVE = datetime(2026, 1, 25, 23, 40, 43, 980516)
AWARE = datetime(2026, 1, 25, 23, 40, 43, 980516, tzinfo=UTC)
EXPECTED = "2026-01-25T23:40:43.980516Z"


class _Model(BaseModel):
    at: UTCDateTime
    maybe: UTCDateTime | None = None


def test_naive_utc_serialises_with_a_z():
    """The database columns are TIMESTAMP WITHOUT TIME ZONE, so naive is the normal case."""
    assert _Model(at=NAIVE).model_dump(mode="json")["at"] == EXPECTED


def test_aware_utc_serialises_identically():
    assert _Model(at=AWARE).model_dump(mode="json")["at"] == EXPECTED


def test_it_never_emits_a_bare_naive_isoformat():
    """`utcnow().isoformat()` was what `CuratedPromptsResponse.generated_at` shipped, and it is
    exactly what a client misreads as local time."""
    emitted = _Model(at=NAIVE).model_dump(mode="json")["at"]
    assert emitted != NAIVE.isoformat()
    assert emitted.endswith("Z")


def test_none_stays_none():
    assert _Model(at=NAIVE).model_dump(mode="json")["maybe"] is None


def test_the_schema_declares_the_format():
    """`WithJsonSchema` is what makes a generated client decode these as dates rather than strings.

    Asserted in serialization mode because that is the direction responses travel, and it is the
    mode `PlainSerializer` would otherwise degrade to a bare string.
    """
    schema = _Model.model_json_schema(mode="serialization")
    assert schema["properties"]["at"]["format"] == "date-time"


@pytest.mark.parametrize("offset_hours", [0, 5, -8])
def test_any_offset_normalises_to_utc(offset_hours):
    """A client may send an offset-aware value; what goes back out is always UTC."""
    from datetime import timedelta, timezone

    local = AWARE.astimezone(timezone(timedelta(hours=offset_hours)))
    assert _Model(at=local).model_dump(mode="json")["at"] == EXPECTED
