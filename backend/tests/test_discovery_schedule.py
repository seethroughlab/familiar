"""Discovery runs continuously, in small batches, taking profiles in turn.

ADR-0099 point 3. A single nightly sweep is why one bad window cost a whole day:
the job either won the race at 03:00 or the library learned nothing for
twenty-four hours — and when it crashed it crashed on the same artist at the same
time, nineteen nights running.
"""

from app.services.background.manager import (
    DISCOVERY_BATCH_SIZE,
    DISCOVERY_INTERVAL_MINUTES,
)
from app.services.tasks.new_releases import MUSICBRAINZ_CALL_TIMEOUT_SECONDS

# The library this was sized against, so the arithmetic below can be rechecked
# rather than trusted.
LIBRARY_ARTISTS = 3453
RECHECK_WINDOW_DAYS = 7


def _checks_per_day() -> float:
    return DISCOVERY_BATCH_SIZE * (60 / DISCOVERY_INTERVAL_MINUTES) * 24


def test_the_rotation_can_keep_up_with_the_library():
    """Capacity must exceed what the re-check window demands.

    The defect this replaces was the opposite: 75 a day against a seven-day window
    is 525 slots for 839 eligible artists, so the tail was never reached. Any change
    to the interval or batch size has to keep this true.
    """
    needed_per_day = LIBRARY_ARTISTS / RECHECK_WINDOW_DAYS
    assert _checks_per_day() > needed_per_day, (
        f"{_checks_per_day():.0f}/day cannot sustain {LIBRARY_ARTISTS} artists "
        f"on a {RECHECK_WINDOW_DAYS}-day window ({needed_per_day:.0f}/day needed)"
    )


def test_the_upstream_duty_cycle_stays_polite():
    """MusicBrainz allows one request a second and is unauthenticated and free.

    A batch is at most `DISCOVERY_BATCH_SIZE` seconds of upstream time — two calls
    per artist in the worst case — against an interval measured in minutes. Raising
    the batch without lengthening the interval is the way to make this a bad
    neighbour, so the ratio is asserted rather than left to judgement.
    """
    worst_case_upstream_seconds = DISCOVERY_BATCH_SIZE * 2
    interval_seconds = DISCOVERY_INTERVAL_MINUTES * 60
    duty_cycle = worst_case_upstream_seconds / interval_seconds
    assert duty_cycle < 0.05, f"duty cycle {duty_cycle:.1%} is not a good citizen"


def test_one_stalled_artist_cannot_absorb_the_batch():
    """The per-call bound has to be small relative to the batch it protects."""
    worst_case_batch_seconds = DISCOVERY_BATCH_SIZE * MUSICBRAINZ_CALL_TIMEOUT_SECONDS * 2
    assert worst_case_batch_seconds < DISCOVERY_INTERVAL_MINUTES * 60, (
        "a fully stalled batch must still finish before its next trigger, or "
        "max_instances=1 silently drops ticks"
    )


# ---------------------------------------------------------------------------
# Profiles take turns (ADR-0099 point 3, the shared-library half)
# ---------------------------------------------------------------------------


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = str(value)


class _CursorHarness:
    """The cursor arithmetic from `_discovery_batch`, exercised on its own.

    Extracted rather than driving the real job because the job builds its own
    engine and session; the part that can silently regress is the indexing.
    """

    def __init__(self, profile_ids, redis):
        self.profile_ids = profile_ids
        self.redis = redis
        self.key = "familiar:discovery:profile_cursor"

    def next_profile(self):
        index = 0
        raw = self.redis.get(self.key)
        if raw is not None:
            index = int(raw) % len(self.profile_ids)
        self.redis.set(self.key, (index + 1) % len(self.profile_ids))
        return self.profile_ids[index]


def test_profiles_take_turns_rather_than_the_first_always_winning():
    """On a shared library one listener must not decide what everyone discovers.

    `_discovery_batch` used to `select(Profile.id).limit(1)`, so the first profile's
    play history drove every batch — while the rows it writes are not profile-scoped,
    so the whole household saw one person's taste.
    """
    harness = _CursorHarness(["a", "b", "c"], _FakeRedis())
    picked = [harness.next_profile() for _ in range(7)]
    assert picked == ["a", "b", "c", "a", "b", "c", "a"]


def test_a_lost_cursor_costs_one_batch_not_the_rotation():
    """The cursor is a hint in Redis, not state worth a table."""
    redis = _FakeRedis()
    harness = _CursorHarness(["a", "b", "c"], redis)
    harness.next_profile()
    harness.next_profile()
    redis.store.clear()
    assert harness.next_profile() == "a"


def test_the_cursor_survives_a_profile_being_removed():
    """A stale index must wrap rather than raise IndexError."""
    redis = _FakeRedis()
    redis.store["familiar:discovery:profile_cursor"] = "9"
    harness = _CursorHarness(["a", "b"], redis)
    assert harness.next_profile() == "b"  # 9 % 2 == 1
