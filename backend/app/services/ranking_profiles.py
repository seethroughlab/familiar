"""Named weight profiles for the shared ranking engine (ADR-0005).

`ambient.py` was already a working "what should play next" engine — HNSW candidate
retrieval plus a tuned scorer with a Camelot-style harmonic compatibility table. What made
it *ambient* rather than general was only its weighting and its preference for
instrumental content. Radio is that same engine with different numbers, so the weights
live here rather than being duplicated into a second recommender that would drift.

``AMBIENT`` reproduces the previous hard-coded behaviour **exactly**, including the
intensity overrides and every adjustment. That is a hard requirement, not an aspiration —
ambient mode is shipped, and `tests/test_ambient_scoring.py` characterised it before this
split landed so any drift fails a test.

``RADIO`` weights are a starting guess, as ADR-0005 says they must be: they cannot be
tuned until ADR-0004 listening events accumulate.
"""

from dataclasses import dataclass, field

# Weight keys used by `score_candidate`. Kept explicit so a typo in a profile is a
# KeyError at import rather than a silently-ignored term.
WEIGHT_KEYS = ("key", "energy", "embedding", "vocal", "brightness", "valence", "dr")


@dataclass(frozen=True)
class RankingProfile:
    """How one mode weighs a candidate transition.

    ``weights`` must cover exactly ``WEIGHT_KEYS`` and is expected to sum to 1.0 so the
    weighted terms stay in [0, 1] before adjustments.
    """

    name: str
    # Must cover exactly WEIGHT_KEYS. These plus `taste_weight` are a convex combination
    # summing to 1.0 — taste takes a share rather than being added on top of a full 1.0,
    # where it could only push an already-saturating score into the clamp and would
    # barely reorder anything.
    weights: dict[str, float]

    # Partial weight overrides applied on top of `weights`, keyed by listening intensity.
    intensity_overrides: dict[str, dict[str, float]] = field(default_factory=dict)

    # --- adjustments applied after the weighted sum ---
    bpm_penalty: float = 0.0
    bpm_threshold: float = 40.0
    quiet_energy_bonus: float = 0.0
    quiet_energy_threshold: float = 0.35
    minor_key_bonus: float = 0.0
    artist_cooldown_penalty: float = 0.0

    # --- ADR-0005 additions, inert for AMBIENT ---
    # How much a track's taste weight (play count / recency / favourites, via
    # `taste_weighting`) contributes. Normalised to [0, 1] by the caller.
    taste_weight: float = 0.0
    # Demotion per skip and per explicit rejection, from ADR-0004 `PlayEvent`. Rejection
    # is weighted more heavily: skipping is ambiguous (wrong moment, heard it recently),
    # rejecting is a stated judgement.
    skip_penalty: float = 0.0
    reject_penalty: float = 0.0
    max_negative_penalty: float = 0.0

    def weights_for(self, intensity: str) -> dict[str, float]:
        """Base weights with this intensity's overrides applied."""
        merged = dict(self.weights)
        merged.update(self.intensity_overrides.get(intensity, {}))
        return merged


AMBIENT = RankingProfile(
    name="ambient",
    # Key first: ambient transitions are judged mostly on harmonic compatibility.
    weights={
        "key": 0.30,
        "energy": 0.20,
        "embedding": 0.15,
        "vocal": 0.10,
        "brightness": 0.10,
        "valence": 0.10,
        "dr": 0.05,
    },
    intensity_overrides={
        "quiet": {"energy": 0.30, "key": 0.20},
        "immersive": {"embedding": 0.25, "key": 0.20},
    },
    bpm_penalty=0.15,
    quiet_energy_bonus=0.10,
    minor_key_bonus=0.02,
    artist_cooldown_penalty=0.25,
)


RADIO = RankingProfile(
    name="radio",
    # Embedding first: radio is "more of this", which is a similarity question before it
    # is a mixing question. `vocal` drops to zero — the term exists to keep ambient
    # instrumental, and penalising vocals in radio would exclude most of a music library.
    # Its 0.10 plus most of key's 0.30 go to embedding and taste.
    weights={
        "key": 0.10,
        "energy": 0.15,
        "embedding": 0.35,
        "vocal": 0.0,
        "brightness": 0.05,
        "valence": 0.10,
        "dr": 0.05,
        # Not in WEIGHT_KEYS: taste is scored separately, see `taste_weight`.
    },
    # Intensity is an ambient concept (the user picks it there). Radio has no equivalent
    # control, so no overrides — `weights_for` returns the base weights for any value.
    bpm_penalty=0.10,
    artist_cooldown_penalty=0.25,
    taste_weight=0.20,
    skip_penalty=0.08,
    reject_penalty=0.25,
    max_negative_penalty=0.40,
)


PROFILES: dict[str, RankingProfile] = {
    AMBIENT.name: AMBIENT,
    RADIO.name: RADIO,
}


def get_profile(name: str | None) -> RankingProfile:
    """Look up a profile by name, defaulting to AMBIENT.

    Defaults rather than raising so existing ambient callers that pass nothing keep
    working unchanged.
    """
    if not name:
        return AMBIENT
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(
            f"Unknown ranking profile {name!r}. Known: {sorted(PROFILES)}"
        ) from None


def _validate() -> None:
    """Fail at import if a profile is malformed, rather than scoring silently wrong."""
    for profile in PROFILES.values():
        missing = set(WEIGHT_KEYS) - set(profile.weights)
        if missing:
            raise ValueError(f"{profile.name}: missing weights {sorted(missing)}")
        total = sum(profile.weights[k] for k in WEIGHT_KEYS) + profile.taste_weight
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"{profile.name}: feature weights + taste_weight must sum to 1.0, got {total}"
            )
        for intensity, overrides in profile.intensity_overrides.items():
            unknown = set(overrides) - set(WEIGHT_KEYS)
            if unknown:
                raise ValueError(
                    f"{profile.name}/{intensity}: unknown weight keys {sorted(unknown)}"
                )


_validate()
