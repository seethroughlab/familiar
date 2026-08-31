"""What a caller is told about results whose age it cannot see (ADR-0099 point 7).

This replaces `test_new_release_budget.py`, whose subject no longer exists: the
scan budgets bounded a live MusicBrainz call on the request path, and there is no
longer a live call to bound. The rule those tests protected survives and gets
stricter — an empty list must not be reported as a confident "nothing new" when
the real answer is "discovery is stale" or "discovery has never run".
"""

from datetime import timedelta

from app.services.new_releases import STALE_AFTER_HOURS, new_release_note
from app.utils.time import utcnow


def _note(**kw):
    base = dict(found=0, new_count=0, days_back=90, as_of=None, age_hours=None)
    base.update(kw)
    return new_release_note(**base)


def test_never_run_is_not_reported_as_nothing_new():
    """The state that held for nineteen nights while the job crashed.

    `as_of=None` means discovery has never written a row. Saying "no new releases"
    would be a confident wrong answer about the library rather than a true one
    about the system.
    """
    note = _note(as_of=None)
    assert "not the same as" in note
    assert "nothing new" in note
    assert "no new releases" not in note.lower().replace("'nothing new'", "")


def test_stale_results_say_how_old_they_are():
    """Point 7: a host reading this aloud must be able to say 'as of N days ago'."""
    as_of = utcnow().replace(tzinfo=None) - timedelta(days=5)
    note = _note(found=7, new_count=7, as_of=as_of, age_hours=120.0)
    assert "5 day(s) ago" in note
    assert "stale" in note


def test_current_results_do_not_mention_staleness():
    as_of = utcnow().replace(tzinfo=None) - timedelta(hours=2)
    note = _note(found=7, new_count=3, as_of=as_of, age_hours=2.0)
    assert "stale" not in note
    assert "7 recent releases" in note
    assert "3 not in library" in note


def test_empty_but_current_is_a_real_nothing_new():
    """The one case where "nothing new" is the honest answer."""
    as_of = utcnow().replace(tzinfo=None) - timedelta(hours=1)
    note = _note(found=0, as_of=as_of, age_hours=1.0)
    assert note == "No new releases in the last 90 days."


def test_the_three_states_produce_three_different_notes():
    """The whole point of the helper, asserted directly.

    Found-nothing, stale and never-run all return an empty release list. If any two
    of them read the same, the distinction the note exists for is gone.
    """
    fresh = utcnow().replace(tzinfo=None) - timedelta(hours=1)
    stale = utcnow().replace(tzinfo=None) - timedelta(hours=STALE_AFTER_HOURS + 1)

    notes = {
        _note(found=0, as_of=fresh, age_hours=1.0),
        _note(found=0, as_of=stale, age_hours=STALE_AFTER_HOURS + 1),
        _note(found=0, as_of=None, age_hours=None),
    }
    assert len(notes) == 3


def test_staleness_threshold_allows_a_normal_rotation():
    """Discovery rotates over roughly a day, so yesterday is not a problem."""
    assert STALE_AFTER_HOURS >= 48, "a one-day-old result is normal operation"
    assert STALE_AFTER_HOURS <= 96, "a week-old result must not read as current"
