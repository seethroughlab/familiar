"""Score a visualizer's declared affinity against one track's analysis (ADR-0064).

A visualizer declares, in its `familiar-plugin.json`, the tags it suits and ranges over the
numeric analysis columns. This module decides how well one such declaration fits one track.

**Pure by design.** Everything arrives as plain values — a features dict, a mood-tag list, the
candidates' declarations — and nothing here touches the database or the ORM. That is the same rule
`ambient.score_candidate` states for itself ("taste and listening history arrive as numbers rather
than being queried here"), and it is what lets the whole scorer be tested without a database.

**Unrecognised means inert, never rejected** (ADR-0064 point 3). A tag outside the 48-descriptor
vocabulary, a range over a column that does not exist, a range over one of the seven columns that
holds a string, and a range over a feature this particular track was never analysed for all
contribute nothing *and are excluded from the denominator* — they neither help nor harm. They are
reported back so the picker can show an author what did not land, rather than being dropped
silently. Refusing a working visualizer over a typo in an optional field would be the worst trade
available here.

**Nothing to judge scores neutral, not zero.** A visualizer that declares no affinity, and a track
with no mood tags, both land on `NEUTRAL`. Zero would mean "definitely wrong for this track", which
is a much stronger claim than "nobody said". `ambient.py` uses the same 0.5 for an unparseable key.
"""

from dataclasses import dataclass, field

import sqlalchemy as sa

from app.db.models.tracks import ANALYSIS_FEATURE_COLUMNS, TrackAnalysis
from app.services.mood_tags import KNOWN_TAGS

# What an unjudgeable term scores. See the module docstring.
NEUTRAL = 0.5

# Weight keys, explicit so a typo is a KeyError at import rather than a silently dropped term —
# the convention `ranking_profiles.WEIGHT_KEYS` establishes.
WEIGHT_KEYS = ("tags", "ranges")

# A starting guess, as ADR-0064 says the weights must be: tags carry more because they describe
# what a track *is* and are what an author reaches for first, while ranges are a refinement.
# There is no listening data to tune against — that is the ADR's own follow-up.
WEIGHTS: dict[str, float] = {
    "tags": 0.6,
    "ranges": 0.4,
}


def _numeric_feature_columns() -> frozenset[str]:
    """The analysis columns a numeric range can meaningfully be declared over.

    Derived from the mapped column types rather than listed by hand, so a column added to
    `ANALYSIS_FEATURE_COLUMNS` later is classified correctly without anyone remembering to edit a
    second list here. Seven of the twenty-eight hold strings (`key`, `key_stability`,
    `modal_character`, `tempo_character`, `energy_shape`, `form_string`, `interval_character`) and
    a range over one of those is inert.
    """
    table = TrackAnalysis.__table__
    numeric = set()
    for name in ANALYSIS_FEATURE_COLUMNS:
        column = table.columns.get(name)
        if column is not None and isinstance(column.type, (sa.Float, sa.Integer, sa.Numeric)):
            numeric.add(name)
    return frozenset(numeric)


NUMERIC_FEATURE_COLUMNS: frozenset[str] = _numeric_feature_columns()


@dataclass(frozen=True)
class FeatureRange:
    """One declared bound on a numeric analysis column. Either end may be open."""

    feature: str
    minimum: float | None = None
    maximum: float | None = None

    def contains(self, value: float) -> bool:
        if self.minimum is not None and value < self.minimum:
            return False
        if self.maximum is not None and value > self.maximum:
            return False
        return True

    @property
    def is_bounded(self) -> bool:
        """A range with neither end set constrains nothing and is treated as unrecognised."""
        return self.minimum is not None or self.maximum is not None


