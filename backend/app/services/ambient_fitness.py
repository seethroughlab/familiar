"""How ambient-adjacent a track is, relative to the library it is in.

One definition in two forms — Python for scoring rows already in memory, SQL for gating a
query before the rows exist. `test_ambient_fitness.py` asserts they agree, because the
realistic failure here is a NULL-handling or precedence divergence that nothing else would
notice until a pool came back the wrong shape.

**Features only.** No genre tags: `Track.genre` is free text from file metadata with no
controlled vocabulary. No CLAP text embedding: that would make every candidate query depend on
an inference-time text encode and on ADR-0105's external runtime.

## Why this is relative and not absolute

The first version used fixed thresholds — "energy at or below 0.30 is ambient" — and measuring
the real library showed that cannot work:

    energy       p5 0.648   p10 0.700   p50 0.826   p80 0.878
    bpm          p5 92      p10 96      p50 123
    acousticness p50 0.491  p90 0.578   p95 0.598

**The quietest five percent of a 26,000-track library sits at energy 0.648.** A ramp reaching
zero at 0.60 scores the entire library zero on its heaviest term, and acousticness spans only
0.49 to 0.60 between its median and 95th percentile. librosa's features on real music occupy a
narrow band nowhere near the 0–1 range absolute constants assume, and the band moves with the
library — a collection of solo piano and one of metal do not share a scale.

So a track is scored by **where it sits in its own library's distribution**. The quietest
tenth gets full credit whatever "quietest" happens to mean there; the middle gets almost none.
Self-calibrating, and the discrimination is uniform by construction rather than by hoping the
constants land somewhere useful.

`instrumentalness` and `speechiness` are deliberately **not** scored: their medians are 1.00
and 0.00, so they are near-constant and would contribute weight without signal. They remain
hard gates in `ambient_seed_conditions`, which is the shape they actually have.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Float, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Track, TrackAnalysis

#: Only the three features that carry signal. Sums to 1.0, so fitness reads as a fraction.
FITNESS_WEIGHTS = {"energy": 0.45, "tempo": 0.25, "acousticness": 0.30}

#: A missing feature reads as neutral, **not** as zero.
#:
#: `ambient._safe_float` returns 0.0 for NULL — maximally unambient — which would silently
#: exile every track whose analyser never wrote `acousticness`. 740 of this library's rows have
#: no analysis at all.
NEUTRAL = 0.5

#: The quantiles that define "the quiet end". Full credit at or beyond `_FULL`, none at
#: `_ZERO`, linear between. The gap is wide on purpose: a cliff at one quantile would make
#: fitness a near-binary gate, and the pool wants an ordering.
FULL_QUANTILE = 0.10
ZERO_QUANTILE = 0.60


@dataclass(frozen=True)
class AmbientCalibration:
    """Where this particular library's quiet end is.

    Measured once and reused. Every field is the feature value at a quantile, so the same code
    behaves the same way on a 500-track piano collection and a 26,000-track one that is mostly
    rock — which is the whole point of not hard-coding thresholds.
    """

    energy_full: float
    energy_zero: float
    bpm_full: float
    bpm_zero: float
    #: Direction is flipped: *more* acoustic is more ambient, so `full` is the higher value.
    acoustic_full: float
    acoustic_zero: float

    @property
    def is_degenerate(self) -> bool:
        """True when a feature has no spread — every track scores the same on it."""
        return (
            self.energy_full >= self.energy_zero
            or self.bpm_full >= self.bpm_zero
            or self.acoustic_full <= self.acoustic_zero
        )


#: Measured from a 26,000-track library, and used when the real distribution is unavailable —
#: an empty database, a unit test, or the first request before the measurement is cached.
#: Better than absolute guesses, and still replaced by the real thing wherever there is one.
DEFAULT_CALIBRATION = AmbientCalibration(
    energy_full=0.70,
    energy_zero=0.85,
    bpm_full=96.0,
    bpm_zero=130.0,
    acoustic_full=0.58,
    acoustic_zero=0.47,
)


def _ramp(value: float, full: float, zero: float) -> float:
    """1.0 at or beyond `full`, 0.0 at or beyond `zero`, linear between.

    Works in either direction, so the acousticness term — where higher is better — uses the
    same function rather than a mirrored copy.
    """
    if full == zero:
        return NEUTRAL
    t = (value - zero) / (full - zero)
    return max(0.0, min(1.0, t))


def ambient_fitness(
    *,
    energy: float | None,
    bpm: float | None,
    acousticness: float | None,
    calibration: AmbientCalibration = DEFAULT_CALIBRATION,
) -> float:
    """How ambient-adjacent a track is *for its library*, in [0, 1].

    A track at the quiet, slow, acoustic end of its own collection scores near 1 whatever the
    absolute numbers are; one at the loud, fast, electronic end scores near 0.
    """
    w = FITNESS_WEIGHTS
    energy_term = (
        NEUTRAL
        if energy is None
        else _ramp(float(energy), calibration.energy_full, calibration.energy_zero)
    )
    tempo_term = (
        NEUTRAL if bpm is None else _ramp(float(bpm), calibration.bpm_full, calibration.bpm_zero)
    )
    acoustic_term = (
        NEUTRAL
        if acousticness is None
        else _ramp(float(acousticness), calibration.acoustic_full, calibration.acoustic_zero)
    )
    return max(
        0.0,
        min(
            1.0,
            w["energy"] * energy_term + w["tempo"] * tempo_term + w["acousticness"] * acoustic_term,
        ),
    )


def ambient_fitness_sql(
    calibration: AmbientCalibration = DEFAULT_CALIBRATION,
) -> ColumnElement[float]:
    """The same arithmetic over `TrackAnalysis` columns, for gating a query.

    The calibration arrives as literals at query-build time, so this stays a plain arithmetic
    expression — no window function, no self-join, nothing that would make the planner give up
    on the indexes.

    **Not sargable.** No index serves this expression, so callers should pair it with sargable
    conjuncts on the same columns to give the planner something to narrow with first.
    """
    w = FITNESS_WEIGHTS

    def ramp(col: Any, full: float, zero: float) -> ColumnElement[float]:
        if full == zero:
            return literal(NEUTRAL)
        return func.greatest(0.0, func.least(1.0, (cast(col, Float) - zero) / (full - zero)))

    energy_term = func.coalesce(
        ramp(TrackAnalysis.energy, calibration.energy_full, calibration.energy_zero), NEUTRAL
    )
    tempo_term = func.coalesce(
        ramp(TrackAnalysis.bpm, calibration.bpm_full, calibration.bpm_zero), NEUTRAL
    )
    acoustic_term = func.coalesce(
        ramp(TrackAnalysis.acousticness, calibration.acoustic_full, calibration.acoustic_zero),
        NEUTRAL,
    )

    return func.greatest(
        0.0,
        func.least(
            1.0,
            w["energy"] * energy_term + w["tempo"] * tempo_term + w["acousticness"] * acoustic_term,
        ),
    )


async def measure_calibration(db: AsyncSession) -> AmbientCalibration:
    """Read where this library's quiet end actually is.

    One aggregate pass. The caller is expected to cache it — the distribution moves only as
    the library is analysed, and a stale calibration degrades the ordering slightly rather
    than breaking it.

    Falls back to `DEFAULT_CALIBRATION` when a feature has no spread, which is the case for a
    library too small or too uniform to rank: `is_degenerate` would otherwise make every ramp
    return neutral and the pool would stop distinguishing anything.
    """

    def q(column, quantile: float):
        return func.percentile_cont(quantile).within_group(column.asc())

    row = (
        await db.execute(
            select(
                q(TrackAnalysis.energy, FULL_QUANTILE),
                q(TrackAnalysis.energy, ZERO_QUANTILE),
                q(TrackAnalysis.bpm, FULL_QUANTILE),
                q(TrackAnalysis.bpm, ZERO_QUANTILE),
                # Flipped: the acoustic end is the *high* end.
                q(TrackAnalysis.acousticness, 1 - FULL_QUANTILE),
                q(TrackAnalysis.acousticness, 1 - ZERO_QUANTILE),
            )
            .select_from(TrackAnalysis)
            .join(Track, Track.id == TrackAnalysis.track_id)
            .where(Track.active_filter(), TrackAnalysis.energy.isnot(None))
        )
    ).first()

    if row is None or any(v is None for v in row):
        return DEFAULT_CALIBRATION

    measured = AmbientCalibration(
        energy_full=float(row[0]),
        energy_zero=float(row[1]),
        bpm_full=float(row[2]),
        bpm_zero=float(row[3]),
        acoustic_full=float(row[4]),
        acoustic_zero=float(row[5]),
    )
    return DEFAULT_CALIBRATION if measured.is_degenerate else measured


#: How much of the seed score each feature carries. Unchanged from `pick_surprise_seed`.
SEED_WEIGHTS = {"instrumentalness": 0.4, "speechiness": 0.3, "energy": 0.3}

#: The energy a seed is scored against, and the slope away from it. `pick_surprise_seed` used
#: these exact numbers; they are preserved rather than retuned.
SEED_ENERGY_TARGET = 0.25
SEED_ENERGY_SLOPE = 3.33


def seed_fitness(
    *,
    energy: float | None,
    instrumentalness: float | None,
    speechiness: float | None,
) -> float:
    """Which of an already-gated set is the *most* ambient — a different question.

    `ambient_fitness` answers "is this ambient enough to be in the pool", and its energy term
    is a **ceiling**: everything past the quiet end scores the same, which is right for
    admission and useless for ranking. The seed paths gate on `energy <= 0.7` first and then
    choose among what is left, where every candidate is already past that ceiling — so scoring
    them with `ambient_fitness` would make them all tie and the seed would be arbitrary.

    Proximity to a target is right *here* for the reason it was wrong there: within a gated
    set the quietest track is the best seed, and `pick_surprise_seed`'s docstring promises
    exactly that.

    **The bug this fixes was never the shape, it was having two of them.**
    `pick_surprise_seed` targeted 0.25 with a 3.33 slope; `find_seed_by_artist` targeted 0.4
    with no slope, so for one artist with tracks at energy 0.20 and 0.45:

        surprise:  0.20 -> 0.880   0.45 -> 0.730   picks 0.20
        artist:    0.20 -> 0.870   0.45 -> 0.915   picks 0.45

    Two accidentally different answers to one question. This is that question, answered once.
    """
    w = SEED_WEIGHTS
    inst = 0.0 if instrumentalness is None else float(instrumentalness)
    speech = 0.0 if speechiness is None else float(speechiness)
    e = 0.0 if energy is None else float(energy)
    energy_term = max(0.0, 1.0 - abs(e - SEED_ENERGY_TARGET) * SEED_ENERGY_SLOPE)
    return (
        w["instrumentalness"] * inst + w["speechiness"] * (1.0 - speech) + w["energy"] * energy_term
    )


def ambient_seed_conditions(*, min_duration: float = 60.0) -> list[ColumnElement[bool]]:
    """The gate three call sites each inlined separately.

    Values unchanged from `pick_surprise_seed` — this deduplicates, it does not retune. The 0.7
    energy limit is deliberately not the "obvious" 0.5: librosa's energy metric biases high for
    well-mastered full-band acoustic recordings, and the measurement above bears that out — the
    library's *median* energy is 0.83.

    `instrumentalness` and `speechiness` live here rather than in the score because their
    medians are 1.00 and 0.00: they separate almost nothing continuously, and everything as a
    gate.

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
    "DEFAULT_CALIBRATION",
    "FITNESS_WEIGHTS",
    "AmbientCalibration",
    "ambient_fitness",
    "ambient_fitness_sql",
    "ambient_seed_conditions",
    "seed_fitness",
    "measure_calibration",
]
