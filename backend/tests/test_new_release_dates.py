"""A release date the source could not possibly mean.

Two of 589 cached releases claimed **2913** and **2209** — year-only dates from MusicBrainz with a
digit typed wrong. They parse cleanly (`2913-01-01` is valid ISO), so nothing rejected them, and
because the list is ordered by date descending they sorted above every real release. The two most
prominent cards in Discover were the two worst rows in the table.

These run without a database: `plausible_release_date` is a pure function, which is most of why it
is one.
"""

from datetime import datetime, timedelta

from app.services.new_releases import (
    MAX_RELEASE_DATE_LOOKAHEAD,
    plausible_release_date,
)

NOW = datetime(2026, 8, 2)


def test_the_two_dates_found_in_the_live_cache_are_rejected() -> None:
    assert plausible_release_date(datetime(2913, 1, 1), now=NOW) is None
    assert plausible_release_date(datetime(2209, 1, 1), now=NOW) is None


def test_an_announced_future_release_is_kept() -> None:
    """MusicBrainz legitimately carries releases that have not happened yet.

    Rejecting those would empty the feature of the thing it is for — an album due in three months is
    exactly what "new releases from your artists" means.
    """
    assert plausible_release_date(datetime(2026, 11, 1), now=NOW) == datetime(2026, 11, 1)
    assert plausible_release_date(NOW + timedelta(days=300), now=NOW) is not None


def test_the_boundary_is_inclusive_and_just_beyond_it_is_not() -> None:
    edge = NOW + MAX_RELEASE_DATE_LOOKAHEAD
    assert plausible_release_date(edge, now=NOW) == edge
    assert plausible_release_date(edge + timedelta(seconds=1), now=NOW) is None


def test_old_dates_are_left_alone() -> None:
    """Only the future bound is checked.

    A reissue can legitimately carry an old first-release date, and deciding what that means for
    this feature is a different question from rejecting a date that cannot be true.
    """
    assert plausible_release_date(datetime(1913, 1, 1), now=NOW) == datetime(1913, 1, 1)
    assert plausible_release_date(datetime(1970, 6, 1), now=NOW) == datetime(1970, 6, 1)


def test_no_date_stays_no_date() -> None:
    assert plausible_release_date(None, now=NOW) is None


def test_a_mixed_awareness_comparison_does_not_raise() -> None:
    """The stored column is naive; a caller's clock may not be.

    Subtracting one from the other raises, and a crash inside a background sync is a worse outcome
    than trusting one odd date — so the mismatch is a pass, not an error.
    """
    from datetime import UTC

    aware = datetime(2913, 1, 1, tzinfo=UTC)
    assert plausible_release_date(aware, now=NOW) == aware

    naive_far_future = datetime(2913, 1, 1)
    aware_now = datetime(2026, 8, 2, tzinfo=UTC)
    assert plausible_release_date(naive_far_future, now=aware_now) == naive_far_future


def test_it_defaults_to_the_real_clock() -> None:
    """Called with no `now` in production, so the default path is the one that runs."""
    assert plausible_release_date(datetime(2913, 1, 1)) is None
    assert plausible_release_date(datetime(2020, 1, 1)) == datetime(2020, 1, 1)
