"""How ambient-adjacent a track is, from audio features alone.

One definition in two forms — Python for scoring rows already in memory, SQL for gating a
query before the rows exist. `test_ambient_fitness.py` asserts they agree, because the
realistic failure here is a NULL-handling or precedence divergence that nothing else would
notice until a pool came back the wrong shape.

**Features only.** No genre tags: `Track.genre` is free text from file metadata with no
controlled vocabulary. No CLAP text embedding: that would make every candidate query depend
on an inference-time text encode and on ADR-0105's external runtime. Every input here is a
column `TrackAnalysis` already carries for all 26,000 analysed tracks.

This replaces three inline copies that had quietly diverged:

- `pick_surprise_seed` scored energy as proximity to 0.25 with a 3.33 slope.
- `find_seed_by_artist` targeted 0.4 with no slope at all, so its energy term spanned only
  [0.4, 1.0]. Given one artist with tracks at energy 0.20 and 0.45, the two functions picked
  **different** tracks and disagreed about which was the more ambient.
- `offline_manifest.eligible_seed_ids` inlined the gates a third time, under a docstring
  claiming they matched `pick_surprise_seed`.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, Float, cast, func

from app.db.models import Track, TrackAnalysis

#: Ambient-adjacency is a **ceiling, not a target** — one-sided on both energy and tempo.
#:
#: This is the deliberate difference from the copies being replaced. Scoring energy as
#: proximity to 0.25 made a 0.10-energy drone score *worse* than a 0.25 one. That was
#: defensible where it lived — choosing the most representative seed from an already-gated
#: set — and is wrong as a floor, where anything quiet enough should simply qualify.
AMBIENT_ENERGY_CEILING = 0.30
AMBIENT_ENERGY_SPAN = 0.30  # 1.0 at or below 0.30, falling to 0.0 at 0.60

AMBIENT_BPM_CEILING = 90.0
AMBIENT_BPM_SPAN = 60.0  # 1.0 at or below 90, falling to 0.0 at 150

#: Sums to 1.0, so fitness is directly readable as a fraction.
FITNESS_WEIGHTS = {
    "energy": 0.30,
    "tempo": 0.15,
    "acousticness": 0.20,
    "instrumentalness": 0.25,
    "speechiness": 0.10,
}

#: A missing feature reads as neutral, **not** as zero.
#:
#: `ambient._safe_float` returns 0.0 for NULL, which is right for a proximity term (an
#: unknown value should not look close) and wrong here: 0.0 is maximally *unambient*, so
#: inheriting it would silently exile every track whose analyser never wrote `acousticness`
#: from ambient entirely. This is a new function and does not have to inherit that.
NEUTRAL = 0.5


def _ramp(value: float, ceiling: float, span: float) -> float:
    """1.0 at or below `ceiling`, falling linearly to 0.0 at `ceiling + span`."""
    if value <= ceiling:
        return 1.0
    return max(0.0, 1.0 - (value - ceiling) / span)


def ambient_fitness(
    *,
    energy: float | None,
    bpm: float | None,
    acousticness: float | None,
    instrumentalness: float | None,
    speechiness: float | None,
) -> float:
    """How ambient-adjacent a track is, in [0, 1].

    Worked examples, which are also the test table:

    | track               | energy | bpm | acous | inst | speech | fitness |
    |---------------------|--------|-----|-------|------|--------|---------|
    | drone               | 0.15   |  60 | 0.90  | 0.98 | 0.02   | 0.97    |
    | quiet acoustic folk | 0.45   | 110 | 0.70  | 0.30 | 0.15   | 0.55    |
    | rock                | 0.85   | 140 | 0.05  | 0.05 | 0.20   | 0.13    |

    The middle row is the one that matters: "quiet acoustic folk" is the boundary case, and
    the weights are chosen so it lands near the floor rather than comfortably inside it.
    """
    e = NEUTRAL if energy is None else float(energy)
    b = bpm if bpm is not None else None
    a = NEUTRAL if acousticness is None else float(acousticness)
    i = NEUTRAL if instrumentalness is None else float(instrumentalness)
    s = NEUTRAL if speechiness is None else float(speechiness)

    w = FITNESS_WEIGHTS
    total = (
        w["energy"] * _ramp(e, AMBIENT_ENERGY_CEILING, AMBIENT_ENERGY_SPAN)
        + w["tempo"]
        * (NEUTRAL if b is None else _ramp(float(b), AMBIENT_BPM_CEILING, AMBIENT_BPM_SPAN))
        + w["acousticness"] * a
        + w["instrumentalness"] * i
        + w["speechiness"] * (1.0 - s)
    )
    return max(0.0, min(1.0, total))


def ambient_fitness_sql() -> ColumnElement[float]:
    """The same arithmetic over `TrackAnalysis` columns, for gating a query.

    Must agree with `ambient_fitness` row for row — `test_ambient_fitness.py` asserts it
    across the feature space including NULLs.

    **Not sargable.** No index can serve this expression, so callers should pair it with
    sargable conjuncts on the same columns to give the planner something to narrow with
    first. See `get_candidates`.
    """
    w = FITNESS_WEIGHTS

    def ramp(col: ColumnElement[float], ceiling: float, span: float) -> ColumnElement[float]:
        # greatest(0, least(1, 1 - (v - ceiling)/span)) — the ceiling arm is implied, since
        # v <= ceiling makes the inner expression >= 1 and `least` clamps it.
        return func.greatest(
            0.0,
            func.least(1.0, 1.0 - (cast(col, Float) - ceiling) / span),
        )

    energy = func.coalesce(cast(TrackAnalysis.energy, Float), NEUTRAL)
    acous = func.coalesce(cast(TrackAnalysis.acousticness, Float), NEUTRAL)
    inst = func.coalesce(cast(TrackAnalysis.instrumentalness, Float), NEUTRAL)
    speech = func.coalesce(cast(TrackAnalysis.speechiness, Float), NEUTRAL)

    tempo_term = func.coalesce(
        ramp(TrackAnalysis.bpm, AMBIENT_BPM_CEILING, AMBIENT_BPM_SPAN), NEUTRAL
    )

    return func.greatest(
        0.0,
        func.least(
            1.0,
            w["energy"] * ramp(energy, AMBIENT_ENERGY_CEILING, AMBIENT_ENERGY_SPAN)
            + w["tempo"] * tempo_term
            + w["acousticness"] * acous
            + w["instrumentalness"] * inst
            + w["speechiness"] * (1.0 - speech),
        ),
    )


def ambient_seed_conditions(*, min_duration: float = 60.0) -> list[ColumnElement[bool]]:
    """The gate three call sites each inlined separately.

    Values unchanged from `pick_surprise_seed` — this deduplicates, it does not retune. The
    0.7 energy limit is deliberately not the "obvious" 0.5: librosa's energy metric biases
    high for well-mastered full-band acoustic recordings, and known-calm piano pieces
    routinely score 0.6–0.8.

    `Track.active_filter()` is included because a MISSING track is a file no longer on disk
    that 404s on stream, and a bad *seed* is a session that cannot start at all (ADR-0106
    point 6).
    """
    return [
        Track.active_filter(),
        TrackAnalysis.instrumentalness >= 0.5,
        TrackAnalysis.speechiness <= 0.5,
        TrackAnalysis.energy <= 0.7,
        Track.duration_seconds >= min_duration,
        TrackAnalysis.energy.isnot(None),
    ]


__all__ = [
    "AMBIENT_BPM_CEILING",
    "AMBIENT_BPM_SPAN",
    "AMBIENT_ENERGY_CEILING",
    "AMBIENT_ENERGY_SPAN",
    "FITNESS_WEIGHTS",
    "ambient_fitness",
    "ambient_fitness_sql",
    "ambient_seed_conditions",
]