@dataclass(frozen=True)
class Affinity:
    """What a visualizer says it suits. Every field optional — the whole block is optional."""

    tags: tuple[str, ...] = ()
    ranges: tuple[FeatureRange, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.tags and not self.ranges


@dataclass(frozen=True)
class Candidate:
    """One visualizer offered for ranking, as the client reports having it loaded."""

    id: str
    affinity: Affinity = field(default_factory=Affinity)


@dataclass(frozen=True)
class ScoredCandidate:
    """One visualizer's score, with enough detail to explain the ordering.

    `ignored` is the ADR-0064 point 3 report: declarations this server did not understand. It is
    per-candidate rather than global because it belongs to the visualizer that made them.
    """

    id: str
    score: float
    matched_tags: tuple[str, ...] = ()
    matched_ranges: tuple[str, ...] = ()
    unmatched_ranges: tuple[str, ...] = ()
    ignored: tuple[str, ...] = ()


def _tag_term(
    declared: tuple[str, ...],
    track_tags: list[dict],
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    """How much of this track's character the visualizer claims.

    Scored as the share of the track's total tag confidence that the visualizer declared, so a
    visualizer naming the track's strongest tags scores near 1 and one naming only a weak tag
    scores low. Counting matched tags instead would rate "matched one incidental tag" the same as
    "matched the defining one".
    """
    ignored = tuple(t for t in declared if t not in KNOWN_TAGS)
    recognised = {t for t in declared if t in KNOWN_TAGS}

    usable = [
        t for t in track_tags
        if isinstance(t, dict) and isinstance(t.get("tag"), str)
    ]
    total = sum(float(t.get("confidence") or 0.0) for t in usable)

    # Nothing declared that we understand, or a track nothing was tagged on: no opinion.
    if not recognised or total <= 0.0:
        return NEUTRAL, (), ignored

    matched = tuple(t["tag"] for t in usable if t["tag"] in recognised)
    claimed = sum(
        float(t.get("confidence") or 0.0) for t in usable if t["tag"] in recognised
    )
    return min(1.0, claimed / total), matched, ignored


def _range_term(
    declared: tuple[FeatureRange, ...],
    features: dict,
) -> tuple[float, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """The share of judgeable declared ranges this track falls inside.

    A range is judgeable only when the column exists, is numeric, the range actually bounds
    something, and this track has a value for it. `to_features_dict()` omits nulls entirely, so a
    missing key means "not analysed for that feature" — which must be inert rather than a miss,
    or a partly-analysed track would rank every declaring visualizer down.
    """
    ignored: list[str] = []
    inside: list[str] = []
    outside: list[str] = []

    for declared_range in declared:
        if declared_range.feature not in NUMERIC_FEATURE_COLUMNS or not declared_range.is_bounded:
            ignored.append(declared_range.feature)
            continue

        value = features.get(declared_range.feature)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            # Present-but-unusable and absent are the same thing here: nothing to judge.
            continue

        (inside if declared_range.contains(float(value)) else outside).append(
            declared_range.feature
        )

    judged = len(inside) + len(outside)
    if judged == 0:
        return NEUTRAL, (), (), tuple(ignored)
    return len(inside) / judged, tuple(inside), tuple(outside), tuple(ignored)


def score_candidate(
    candidate: Candidate,
    features: dict,
    track_tags: list[dict],
) -> ScoredCandidate:
    """Score one visualizer against one track. Always in [0, 1]."""
    if candidate.affinity.is_empty:
        # Declared nothing. Neutral rather than last, so a visualizer that has not been described
        # is not effectively removed from a library — ADR-0064 point 4's concern, from the other end.
        return ScoredCandidate(id=candidate.id, score=NEUTRAL)

    tag_score, matched_tags, ignored_tags = _tag_term(candidate.affinity.tags, track_tags)
    range_score, inside, outside, ignored_ranges = _range_term(
        candidate.affinity.ranges, features
    )

    total = WEIGHTS["tags"] * tag_score + WEIGHTS["ranges"] * range_score

    return ScoredCandidate(
        id=candidate.id,
        score=max(0.0, min(1.0, total)),
        matched_tags=matched_tags,
        matched_ranges=inside,
        unmatched_ranges=outside,
        ignored=ignored_tags + ignored_ranges,
    )


def rank_candidates(
    candidates: list[Candidate],
    features: dict,
    track_tags: list[dict],
) -> list[ScoredCandidate]:
    """Score every candidate, best first.

    Ties break on the order the client submitted, because that is the order it would have used
    anyway and a stable result is worth more than an arbitrary one — a visualizer that flickered
    between two equal matches on every track would read as a bug.
    """
    scored = [score_candidate(c, features, track_tags) for c in candidates]
    return sorted(
        scored,
        key=lambda s: (-s.score, [c.id for c in candidates].index(s.id)),
    )


def _validate() -> None:
    """Fail at import if the weights are malformed, rather than scoring silently wrong."""
    missing = set(WEIGHT_KEYS) - set(WEIGHTS)
    if missing:
        raise ValueError(f"visualizer affinity: missing weights {sorted(missing)}")
    unknown = set(WEIGHTS) - set(WEIGHT_KEYS)
    if unknown:
        raise ValueError(f"visualizer affinity: unknown weight keys {sorted(unknown)}")
    total = sum(WEIGHTS[k] for k in WEIGHT_KEYS)
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"visualizer affinity: weights must sum to 1.0, got {total}")
    if not NUMERIC_FEATURE_COLUMNS:
        # Would mean the model changed shape underneath this and every range became inert —
        # a silent "nothing matches anything", which is exactly the failure worth failing loudly.
        raise ValueError("visualizer affinity: no numeric analysis columns found")


_validate()
