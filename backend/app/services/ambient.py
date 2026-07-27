"""Ambient mode scoring service.

Pure scoring logic for ambient playback — key compatibility, feature-based
candidate ranking, filter presets, seed selection, and snippet window hints.
No session persistence; all state lives on the client.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Track, TrackAnalysis
from app.logging_config import get_logger
from app.services.ranking_profiles import AMBIENT, RankingProfile

logger = get_logger(__name__)

# ============================================================================
# Key compatibility
# ============================================================================

# Camelot-style key map: (pitch_class, mode) → int wheel position
# pitch_class: 0=C, 1=C#, 2=D, ..., 11=B
# mode: 'major' or 'minor'

_KEY_ALIASES: dict[str, tuple[int, str]] = {}

_NOTE_NAMES = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "Fb": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7,
    "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11, "Cb": 11,
}


def _build_key_aliases() -> None:
    """Build lookup table for all common key notations."""
    for note, pc in _NOTE_NAMES.items():
        # "Am", "A minor", "A min"
        for suffix in ("m", " minor", " min"):
            _KEY_ALIASES[f"{note}{suffix}"] = (pc, "minor")
        # "A", "A major", "A maj"
        _KEY_ALIASES[note] = (pc, "major")
        for suffix in (" major", " maj"):
            _KEY_ALIASES[f"{note}{suffix}"] = (pc, "major")


_build_key_aliases()


def parse_key(key_str: str | None) -> tuple[int, str] | None:
    """Parse a key string like 'Am', 'C# minor', 'Eb' into (pitch_class, mode)."""
    if not key_str:
        return None
    key_str = key_str.strip()
    result = _KEY_ALIASES.get(key_str)
    if result:
        return result
    # Try case-insensitive
    for alias, val in _KEY_ALIASES.items():
        if alias.lower() == key_str.lower():
            return val
    return None


def key_compatibility(key_a: str | None, key_b: str | None) -> float:
    """Score key compatibility between two tracks (0.0–1.0)."""
    parsed_a = parse_key(key_a)
    parsed_b = parse_key(key_b)

    if parsed_a is None or parsed_b is None:
        return 0.5  # Unknown keys → neutral

    pc_a, mode_a = parsed_a
    pc_b, mode_b = parsed_b

    # Same key
    if pc_a == pc_b and mode_a == mode_b:
        return 1.0

    # Relative major/minor (e.g., Am ↔ C)
    if mode_a == "minor" and mode_b == "major" and (pc_a + 3) % 12 == pc_b:
        return 0.9
    if mode_a == "major" and mode_b == "minor" and (pc_b + 3) % 12 == pc_a:
        return 0.9

    # Perfect fifth (same mode)
    interval = (pc_b - pc_a) % 12
    if mode_a == mode_b and interval in (5, 7):
        return 0.8

    # Parallel major/minor (same root)
    if pc_a == pc_b and mode_a != mode_b:
        return 0.7

    # Second neighbor (two steps on circle of fifths, same mode)
    if mode_a == mode_b and interval in (2, 10):
        return 0.5

    return 0.2


# ============================================================================
# Candidate scoring
# ============================================================================

@dataclass
class AmbientDescriptor:
    """Minimal track descriptor for ambient scoring."""
    track_id: UUID
    title: str | None
    artist: str | None
    album: str | None
    duration_seconds: float | None
    key: str | None
    bpm: float | None
    energy: float | None
    brightness: float | None
    valence: float | None
    instrumentalness: float | None
    speechiness: float | None
    dynamic_range_db: float | None
    energy_shape: str | None
    section_count: int | None
    modal_character: str | None
    acousticness: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": str(self.track_id),
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "duration_seconds": self.duration_seconds,
            "key": self.key,
            "bpm": self.bpm,
            "energy": self.energy,
            "brightness": self.brightness,
            "valence": self.valence,
            "instrumentalness": self.instrumentalness,
            "speechiness": self.speechiness,
            "dynamic_range_db": self.dynamic_range_db,
            "energy_shape": self.energy_shape,
            "section_count": self.section_count,
            "modal_character": self.modal_character,
            "acousticness": self.acousticness,
        }


@dataclass
class AmbientCandidate:
    """Scored candidate for ambient playback."""
    descriptor: AmbientDescriptor
    compatibility_score: float
    key_compatibility: float
    suggested_start_pct: float
    suggested_end_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "descriptor": self.descriptor.to_dict(),
            "compatibility_score": round(self.compatibility_score, 4),
            "key_compatibility": round(self.key_compatibility, 4),
            "suggested_start_pct": round(self.suggested_start_pct, 4),
            "suggested_end_pct": round(self.suggested_end_pct, 4),
        }


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def score_candidate(
    current: AmbientDescriptor,
    candidate: AmbientDescriptor,
    intensity: str = "balanced",
    embedding_similarity: float | None = None,
    recent_artist_names: list[str] | None = None,
    profile: RankingProfile | None = None,
    taste_score: float | None = None,
    skip_count: int = 0,
    reject_count: int = 0,
) -> float:
    """Score a candidate track against the current track.

    Returns a score in [0, 1] range (higher = better fit).

    ``profile`` selects the weighting (ADR-0005); it defaults to ``AMBIENT``, which
    reproduces this function's original hard-coded behaviour exactly. ``taste_score``,
    ``skip_count`` and ``reject_count`` are inert under ``AMBIENT`` — their profile
    weights are zero — so ambient callers are unaffected by their presence.

    Stays pure: taste and listening history arrive as numbers rather than being queried
    here, so this remains directly testable and usable from either retrieval path.
    """
    profile = profile or AMBIENT
    # Key compatibility
    key_score = key_compatibility(current.key, candidate.key)

    # Energy proximity
    energy_score = 1.0 - abs(_safe_float(current.energy) - _safe_float(candidate.energy))

    # Embedding similarity (pre-computed in SQL as 1 - cosine_distance)
    embedding_score = embedding_similarity if embedding_similarity is not None else 0.5

    # Vocal penalty: prefer instrumental content
    inst = _safe_float(candidate.instrumentalness)
    speech = _safe_float(candidate.speechiness)
    vocal_score = inst * 0.7 + (1.0 - speech) * 0.3

    # Brightness proximity
    brightness_score = 1.0 - abs(
        _safe_float(current.brightness) - _safe_float(candidate.brightness)
    )

    # Valence proximity
    valence_score = 1.0 - abs(
        _safe_float(current.valence) - _safe_float(candidate.valence)
    )

    # Dynamic range proximity
    dr_diff = abs(
        _safe_float(current.dynamic_range_db) - _safe_float(candidate.dynamic_range_db)
    )
    dr_score = 1.0 - min(dr_diff / 20.0, 1.0)

    # Base weights, with this intensity's overrides applied (see ranking_profiles).
    weights = profile.weights_for(intensity)

    total = (
        weights["key"] * key_score
        + weights["energy"] * energy_score
        + weights["embedding"] * embedding_score
        + weights["vocal"] * vocal_score
        + weights["brightness"] * brightness_score
        + weights["valence"] * valence_score
        + weights["dr"] * dr_score
    )

    # Taste: play count, recency, favourites — reuses the weighting already tuned for
    # this library (`taste_weighting`). Zero-weighted under AMBIENT.
    if profile.taste_weight and taste_score is not None:
        total += profile.taste_weight * max(0.0, min(1.0, taste_score))

    # BPM penalty
    cur_bpm = _safe_float(current.bpm)
    cand_bpm = _safe_float(candidate.bpm)
    if cur_bpm > 0 and cand_bpm > 0 and abs(cur_bpm - cand_bpm) > profile.bpm_threshold:
        total -= profile.bpm_penalty

    # Quiet intensity bonus for low-energy tracks
    if (
        profile.quiet_energy_bonus
        and intensity == "quiet"
        and _safe_float(candidate.energy) < profile.quiet_energy_threshold
    ):
        total += profile.quiet_energy_bonus

    # Dark filter bonus for minor keys
    if profile.minor_key_bonus and candidate.modal_character and "minor" in (candidate.modal_character or "").lower():
        total += profile.minor_key_bonus  # Small bonus, mainly used by dark filter

    # Artist cooldown
    if recent_artist_names and candidate.artist:
        if candidate.artist.lower() in [a.lower() for a in recent_artist_names]:
            total -= profile.artist_cooldown_penalty

    # Negative signal from ADR-0004 PlayEvent. Capped so a track the listener happened to
    # skip a few times is demoted rather than permanently exiled — skips are ambiguous,
    # and an uncapped penalty would make the catalogue shrink over time.
    if profile.max_negative_penalty:
        penalty = profile.skip_penalty * skip_count + profile.reject_penalty * reject_count
        total -= min(penalty, profile.max_negative_penalty)

    return max(0.0, min(1.0, total))


# ============================================================================
# Filter presets
# ============================================================================

FILTER_PRESETS = {
    "all": {},
    "soft": {"max_energy": 0.5, "max_brightness": 0.6, "min_acousticness": 0.2},
    "dark": {"max_valence": 0.45, "max_brightness": 0.5},
    "instrumental": {"min_instrumentalness": 0.5, "max_speechiness": 0.3},
}


def _build_filter_conditions(preset: str) -> list:
    """Build SQLAlchemy filter conditions for a given preset."""
    conditions = []
    params = FILTER_PRESETS.get(preset, {})

    if "max_energy" in params:
        conditions.append(TrackAnalysis.energy <= params["max_energy"])
    if "max_brightness" in params:
        conditions.append(TrackAnalysis.brightness <= params["max_brightness"])
    if "min_acousticness" in params:
        conditions.append(TrackAnalysis.acousticness >= params["min_acousticness"])
    if "max_valence" in params:
        conditions.append(TrackAnalysis.valence <= params["max_valence"])
    if "min_instrumentalness" in params:
        conditions.append(TrackAnalysis.instrumentalness >= params["min_instrumentalness"])
    if "max_speechiness" in params:
        conditions.append(TrackAnalysis.speechiness <= params["max_speechiness"])

    return conditions


# ============================================================================
# Snippet window suggestion
# ============================================================================

def suggest_snippet_window(
    duration_seconds: float | None,
    energy_shape: str | None = None,
) -> tuple[float, float]:
    """Suggest start/end percentages for a snippet window.

    Returns (start_pct, end_pct) in [0, 1].
    Guard bands: skip first 10s, last 15-20s.
    Prefer middle 25-70%.
    """
    if not duration_seconds or duration_seconds < 30:
        return (0.1, 0.9)

    # Guard bands as percentages
    start_guard = min(10.0 / duration_seconds, 0.15)
    end_guard = min(20.0 / duration_seconds, 0.15)

    # Default: prefer middle section
    start_pct = max(0.25, start_guard)
    end_pct = min(0.70, 1.0 - end_guard)

    # Bias by energy shape
    if energy_shape == "building":
        # Prefer later section for building tracks
        start_pct = max(0.35, start_guard)
        end_pct = min(0.80, 1.0 - end_guard)
    elif energy_shape == "declining":
        # Prefer earlier section
        start_pct = max(0.15, start_guard)
        end_pct = min(0.55, 1.0 - end_guard)
    elif energy_shape == "peak_middle":
        # Center on peak
        start_pct = max(0.30, start_guard)
        end_pct = min(0.65, 1.0 - end_guard)

    return (round(start_pct, 4), round(end_pct, 4))


# ============================================================================
# Database queries
# ============================================================================

def _row_to_descriptor(track: Track, analysis: TrackAnalysis) -> AmbientDescriptor:
    """Convert a Track + TrackAnalysis row to an AmbientDescriptor."""
    return AmbientDescriptor(
        track_id=track.id,
        title=track.title,
        artist=track.artist,
        album=track.album,
        duration_seconds=track.duration_seconds,
        key=analysis.key,
        bpm=analysis.bpm,
        energy=analysis.energy,
        brightness=analysis.brightness,
        valence=analysis.valence,
        instrumentalness=analysis.instrumentalness,
        speechiness=analysis.speechiness,
        dynamic_range_db=analysis.dynamic_range_db,
        energy_shape=analysis.energy_shape,
        section_count=analysis.section_count,
        modal_character=analysis.modal_character,
        acousticness=analysis.acousticness,
    )


async def get_track_descriptor(
    db: AsyncSession,
    track_id: UUID,
) -> AmbientDescriptor | None:
    """Fetch a single track's ambient descriptor."""
    result = await db.execute(
        select(Track, TrackAnalysis)
        .join(TrackAnalysis, TrackAnalysis.track_id == Track.id)
        .where(Track.id == track_id)
    )
    row = result.first()
    if not row:
        return None
    return _row_to_descriptor(row[0], row[1])


