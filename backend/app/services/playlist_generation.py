"""Seeded playlist generation from analysis (ADR-0048).

"Make a playlist based on this album" used to be an English sentence handed to a language model.
The model was never the thing that knew which tracks sound alike — the analysis was; the model read
a sentence and chose which query to run. When the seed comes from a right-click there is no sentence
and nothing to interpret, so this runs the query directly.

The pipeline is ADR-0048 point 3: **seed → pool → score → constrain → order → name**. Every stage
but the last two reuses what `ambient.py` and `ranking_profiles.py` already do.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Track, TrackAnalysis
from app.services.ambient import (
    AmbientDescriptor,
    _row_to_descriptor,
    score_candidate,
)
from app.services.ranking_profiles import PLAYLIST

logger = logging.getLogger(__name__)

#: How wide the candidate pool is before scoring. `get_candidates` uses 150 for a single "what
#: next" pick; a playlist keeps 20-50 after an artist cap, so it needs more to choose from or the
#: cap starves it. ADR-0048 point 3's "widened for playlist-sized output".
POOL_SIZE = 400

#: Minimum a track must score to be included at all. Without a floor, a small library returns
#: whatever it has — a "playlist based on Cocteau Twins" padded with death metal because there was
#: nothing else left. Better to return a short playlist than a wrong one.
MIN_SCORE = 0.35


@dataclass(frozen=True)
class SeededPlaylist:
    """The result of generation: what to save, and what to call it."""

    name: str
    track_ids: list[UUID]
    seed_track_ids: list[UUID]
    #: Pool size before scoring, for diagnostics — a collapsed pool is the usual cause of a
    #: disappointing playlist and is invisible from the result alone.
    pool_size: int


@dataclass(frozen=True)
class ResolvedSeed:
    """A closed seed (ADR-0048 point 2), resolved to tracks and a centroid."""

    track_ids: list[UUID]
    #: Mean of the seed tracks' embeddings. **One query, not N** — point 3.
    centroid: list[float] | None
    #: A synthetic descriptor built from the seed's mean features, for the non-embedding terms.
    descriptor: AmbientDescriptor | None
    #: What the playlist is named after, already in display form.
    label: str
    kind: str


async def resolve_seed(
    db: AsyncSession,
    *,
    track_id: UUID | None = None,
    artist: str | None = None,
    album: str | None = None,
    track_ids: list[UUID] | None = None,
    artists: list[str] | None = None,
) -> ResolvedSeed | None:
    """Turn one of the four accepted seed shapes into tracks, a centroid and a label.

    Exactly one shape is expected; the caller validates that. Returns ``None`` when the seed
    matches nothing, which is a 404 rather than an empty playlist — "make a playlist from an album
    that isn't in your library" has no sensible empty answer.
    """
    conditions = [Track.active_filter()]

    if track_id is not None:
        conditions.append(Track.id == track_id)
        kind = "track"
    elif track_ids:
        conditions.append(Track.id.in_(track_ids))
        kind = "tracks"
    elif album is not None:
        conditions.append(func.lower(Track.album) == album.lower())
        if artist:
            conditions.append(func.lower(Track.artist) == artist.lower())
        kind = "album"
    elif artists:
        # **VibeMap selects artists, not tracks.** ADR-0048 point 2 says `track_ids` is "what VibeMap
        # has"; it is not — the map's selection is a set of artist names. Rather than have the client
        # resolve those to hundreds of track ids and post them back, the plural of an accepted seed
        # kind is accepted here, which keeps the centroid on the server where point 3 wants it.
        conditions.append(func.lower(Track.artist).in_([a.lower() for a in artists]))
        kind = "artists"
    elif artist is not None:
        conditions.append(func.lower(Track.artist) == artist.lower())
        kind = "artist"
    else:
        return None

    rows = (
        await db.execute(
            select(Track, TrackAnalysis)
            .join(TrackAnalysis, TrackAnalysis.track_id == Track.id)
            .where(and_(*conditions))
        )
    ).all()

    if not rows:
        return None

    seed_ids = [row[0].id for row in rows]
    descriptors = [_row_to_descriptor(row[0], row[1]) for row in rows]

    embeddings = [row[1].embedding for row in rows if row[1].embedding is not None]
    centroid: list[float] | None = None
    if embeddings:
        # **The centroid, not a loop over seeds** (point 3). A mean of unit-ish CLAP vectors is the
        # direction they have in common; pgvector's cosine distance ignores magnitude, so it does
        # not need renormalising.
        width = len(embeddings[0])
        centroid = [sum(float(e[i]) for e in embeddings) / len(embeddings) for i in range(width)]

    label = _seed_label(kind, rows, artist=artist, album=album)

    return ResolvedSeed(
        track_ids=seed_ids,
        centroid=centroid,
        descriptor=_mean_descriptor(descriptors),
        label=label,
        kind=kind,
    )


def _seed_label(kind: str, rows: Sequence[Any], *, artist: str | None, album: str | None) -> str:
    """What the listener called the thing they right-clicked."""
    first = rows[0][0]
    if kind == "album":
        return album or first.album or "this album"
    if kind == "artist":
        return artist or first.artist or "this artist"
    if kind == "artists":
        names = sorted({row[0].artist for row in rows if row[0].artist})
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} and {names[1]}"
        return f"{names[0]}, {names[1]} and {len(names) - 2} more"
    if kind == "track":
        return first.title or "this track"
    # A set: name it after the artists, which is what VibeMap's selection actually is.
    artists = sorted({row[0].artist for row in rows if row[0].artist})
    if not artists:
        return "these tracks"
    if len(artists) == 1:
        return artists[0]
    if len(artists) == 2:
        return f"{artists[0]} and {artists[1]}"
    return f"{artists[0]}, {artists[1]} and {len(artists) - 2} more"


def _mean_descriptor(descriptors: list[AmbientDescriptor]) -> AmbientDescriptor | None:
    """A synthetic descriptor standing for the seed as a whole.

    `score_candidate` compares a candidate against one descriptor, and a multi-track seed has no
    single one. The mean of each numeric feature is the honest summary; **`key` is deliberately
    dropped** rather than being guessed at, because there is no meaningful average of keys and
    `PLAYLIST` weights key at zero anyway — inventing one would only matter if the profile changed
    underneath this, and then it would matter silently.
    """
    if not descriptors:
        return None

    def mean(attr: str) -> float | None:
        values = [getattr(d, attr) for d in descriptors]
        present = [float(v) for v in values if v is not None]
        return sum(present) / len(present) if present else None

    first = descriptors[0]
    return AmbientDescriptor(
        track_id=first.track_id,
        title=None,
        artist=None,
        album=None,
        duration_seconds=mean("duration_seconds"),
        key=None,
        bpm=mean("bpm"),
        energy=mean("energy"),
        brightness=mean("brightness"),
        valence=mean("valence"),
        instrumentalness=mean("instrumentalness"),
        speechiness=mean("speechiness"),
        dynamic_range_db=mean("dynamic_range_db"),
        energy_shape=None,
        section_count=None,
        modal_character=None,
        acousticness=mean("acousticness"),
    )


def _diverse_in_order(
    scored: list[tuple[Track, float]],
    *,
    limit: int,
    max_per_artist: int,
    max_per_album: int,
) -> list[Track]:
    """Apply the artist and album caps **without losing the ranking**.

    `ToolExecutor._apply_diversity` does the same caps and is tempting to reuse — ADR-0048 points at
    it — but it calls `random.shuffle` first. That is right where it is used, picking a diverse
    subset from an unordered search result, and wrong here: it would discard the scoring entirely
    and return a random selection that merely *looks* ranked. Walking the sorted list in order and
    skipping anything over its cap keeps the best track of each artist rather than an arbitrary one.
    """
    artist_counts: dict[str, int] = {}
    album_counts: dict[str, int] = {}
    kept: list[Track] = []

    for track, _score in scored:
        artist_key = (track.artist or "").lower().strip()
        album_key = f"{artist_key}:{(track.album or '').lower().strip()}"

        if artist_counts.get(artist_key, 0) >= max_per_artist:
            continue
        if album_counts.get(album_key, 0) >= max_per_album:
            continue

        kept.append(track)
        artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
        album_counts[album_key] = album_counts.get(album_key, 0) + 1

        if len(kept) >= limit:
            break

    return kept


def playlist_name(seed: ResolvedSeed) -> str:
    """Deterministic, and says what the seed was (ADR-0048 point 7).

    Never a timestamp. `AI Playlist — Aug 09` was tolerable when a typed sentence had described the
    intent somewhere the listener could still see it; a button leaves no such record, so the name is
    the only thing that says where the playlist came from.
    """
    if seed.kind == "album":
        return f"Based on {seed.label}"
    if seed.kind == "track":
        return f"Based on {seed.label}"
    return f"Like {seed.label}"


async def generate_seeded_playlist(
    db: AsyncSession,
    seed: ResolvedSeed,
    *,
    limit: int = 25,
    max_per_artist: int = 2,
    max_per_album: int = 2,
    include_seed: bool = False,
    profile_id: UUID | None = None,
) -> SeededPlaylist:
    """seed → pool → score → constrain → order → name."""
    seed_ids = set(seed.track_ids)

    conditions = [
        # Same guard ambient learned the hard way: MISSING tracks 404 on stream, and putting one
        # into a playlist is exactly what `active_filter` exists to prevent.
        Track.active_filter(),
        TrackAnalysis.energy.isnot(None),
    ]
    # ADR-0048 point 5: the seed is excluded by default. "A playlist based on this album" that opens
    # with that album has answered a question nobody asked.
    if not include_seed:
        conditions.append(Track.id.notin_(seed_ids))

    if seed.centroid is not None:
        cosine_dist = TrackAnalysis.embedding.cosine_distance(seed.centroid)
        query = (
            select(Track, TrackAnalysis, (1 - cosine_dist).label("similarity"))
            .join(TrackAnalysis, TrackAnalysis.track_id == Track.id)
            .where(and_(*conditions, TrackAnalysis.embedding.isnot(None)))
            .order_by(cosine_dist)
            .limit(POOL_SIZE)
        )
    else:
        # No embedding on any seed track — unanalysed, or analysed before embeddings existed.
        # Feature scoring still works, so this degrades rather than failing.
        query = (
            select(Track, TrackAnalysis, literal(0.5).label("similarity"))
            .join(TrackAnalysis, TrackAnalysis.track_id == Track.id)
            .where(and_(*conditions))
            .order_by(func.random())
            .limit(POOL_SIZE)
        )

    rows = (await db.execute(query)).all()
    pool_size = len(rows)

    if not rows or seed.descriptor is None:
        return SeededPlaylist(
            name=playlist_name(seed),
            track_ids=[],
            seed_track_ids=seed.track_ids,
            pool_size=pool_size,
        )

    # Taste and negative signal, when a listener is known. Same two queries `get_candidates` runs,
    # and skipped entirely when the profile does not weigh them.
    taste_scores: dict[UUID, float] = {}
    negative: dict[UUID, tuple[int, int]] = {}
    if profile_id is not None:
        from app.services.ambient import _fetch_negative_signal, _fetch_taste_scores

        candidate_ids = [row[0].id for row in rows]
        if PLAYLIST.taste_weight:
            taste_scores = await _fetch_taste_scores(db, profile_id, candidate_ids)
        if PLAYLIST.max_negative_penalty:
            negative = await _fetch_negative_signal(db, profile_id, candidate_ids)

    scored: list[tuple[Track, float]] = []
    for track, analysis, similarity in rows:
        skips, rejects = negative.get(track.id, (0, 0))
        score = score_candidate(
            seed.descriptor,
            _row_to_descriptor(track, analysis),
            embedding_similarity=float(similarity) if similarity is not None else None,
            profile=PLAYLIST,
            taste_score=taste_scores.get(track.id),
            skip_count=skips,
            reject_count=rejects,
        )
        if score >= MIN_SCORE:
            scored.append((track, score))

    scored.sort(key=lambda pair: pair[1], reverse=True)

    tracks = _diverse_in_order(
        scored,
        limit=limit,
        max_per_artist=max_per_artist,
        max_per_album=max_per_album,
    )

    return SeededPlaylist(
        name=playlist_name(seed),
        track_ids=[t.id for t in tracks],
        seed_track_ids=seed.track_ids,
        pool_size=pool_size,
    )
