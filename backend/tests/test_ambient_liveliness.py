"""The chain has to stay ambient, not merely stay similar.

**Every energy term in `score_candidate` was relative.** Energy is scored as proximity to the
current track — `1.0 - abs(current.energy - candidate.energy)` — so each step resembles the last
and nothing resists a slow climb. A session seeded on something quiet random-walks its way into
whatever the library holds, which for ambient means it stops being ambient after a few windows.
`quiet_energy_bonus` was the only absolute pull and it is gated on `intensity == "quiet"`, so at the
default intensity there was none at all.

Found by listening: "ambient mode is choosing some non-ambient tracks that aren't really appropriate
for something you're supposed to fall asleep to."

The existing characterisation suite did not catch the change these tests describe, which is worth
knowing about it: `test_ambient_scoring.py` pins *ordering*, not scores, so a new absolute term
passes it untouched. ADR-0106 point 8 reads as though that suite makes `AMBIENT` unchangeable. It
does not — it makes it un-reorderable for the cases it names.
"""

from uuid import uuid4

from app.services.ambient import AmbientDescriptor, score_candidate
from app.services.ranking_profiles import AMBIENT, RADIO


def descriptor(**overrides) -> AmbientDescriptor:
    base = {
        "track_id": uuid4(),
        "title": "Test Track",
        "artist": "Test Artist",
        "album": "Test Album",
        "duration_seconds": 200.0,
        "key": "C",
        "bpm": 120.0,
        "energy": 0.3,
        "brightness": 0.3,
        "valence": 0.5,
        "instrumentalness": 0.8,
        "speechiness": 0.1,
        "dynamic_range_db": 10.0,
        "energy_shape": None,
        "section_count": None,
        "modal_character": None,
        "acousticness": 0.5,
    }
    base.update(overrides)
    return AmbientDescriptor(**base)


def test_a_loud_candidate_scores_below_a_calm_one_from_the_same_seed():
    """The whole point: this must hold at the *default* intensity, not only at `quiet`."""
    seed = descriptor(energy=0.3, brightness=0.3)
    calm = descriptor(energy=0.3, brightness=0.3)
    loud = descriptor(energy=0.9, brightness=0.9)

    assert score_candidate(seed, calm) > score_candidate(seed, loud)


def test_a_loud_candidate_is_penalised_even_when_the_current_track_is_loud():
    """**The drift test.** Proximity alone rewards a loud candidate once the chain has already
    climbed — each step looks like the last, and nothing pulls back down.

    Here the current track is already past the ceiling, so a proximity-only scorer would prefer the
    equally loud candidate. The absolute term must prefer the calm one instead.
    """
    drifted = descriptor(energy=0.9, brightness=0.9)
    stay_loud = descriptor(energy=0.9, brightness=0.9)
    come_back = descriptor(energy=0.3, brightness=0.3)

    assert score_candidate(drifted, come_back) > score_candidate(drifted, stay_loud)


def test_brightness_counts_as_well_as_energy():
    """A quiet but very bright track — a cymbal-heavy recording, a thin live mix — is as wrong for
    this as a loud one, and `energy` alone does not catch it."""
    seed = descriptor(energy=0.3, brightness=0.3)
    dull = descriptor(energy=0.3, brightness=0.3)
    piercing = descriptor(energy=0.3, brightness=0.95)

    assert score_candidate(seed, dull) > score_candidate(seed, piercing)


def test_the_penalty_scales_with_how_far_past_the_ceiling_a_track_is():
    """A nudge for something just over, a shove for something far over — so the library does not
    collapse to a hard yes/no at the ceiling."""
    seed = descriptor()
    just_over = descriptor(energy=AMBIENT.liveliness_ceiling + 0.05)
    far_over = descriptor(energy=1.0)

    assert score_candidate(seed, just_over) > score_candidate(seed, far_over)


def test_a_track_under_the_ceiling_is_not_penalised_at_all():
    """It is a ceiling, not a preference for silence: two calm tracks either side of nothing should
    be separated by the other terms, not by this one."""
    seed = descriptor(energy=0.3)
    a = descriptor(energy=0.30)
    b = descriptor(energy=0.45)

    # Both are under the ceiling, so only proximity to the seed separates them.
    assert score_candidate(seed, a) > score_candidate(seed, b)
    # And neither is dragged below what an unpenalised score looks like.
    assert score_candidate(seed, b) > score_candidate(seed, descriptor(energy=0.95))


def test_radio_is_untouched():
    """**Radio must not inherit this.** It ranks for "what would this listener enjoy next", where a
    loud track is a perfectly good answer — the whole reason ADR-0005 made the weights a profile
    rather than a constant.
    """
    assert RADIO.liveliness_penalty == 0

    # Comparing raw scores *across* profiles means nothing — they weigh different things, and the
    # first version of this test did exactly that and failed for a reason unrelated to the feature.
    # The meaningful contrast is which candidate each profile prefers from the same loud seed.
    loud_seed = descriptor(energy=0.95, brightness=0.95)
    stay_loud = descriptor(energy=0.95, brightness=0.95)
    go_calm = descriptor(energy=0.3, brightness=0.3)

    assert score_candidate(loud_seed, stay_loud, profile=RADIO) > score_candidate(
        loud_seed, go_calm, profile=RADIO
    ), "radio should follow the listener's energy, not drag them somewhere quiet"

    assert score_candidate(loud_seed, go_calm, profile=AMBIENT) > score_candidate(
        loud_seed, stay_loud, profile=AMBIENT
    ), "ambient should pull back toward calm from the same seed"


def test_the_ceiling_sits_above_the_soft_filters_limit():
    """A pull, not a gate. `soft` caps energy at 0.5 and is where a hard limit belongs; this only
    has to stop the chain climbing, so it sits just above that and leaves the presets meaningful."""
    assert AMBIENT.liveliness_ceiling > 0.5
    assert 0 < AMBIENT.liveliness_penalty < 1
