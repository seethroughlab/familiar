"""The cutoff that keeps ADR-0004's threshold from being derived from a bug."""

from datetime import datetime

import pytest
from sqlalchemy import select

from app.db.models import PlayEvent
from app.services.listening_feedback import (
    FEEDBACK_TRUSTWORTHY_SINCE,
    trustworthy_feedback_only,
)


def test_cutoff_is_the_day_the_web_client_started_reporting_at_the_end():
    """`familiar` #57. Moving this earlier silently readmits the 0.5-by-construction rows."""
    assert FEEDBACK_TRUSTWORTHY_SINCE == datetime(2026, 8, 1)


def test_cutoff_is_naive_to_match_the_column():
    """`PlayEvent.started_at` is TIMESTAMP WITHOUT TIME ZONE; an aware bound raises."""
    assert FEEDBACK_TRUSTWORTHY_SINCE.tzinfo is None


def test_filter_compiles_into_the_expected_predicate():
    clause = str(
        select(PlayEvent.id).where(trustworthy_feedback_only()).compile()
    )
    assert "play_events.started_at >=" in clause


@pytest.mark.parametrize(
    ("started_at", "trustworthy"),
    [
        (datetime(2026, 7, 31, 23, 59, 59), False),  # the last contaminated day
        (datetime(2026, 8, 1, 0, 0, 0), True),  # the boundary is inclusive
        (datetime(2026, 8, 2), True),
        (datetime(2026, 7, 27), False),  # the first day of data at all
    ],
)
def test_boundary_is_inclusive_and_excludes_everything_before(started_at, trustworthy):
    """Expressed as data rather than as a date comparison, so an off-by-one shows up."""
    assert (started_at >= FEEDBACK_TRUSTWORTHY_SINCE) is trustworthy
