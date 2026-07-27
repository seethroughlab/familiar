"""Precomputed offline ranking manifests (ADR-0006).

Offline, the candidate pool is small and known in advance: it is exactly the set of tracks
a device has downloaded. There is no reason to rank it on the device at playback time — it
can be ranked once, here, using the same `score_candidate()` the online path uses.

That identity is the whole point. Before this, offline ambient scored candidates with a
base of 0.5, minus 0.25 for a recently-heard artist, over a random shuffle, with every
analysis feature discarded. Offline listening now gets the same ranking as online rather
than an approximation of it, and no client on any platform carries ranking code.

The server holds no record of what a device has downloaded — see ADR-0006 decision point
3 — so the caller supplies the set.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Track, TrackAnalysis
from app.logging_config import get_logger
from app.services.ambient import (
    FILTER_PRESETS,
    AmbientDescriptor,
    _build_filter_conditions,
    _row_to_descriptor,
    score_candidate,
)
from app.services.ranking_profiles import RankingProfile

logger = get_logger(__name__)

# Neighbours kept per seed. Measured at acceptance: a 1,719-track offline set yields
# roughly 4MB across all profile/preset combinations at this value.
DEFAULT_NEIGHBOURS = 10

# How many nearest-by-embedding candidates to score per seed.
#
# Scoring every pair is O(n^2) — 1,719 tracks is ~2.9M `score_candidate` calls per
# profile, far too slow for a request. The embedding shortlist cuts that to n x 50 while
# reusing the identical scorer, mirroring what `get_candidates` does with HNSW online.
# Wide enough that the top 10 after full scoring are not merely the top 10 by embedding.
SHORTLIST = 50


@dataclass
class ManifestEntry:
    """One seed's ranked neighbours, drawn only from the offline set."""

    track_id: UUID
    neighbours: list[tuple[UUID, float]]


def _cosine_shortlist(embeddings: np.ndarray, k: int) -> np.ndarray:
    """Indices of the top-k most similar rows for each row, excluding self.

    One matmul rather than n^2 Python calls: 1,719 x 512 against its transpose is ~1.5
    GFLOP, well under a second.
    """
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # a zero vector would produce NaNs
    normalised = embeddings / norms

    similarity = normalised @ normalised.T
    np.fill_diagonal(similarity, -np.inf)  # never a candidate for itself

    k = min(k, max(similarity.shape[0] - 1, 1))
    # argpartition is O(n) per row where a full sort would be O(n log n); order within
    # the shortlist does not matter because `score_candidate` re-ranks it anyway.
    return np.argpartition(-similarity, kth=k - 1, axis=1)[:, :k]


async def build_manifest(
    db: AsyncSession,
    track_ids: Sequence[UUID],
    profile: RankingProfile,
    *,
    filter_preset: str = "all",
    neighbours: int = DEFAULT_NEIGHBOURS,
) -> list[ManifestEntry]:
    """Rank every track in `track_ids` against every other track in `track_ids`.

    Neighbours are drawn **only** from the supplied set — a manifest that suggested a
    track the device has not downloaded would be worse than no manifest, because the
    failure would only appear once offline.
    """
    if not track_ids:
        return []

    conditions = [
        Track.active_filter(),
        Track.id.in_(list(track_ids)),
        TrackAnalysis.energy.isnot(None),
    ]
    conditions.extend(_build_filter_conditions(filter_preset))

    rows = (
        await db.execute(
            select(Track, TrackAnalysis, TrackAnalysis.embedding)
            .join(TrackAnalysis, TrackAnalysis.track_id == Track.id)
            .where(*conditions)
        )
    ).all()

    if len(rows) < 2:
        return []

    descriptors: list[AmbientDescriptor] = [_row_to_descriptor(r[0], r[1]) for r in rows]
    raw_embeddings = [r[2] for r in rows]

    # Tracks with an embedding get a similarity shortlist; the rest fall back to a slice
    # of the pool, matching how `get_candidates` degrades when a seed has no embedding
    # rather than inventing a second rule.
    embedded_positions = [i for i, e in enumerate(raw_embeddings) if e is not None]
    shortlists: dict[int, list[int]] = {}

    if len(embedded_positions) >= 2:
        matrix = np.asarray(
            [np.asarray(raw_embeddings[i], dtype=np.float32) for i in embedded_positions]
        )
        top = _cosine_shortlist(matrix, SHORTLIST)
        for local_i, global_i in enumerate(embedded_positions):
            shortlists[global_i] = [embedded_positions[j] for j in top[local_i]]

    all_positions = list(range(len(descriptors)))

    entries: list[ManifestEntry] = []
    for i, seed in enumerate(descriptors):
        candidate_positions = shortlists.get(i)
        if candidate_positions is None:
            candidate_positions = [p for p in all_positions[: SHORTLIST + 1] if p != i]

        scored: list[tuple[UUID, float]] = []
        for j in candidate_positions:
            if j == i:
                continue
            candidate = descriptors[j]
            similarity = None
            if raw_embeddings[i] is not None and raw_embeddings[j] is not None:
                a = np.asarray(raw_embeddings[i], dtype=np.float32)
                b = np.asarray(raw_embeddings[j], dtype=np.float32)
                denom = float(np.linalg.norm(a) * np.linalg.norm(b))
                similarity = float(a @ b / denom) if denom else None

            scored.append(
                (
                    candidate.track_id,
                    score_candidate(
                        seed,
                        candidate,
                        embedding_similarity=similarity,
                        profile=profile,
                    ),
                )
            )

        scored.sort(key=lambda pair: pair[1], reverse=True)
        entries.append(ManifestEntry(track_id=seed.track_id, neighbours=scored[:neighbours]))

    return entries


async def eligible_seed_ids(
    db: AsyncSession,
    track_ids: Sequence[UUID],
    *,
    filter_preset: str = "all",
) -> list[UUID]:
    """Tracks fit to start an offline ambient session.

    Same filters as `pick_surprise_seed` so an offline surprise matches an online one.
    The client picks from this list rather than choosing by feature, which would mean
    shipping features and the rules for reading them.
    """
    if not track_ids:
        return []

    conditions = [
        Track.active_filter(),
        Track.id.in_(list(track_ids)),
        TrackAnalysis.instrumentalness >= 0.5,
        TrackAnalysis.speechiness <= 0.5,
        TrackAnalysis.energy <= 0.7,
        TrackAnalysis.energy.isnot(None),
        Track.duration_seconds >= 60,
    ]
    conditions.extend(_build_filter_conditions(filter_preset))

    rows = (
        await db.execute(
            select(Track.id)
            .join(TrackAnalysis, TrackAnalysis.track_id == Track.id)
            .where(*conditions)
        )
    ).all()
    return [r[0] for r in rows]


def known_presets() -> list[str]:
    """Filter presets a manifest is generated for (`ambient.FILTER_PRESETS`)."""
    return list(FILTER_PRESETS)
