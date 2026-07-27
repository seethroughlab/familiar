"""Taste weighting shared by weighted shuffle and the radio ranking engine.

Extracted verbatim from ``app/api/routes/tracks/listing.py`` so a service can use it
without importing from a route module, which would invert the dependency (ADR-0005
decision point 3). The logic is unchanged; only its location moved.

Note that ``compute_track_weight`` returns an **unbounded multiplier**, not a 0-1 score.
It starts at 1.0 and each of three axes multiplies by up to 4x, plus a favourites boost
of up to 3x. Anything combining it with a normalised score must scale it first.
"""

from dataclasses import dataclass
from typing import Any

VALID_SHUFFLE_PRESETS = {"rediscover", "fresh_finds", "comfort_zone", "deep_dive"}


@dataclass
class ShufflePresetWeights:
    """Weight configuration for a shuffle preset."""
    play_count_dir: float  # +1 = favor high play count, -1 = favor low
    recency_dir: float     # +1 = favor recent, -1 = favor old
    newness_dir: float     # +1 = favor recently added, -1 = favor old additions
    favorites_boost: float # multiplier for favorited tracks (1.0 = no boost)
    variety_strength: float  # 0-1 for artist spacing post-process


SHUFFLE_PRESETS: dict[str, ShufflePresetWeights] = {
    "rediscover": ShufflePresetWeights(
        play_count_dir=1.0, recency_dir=-1.0, newness_dir=0.0,
        favorites_boost=1.0, variety_strength=0.5,
    ),
    "fresh_finds": ShufflePresetWeights(
        play_count_dir=-1.0, recency_dir=0.0, newness_dir=1.0,
        favorites_boost=1.0, variety_strength=0.7,
    ),
    "comfort_zone": ShufflePresetWeights(
        play_count_dir=1.0, recency_dir=0.5, newness_dir=0.0,
        favorites_boost=3.0, variety_strength=0.2,
    ),
    "deep_dive": ShufflePresetWeights(
        play_count_dir=-1.0, recency_dir=-1.0, newness_dir=0.0,
        favorites_boost=1.0, variety_strength=0.8,
    ),
}


def compute_track_weight(
    play_count: int | None,
    last_played_at: Any,
    created_at: Any,
    is_favorited: bool,
    preset: ShufflePresetWeights,
    now: Any,
    max_play_count: int,
) -> float:
    """Compute weight for a single track based on preset parameters."""
    weight = 1.0

    pc = play_count or 0
    # Play count influence
    if preset.play_count_dir != 0 and max_play_count > 0:
        normalized = pc / max_play_count  # 0..1
        if preset.play_count_dir > 0:
            # Favor high play count
            weight *= 1.0 + abs(preset.play_count_dir) * normalized * 3.0
        else:
            # Favor low play count (unplayed gets max boost)
            weight *= 1.0 + abs(preset.play_count_dir) * (1.0 - normalized) * 3.0

    # Recency influence (last_played_at)
    if preset.recency_dir != 0 and last_played_at is not None:
        days_ago = max((now - last_played_at).total_seconds() / 86400, 0.1)
        if preset.recency_dir < 0:
            # Favor tracks NOT played recently
            recency_score = min(days_ago / 180.0, 1.0)  # Cap at 6 months
            weight *= 1.0 + abs(preset.recency_dir) * recency_score * 3.0
        else:
            # Favor recently played
            recency_score = max(1.0 - days_ago / 30.0, 0.0)  # Recent = within 30 days
            weight *= 1.0 + preset.recency_dir * recency_score * 3.0
    elif preset.recency_dir < 0 and last_played_at is None:
        # Never played = maximally "not recent"
        weight *= 1.0 + abs(preset.recency_dir) * 3.0

    # Library newness (created_at)
    if preset.newness_dir != 0 and created_at is not None:
        days_in_lib = max((now - created_at).total_seconds() / 86400, 0.1)
        if preset.newness_dir > 0:
            newness_score = max(1.0 - days_in_lib / 90.0, 0.0)  # "New" = within 90 days
            weight *= 1.0 + preset.newness_dir * newness_score * 3.0
        else:
            oldness_score = min(days_in_lib / 365.0, 1.0)
            weight *= 1.0 + abs(preset.newness_dir) * oldness_score * 3.0

    # Favorites boost
    if is_favorited and preset.favorites_boost > 1.0:
        weight *= preset.favorites_boost

    return max(weight, 0.01)  # Floor to avoid zero weights


def apply_artist_variety(track_ids_with_artists: list[tuple[str, str | None]], strength: float) -> list[str]:
    """Post-process track IDs to space out same-artist tracks.

    Uses a greedy algorithm: scan forward and swap tracks to avoid
    back-to-back same-artist sequences. Strength controls how aggressively
    we enforce spacing (0 = no change, 1 = maximum spacing).
    """
    if strength <= 0 or len(track_ids_with_artists) <= 2:
        return [tid for tid, _ in track_ids_with_artists]

    result = list(track_ids_with_artists)
    min_gap = max(1, int(strength * 5))  # At strength=1, require 5 tracks between same artist

    for i in range(1, len(result)):
        current_artist = result[i][1]
        if not current_artist:
            continue

        # Check if any of the previous min_gap tracks share the artist
        conflict = False
        for j in range(max(0, i - min_gap), i):
            if result[j][1] == current_artist:
                conflict = True
                break

        if conflict:
            # Try to find a non-conflicting track to swap with
            best_swap = None
            for k in range(i + 1, min(i + 20, len(result))):  # Look ahead up to 20 tracks
                swap_artist = result[k][1]
                swap_ok = True
                for j in range(max(0, i - min_gap), i):
                    if result[j][1] == swap_artist:
                        swap_ok = False
                        break
                if swap_ok:
                    best_swap = k
                    break

            if best_swap is not None:
                result[i], result[best_swap] = result[best_swap], result[i]

    return [tid for tid, _ in result]