async def pick_surprise_seed(
    db: AsyncSession,
    filter_preset: str = "all",
) -> AmbientDescriptor | None:
    """Pick a random ambient-friendly seed track.

    Samples 20 candidates with instrumentalness >= 0.5, energy <= 0.7,
    speechiness <= 0.5, duration >= 60s, then picks the one with highest
    ambient fitness (preferring downtempo, quiet tracks).

    Note: we use 0.7 (not the "obvious" 0.5) because librosa's energy
    metric biases high for well-mastered full-band acoustic recordings —
    known-calm piano pieces routinely score 0.6-0.8. The ambient-fitness
    score inside this function still prefers the lowest-energy candidate
    from the pool, so the final seed is as quiet as the library allows.
    """
    base_conditions = [
        TrackAnalysis.instrumentalness >= 0.5,
        TrackAnalysis.speechiness <= 0.5,
        TrackAnalysis.energy <= 0.7,
        Track.duration_seconds >= 60,
        TrackAnalysis.energy.isnot(None),
    ]
    base_conditions.extend(_build_filter_conditions(filter_preset))

    result = await db.execute(
        select(Track, TrackAnalysis)
        .join(TrackAnalysis, TrackAnalysis.track_id == Track.id)
        .where(and_(*base_conditions))
        .order_by(func.random())
        .limit(20)
    )
    rows = result.all()
    if not rows:
        return None

    # Score by ambient fitness: high instrumentalness + low speechiness + moderate energy
    def ambient_fitness(t: Track, a: TrackAnalysis) -> float:
        inst = _safe_float(a.instrumentalness)
        speech = _safe_float(a.speechiness)
        energy = _safe_float(a.energy)
        # Prefer low energy (0.1–0.4 sweet spot)
        energy_bonus = 1.0 - abs(energy - 0.25) * 3.33
        return inst * 0.4 + (1.0 - speech) * 0.3 + max(0, energy_bonus) * 0.3

    best = max(rows, key=lambda r: ambient_fitness(r[0], r[1]))
    return _row_to_descriptor(best[0], best[1])


