"""One candidate in eight is deliberately not ambient.

The client consumes candidates sequentially — three on seed, two on each top-up — so the rate
has to be a property of **every prefix** of the returned list, not of the request. Both of
those numbers are constants in the Swift repository; anything tuned against them would be
tuned against something this code cannot see.

Pure functions, no database.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.services.ambient import excursion_phase, interleave_excursions


def candidates(prefix: str, count: int) -> list[str]:
    """Stand-ins. `interleave_excursions` never inspects its elements."""
    return [f"{prefix}{i}" for i in range(count)]


class TestTheRateHoldsForEveryPrefix:
    def test_a_prefix_of_any_length_carries_the_rate(self):
        """The property that survives the client changing how much it takes at a time."""
        period = 8
        for phase in range(period):
            out = interleave_excursions(
                candidates("f", 200), candidates("x", 200), period=period, phase=phase
            )
            for k in range(1, 41):
                seen = sum(1 for c in out[:k] if c.startswith("x"))
                expected = len([i for i in range(k) if i % period == phase])
                assert seen == expected, f"prefix {k}, phase {phase}: {out[:k]}"

    def test_the_mean_over_phases_is_exactly_one_in_period(self):
        period = 8
        for k in (8, 16, 24, 40):
            total = 0
            for phase in range(period):
                out = interleave_excursions(
                    candidates("f", 100), candidates("x", 100), period=period, phase=phase
                )
                total += sum(1 for c in out[:k] if c.startswith("x"))
            assert total / period == k / period

    def test_the_client_prefixes_specifically(self):
        """3 on seed and 2 per top-up — the numbers that actually occur."""
        period = 8
        for phase in range(period):
            out = interleave_excursions(
                candidates("f", 50), candidates("x", 50), period=period, phase=phase
            )
            assert sum(1 for c in out[:3] if c.startswith("x")) <= 1
            assert sum(1 for c in out[:2] if c.startswith("x")) <= 1


class TestItNeverInventsAnExcursion:
    def test_an_empty_excursion_list_returns_fit_order_untouched(self):
        fit = candidates("f", 10)
        assert interleave_excursions(fit, [], period=8, phase=0) == fit

    def test_running_out_of_excursions_falls_back_to_fit_order(self):
        out = interleave_excursions(candidates("f", 40), candidates("x", 2), period=8, phase=0)
        assert sum(1 for c in out if c.startswith("x")) == 2
        assert len(out) == 42

    def test_no_candidate_is_dropped_or_duplicated(self):
        fit, exc = candidates("f", 30), candidates("x", 5)
        out = interleave_excursions(fit, exc, period=8, phase=3)
        assert sorted(out) == sorted(fit + exc)

    def test_a_period_of_one_is_a_no_op_rather_than_all_excursions(self):
        fit = candidates("f", 5)
        assert interleave_excursions(fit, candidates("x", 5), period=1, phase=0) == fit


class TestThePhase:
    def test_it_is_stable_across_processes(self):
        """**Catches a switch to the builtin `hash()`**, which is PYTHONHASHSEED-salted: two
        uvicorn workers would disagree about the same track, and this test would pass locally
        and fail in CI."""
        track = UUID("3f2b8c14-9a7d-4e51-b0c6-2d8e5f1a7b93")
        assert excursion_phase(track, 8) == excursion_phase(track, 8)
        assert excursion_phase(track, 8) == 7

    def test_it_is_uniform_over_seeds(self):
        """Catches a hash reading only low bytes. A v4 UUID has fixed version and variant
        nibbles, so e.g. `bytes[6] % 8` is very nearly constant."""
        period = 8
        buckets = [0] * period
        for _ in range(10_000):
            buckets[excursion_phase(uuid4(), period)] += 1
        for count in buckets:
            assert 1050 < count < 1450, buckets

    def test_it_stays_in_range(self):
        for period in (2, 4, 8, 15):
            for _ in range(200):
                assert 0 <= excursion_phase(uuid4(), period) < period

    def test_a_degenerate_period_does_not_divide_by_zero(self):
        assert excursion_phase(uuid4(), 1) == 0
        assert excursion_phase(uuid4(), 0) == 0