async def get_candidates(
    db: AsyncSession,
    current_track_id: UUID,
    filter_preset: str = "all",
    intensity: str = "balanced",
    recent_track_ids: list[UUID] | None = None,
    recent_artist_names: list[str] | None = None,
    limit: int = 10,
) -> tuple[list[AmbientCandidate], int, bool]:
    """Fetch and rank candidates for ambient continuation.

    Two-phase: SQL fetches top-150 by embedding distance, Python scores & sorts.

    Returns: (candidates, pool_size, pool_collapsed)
    """
    recent_ids = set(recent_track_ids or [])
    recent_ids.add(current_track_id)

    # Get current track descriptor
    current = await get_track_descriptor(db, current_track_id)
    if not current:
        return [], 0, True

    # Build SQL query — top 150 by embedding similarity
    base_conditions = [
        Track.id.notin_(recent_ids),
        Track.duration_seconds >= 45,
        TrackAnalysis.energy.isnot(None),
    ]
    base_conditions.extend(_build_filter_conditions(filter_preset))

    # Check if current track has an embedding for similarity search
    current_embedding_result = await db.execute(
        select(TrackAnalysis.embedding)
        .where(TrackAnalysis.track_id == current_track_id)
    )
    current_embedding = current_embedding_result.scalar()

    if current_embedding is not None:
        # Use embedding similarity for initial ranking
        cosine_dist = TrackAnalysis.embedding.cosine_distance(current_embedding)
        query = (
            select(
                Track,
                TrackAnalysis,
                (1 - cosine_dist).label("embedding_similarity"),
            )
            .join(TrackAnalysis, TrackAnalysis.track_id == Track.id)
            .where(and_(*base_conditions, TrackAnalysis.embedding.isnot(None)))
            .order_by(cosine_dist)
            .limit(150)
        )
    else:
        # No embedding — fall back to random sampling
        query = (
            select(
                Track,
                TrackAnalysis,
                text("0.5 as embedding_similarity"),
            )
            .join(TrackAnalysis, TrackAnalysis.track_id == Track.id)
            .where(and_(*base_conditions))
            .order_by(func.random())
            .limit(150)
        )

    result = await db.execute(query)
    rows = result.all()

    pool_size = len(rows)
    pool_collapsed = pool_size < 5

    # Python-side scoring
    scored: list[AmbientCandidate] = []
    for row in rows:
        track, analysis, emb_sim = row[0], row[1], row[2]
        descriptor = _row_to_descriptor(track, analysis)
        emb_sim_float = float(emb_sim) if emb_sim is not None else None

        key_compat = key_compatibility(current.key, descriptor.key)
        total_score = score_candidate(
            current,
            descriptor,
            intensity=intensity,
            embedding_similarity=emb_sim_float,
            recent_artist_names=recent_artist_names,
        )

        start_pct, end_pct = suggest_snippet_window(
            descriptor.duration_seconds,
            descriptor.energy_shape,
        )

        scored.append(AmbientCandidate(
            descriptor=descriptor,
            compatibility_score=total_score,
            key_compatibility=key_compat,
            suggested_start_pct=start_pct,
            suggested_end_pct=end_pct,
        ))

    # Sort by score descending
    scored.sort(key=lambda c: c.compatibility_score, reverse=True)

    return scored[:limit], pool_size, pool_collapsed


async def find_seed_by_artist(
    db: AsyncSession,
    artist_name: str,
    filter_preset: str = "all",
) -> AmbientDescriptor | None:
    """Find a seed track by artist name (best ambient fitness)."""
    base_conditions = [
        Track.artist.ilike(f"%{artist_name}%"),
        Track.duration_seconds >= 45,
        TrackAnalysis.energy.isnot(None),
    ]
    base_conditions.extend(_build_filter_conditions(filter_preset))

    result = await db.execute(
        select(Track, TrackAnalysis)
        .join(TrackAnalysis, TrackAnalysis.track_id == Track.id)
        .where(and_(*base_conditions))
        .limit(20)
    )
    rows = result.all()
    if not rows:
        return None

    # Pick the most ambient-friendly track from this artist
    def fitness(t: Track, a: TrackAnalysis) -> float:
        return _safe_float(a.instrumentalness) * 0.4 + (1.0 - _safe_float(a.speechiness)) * 0.3 + (1.0 - abs(_safe_float(a.energy) - 0.4)) * 0.3

    best = max(rows, key=lambda r: fitness(r[0], r[1]))
    return _row_to_descriptor(best[0], best[1])
