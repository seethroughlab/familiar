"""What else in the library belongs in this collection (ADR-0093).

**Candidates are chosen by agreement between seeds, never by their average.** That is the whole of
the design, and it is the third attempt: averaging a collection's embeddings was tried at two scales
and failed the same way both times. A mean over all 1,730 favourites returns the library's most
generically average music; k-means into four clusters and a mean of each only moves the problem down
a level, because a cluster of 200 tracks still has a centroid that no track occupies and nothing
truthful to call it.

Taking each seed track's own nearest neighbours and counting which candidates several seeds reach
independently needs no mean anywhere. It also answers a question the centroid could not: *why* a
track is being suggested. Every suggestion carries the seed that pulled it in, so the reason shown to
a listener is a real pair of tracks and a real similarity rather than a generated label.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import all_, any_, desc, func, literal, select, text, true
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import Track, TrackAnalysis
from app.services.playlist_generation import _diverse_in_order

logger = logging.getLogger(__name__)

#: How many of a collection's tracks are read as seeds, most-recent-first. Favorites is ~1,730 tracks
#: and a playlist has no upper bound; without a cap the cost of opening this panel grows with the
#: collection, on a surface opened casually. Each seed is one index probe (ADR-0093 point 6).
SEED_SAMPLE_CAP = 600

#: Ballots to aim for in total, from which `_neighbours_for` derives the per-seed neighbour count.
#:
#: **Neighbours have to scale inversely with the seed count, or agreement cannot happen at all on a
#: small collection.** Measured on the real 26k library with a 9-track playlist: at 10 neighbours
#: each, *zero* candidates were reached by two seeds, so `MIN_VOTES` never engaged and the list fell
#: back entirely to single votes — which is the noise the floor exists to remove. At 30 neighbours
#: the same playlist produced 8 agreed candidates. A large collection has the opposite problem and
#: needs no help: 600 seeds overlap heavily at the floor.
TARGET_BALLOTS = 300

#: Never fewer than this per seed, however large the collection.
NEIGHBOURS_MIN = 10

#: Never more, however small. Past this the neighbours stop being neighbours.
NEIGHBOURS_MAX = 40

#: How many seeds must independently reach a candidate before it is offered.
#:
#: **Not tuning — this is what makes voting safe on a small seed set.** Measured on the real library,
#: a 9-track IDM playlist ranked purely by summed similarity admitted a Hans Zimmer cue that exactly
#: one seed had reached; on a large diverse collection the same single votes are the ones a centroid
#: would have averaged away. Requiring agreement removes them without needing a second mechanism for
#: small collections.
MIN_VOTES = 2

#: Candidates carried out of SQL into the diversity pass. Wide enough that the artist and album caps
#: still have something to choose from after they start rejecting rows.
CANDIDATE_LIMIT = 200


@dataclass(frozen=True)
class Suggestion:
    """One addable track, and the track of yours that reached it."""

    track: Track
    #: The seed with the single strongest vote for this candidate — the one the reason names.
    because_of: Track
    #: That seed's cosine similarity, already `1 - distance`.
    similarity: float
    #: How many seeds reached this candidate independently.
    votes: int


async def suggest_for_collection(
    db: AsyncSession,
    *,
    seed_track_ids: Sequence[UUID],
    exclude_track_ids: set[UUID] | None = None,
    #: Tracks whose *metadata* marks a recording as already known, when that is a
    #: wider set than the ids being excluded. Rediscovery excludes by id at three
    #: plays but considers anything played at all "already heard" for the purpose of
    #: spotting a duplicate file. Defaults to `exclude_track_ids`, which is right when
    #: the two sets are the same — favourites, playlists.
    duplicate_key_ids: set[UUID] | None = None,
    profile_id: UUID | None = None,
    limit: int = 10,
) -> list[Suggestion]:
    """seed set → per-seed neighbours → vote → exclude → diversify → one ranked list.

    ``seed_track_ids`` is expected most-recent-first; only the first `SEED_SAMPLE_CAP` are used.
    ``exclude_track_ids`` is what the listener already has and defaults to the **whole** of
    ``seed_track_ids`` — not the capped sample. ADR-0093 point 4: once the seed is a sample, "exclude
    the seed" and "exclude what you already have" stop being the same set, and the difference is
    visible as a suggestion the listener has already favourited.
    """
    excluded = set(exclude_track_ids) if exclude_track_ids is not None else set(seed_track_ids)
    sample = list(seed_track_ids)[:SEED_SAMPLE_CAP]
    if not sample:
        return []

    neighbours = _neighbours_for(len(sample))
    # `hnsw.ef_search` defaults to 40 and caps a scan regardless of `LIMIT` — the defect that had
    # `POOL_SIZE = 400` returning 40 rows since ADR-0048 shipped. `neighbours` can reach that
    # default, so it is raised here rather than left to sit exactly on the boundary.
    await db.execute(text(f"SET LOCAL hnsw.ef_search = {max(64, neighbours * 2)}"))

    rows = (await db.execute(_vote_query(sample, excluded, neighbours))).all()
    if not rows:
        return []

    candidates = [
        Suggestion(
            track=track,
            because_of=seed,
            similarity=float(similarity),
            votes=int(vote_count),
        )
        for track, seed, vote_count, similarity in rows
    ]

    candidates = _drop_duplicate_recordings(candidates)
    candidates = await _drop_recordings_already_in_the_collection(
        db, candidates, duplicate_key_ids if duplicate_key_ids is not None else excluded
    )
    candidates = await _demote_rejected(db, candidates, profile_id)

    # Agreement first; single votes only to fill. A three-track playlist cannot produce two votes for
    # anything, and answering nothing there would be worse than answering with less confidence.
    chosen = _diversify([c for c in candidates if c.votes >= MIN_VOTES], limit)
    if len(chosen) < limit:
        already = {c.track.id for c in chosen}
        singles = [c for c in candidates if c.votes < MIN_VOTES and c.track.id not in already]
        chosen = chosen + _diversify(singles, limit - len(chosen))

    return chosen[:limit]


def _neighbours_for(seed_count: int) -> int:
    """How wide each seed casts, so that a small collection can still reach agreement.

    A fixed count cannot serve both ends: nine seeds taking ten neighbours each never overlap, while
    six hundred taking forty would be doing forty times the work for a pool that already overlaps at
    ten. Holding the total roughly constant does both.
    """
    return max(NEIGHBOURS_MIN, min(NEIGHBOURS_MAX, -(-TARGET_BALLOTS // max(seed_count, 1))))


def _vote_query(sample: list[UUID], excluded: set[UUID], neighbours: int):
    """One statement: seeds → per-seed neighbours → tally → the strongest seed for each candidate."""
    # Bound as arrays rather than expanded into `IN (...)`. The exclusion can be thousands of ids and
    # is evaluated inside a lateral that runs once per seed; inlining them would have PostgreSQL
    # parse the whole list on every request.
    uuid_array = ARRAY(PGUUID(as_uuid=True))
    seed_ids = literal(sample, uuid_array)
    # Sorted so the same collection produces a byte-identical statement, which keeps the plan cached.
    excluded_ids = literal(sorted(excluded), uuid_array)

    seeds = (
        select(
            TrackAnalysis.track_id.label("seed_id"),
            TrackAnalysis.embedding.label("seed_embedding"),
        )
        .join(Track, Track.id == TrackAnalysis.track_id)
        .where(
            TrackAnalysis.track_id == any_(seed_ids),
            TrackAnalysis.embedding.isnot(None),
            Track.active_filter(),
        )
        .cte("seeds")
    )

    distance = TrackAnalysis.embedding.cosine_distance(seeds.c.seed_embedding)
    nearby = (
        select(TrackAnalysis.track_id.label("candidate_id"), distance.label("distance"))
        .join(Track, Track.id == TrackAnalysis.track_id)
        .where(
            TrackAnalysis.embedding.isnot(None),
            # The same guards the rest of the ranking uses: a candidate with no features cannot be
            # scored, and `active_filter` keeps MISSING files out of a list you can act on.
            TrackAnalysis.energy.isnot(None),
            Track.active_filter(),
            TrackAnalysis.track_id != all_(excluded_ids),
        )
        .order_by(distance)
        .limit(neighbours)
        .lateral("nearby")
    )

    ballots = (
        select(
            nearby.c.candidate_id,
            seeds.c.seed_id,
            (1 - nearby.c.distance).label("similarity"),
        )
        .select_from(seeds.join(nearby, true()))
        .cte("ballots")
    )

    tallied = (
        select(
            ballots.c.candidate_id,
            func.count().label("vote_count"),
            func.sum(ballots.c.similarity).label("score"),
        )
        .group_by(ballots.c.candidate_id)
        # The tiebreak is not decoration. Point 6 was broken once already by depending on the order
        # PostgreSQL happened to return rows in.
        .order_by(desc("score"), ballots.c.candidate_id)
        .limit(CANDIDATE_LIMIT)
        .cte("tallied")
    )

    # The single strongest seed for each surviving candidate — the one the reason names.
    strongest = (
        select(ballots.c.candidate_id, ballots.c.seed_id, ballots.c.similarity)
        .join(tallied, tallied.c.candidate_id == ballots.c.candidate_id)
        .distinct(ballots.c.candidate_id)
        .order_by(ballots.c.candidate_id, desc(ballots.c.similarity), ballots.c.seed_id)
        .cte("strongest")
    )

    seed_track = aliased(Track)
    return (
        select(Track, seed_track, tallied.c.vote_count, strongest.c.similarity)
        .select_from(tallied)
        .join(strongest, strongest.c.candidate_id == tallied.c.candidate_id)
        .join(Track, Track.id == tallied.c.candidate_id)
        .join(seed_track, seed_track.id == strongest.c.seed_id)
        .order_by(desc(tallied.c.score), tallied.c.candidate_id)
    )


def _drop_duplicate_recordings(candidates: list[Suggestion]) -> list[Suggestion]:
    """Keep one row per recording, best-ranked first.

    The artist and album caps cannot catch this: a library with the same song filed twice — a single
    and an album cut, or two rips of one release — produces two rows with different album keys, and
    both survive. Seen on the real library, where "Mr. Projectile — None" was suggested twice in one
    list of ten, which reads as a broken feature rather than a rich one.

    Uses `normalize_for_duplicate_matching`, the same normalisation duplicate detection applies, so
    the two features agree about what counts as the same recording. Tracks missing both artist and
    title are never folded together — an empty key would collapse everything unnamed into one.
    """
    from app.services.normalize import normalize_for_duplicate_matching

    seen: set[tuple[str, str]] = set()
    kept: list[Suggestion] = []
    for candidate in candidates:
        artist = normalize_for_duplicate_matching(candidate.track.artist, strip_articles=True)
        title = normalize_for_duplicate_matching(candidate.track.title)
        if not artist and not title:
            kept.append(candidate)
            continue
        key = (artist, title)
        if key in seen:
            continue
        seen.add(key)
        kept.append(candidate)
    return kept


async def _drop_recordings_already_in_the_collection(
    db: AsyncSession,
    candidates: list[Suggestion],
    excluded: set[UUID],
) -> list[Suggestion]:
    """Drop candidates that are another *file* of a track already in the collection.

    `exclude_track_ids` works on ids, so a library holding the same recording twice —
    an album cut and a single, two rips of one release — has one copy excluded and the
    other free to be suggested. It comes back with similarity 1.0 and its own seed as
    the reason, which reads as "listen to this thing you already play".

    Seen on the live library the day rediscovery shipped: four of ten suggestions were
    a track recommended because of itself. `_drop_duplicate_recordings` cannot catch it
    — that folds duplicates among *candidates*, and here the duplicate is on the other
    side of the comparison.

    **The candidate is exempt from its own key**, and that exemption is the whole
    subtlety. A track played twice and offered back *as itself* is the deep cut this
    feature exists to resurface. The same metadata on a *different row* is a second
    file of something already heard, and useless. Two earlier versions of this filter
    got it wrong in opposite directions — one keyed on seeds and killed deep cuts, one
    keyed on the heard set and let duplicates of barely-played tracks through, which
    is how Interpol's "Anywhere" was still being suggested because you play Interpol's
    "Anywhere".
    """
    from app.services.normalize import normalize_for_duplicate_matching

    if not candidates or not excluded:
        return candidates

    rows = (
        await db.execute(
            select(Track.artist, Track.title).where(Track.id.in_(list(excluded)))
        )
    ).all()
    collection_keys = {
        (
            normalize_for_duplicate_matching(artist, strip_articles=True),
            normalize_for_duplicate_matching(title),
        )
        for artist, title in rows
    }
    collection_keys.discard(("", ""))

    kept = []
    for candidate in candidates:
        key = (
            normalize_for_duplicate_matching(candidate.track.artist, strip_articles=True),
            normalize_for_duplicate_matching(candidate.track.title),
        )
        if key in collection_keys and candidate.track.id not in excluded:
            continue
        kept.append(candidate)
    return kept


def _diversify(candidates: list[Suggestion], limit: int) -> list[Suggestion]:
    """Apply the artist and album caps without losing the ranking.

    `_diverse_in_order` walks an already-sorted list and skips anything over its cap, which is why it
    is reused here rather than `ToolExecutor._apply_diversity` — that one shuffles first and would
    discard the vote ranking entirely.
    """
    if not candidates or limit <= 0:
        return []
    by_id = {c.track.id: c for c in candidates}
    kept = _diverse_in_order(
        # The scores are already in rank order; `_diverse_in_order` re-reads them only for the walk.
        [(c.track, float(len(candidates) - index)) for index, c in enumerate(candidates)],
        limit=limit,
        max_per_artist=2,
        max_per_album=2,
    )
    return [by_id[track.id] for track in kept]


async def _demote_rejected(
    db: AsyncSession, candidates: list[Suggestion], profile_id: UUID | None
) -> list[Suggestion]:
    """Push down anything the listener has skipped or rejected lately.

    Reuses `ambient._fetch_negative_signal`, which counts `skipped` and `rejected` inside a 90-day
    window and never counts `errored` — a track that failed to stream says nothing about taste.

    **Demoted, not removed**, matching how the ranking engine treats the same signal: one accidental
    skip should not exile a track from a list of things you might like.

    There is deliberately no matching *taste boost*. `_fetch_taste_scores` hard-codes the
    ``rediscover`` preset, whose ``favorites_boost`` is 1.0, so the term reduces to "played a lot but
    not lately" — backwards for something you have not added yet, and inert anyway for the 90% of the
    library that has never been played.
    """
    if profile_id is None or not candidates:
        return candidates

    from app.services.ambient import _fetch_negative_signal
    from app.services.ranking_profiles import PLAYLIST

    negative = await _fetch_negative_signal(db, profile_id, [c.track.id for c in candidates])
    if not negative:
        return candidates

    def penalty(suggestion: Suggestion) -> float:
        skips, rejects = negative.get(suggestion.track.id, (0, 0))
        return min(
            skips * PLAYLIST.skip_penalty + rejects * PLAYLIST.reject_penalty,
            PLAYLIST.max_negative_penalty,
        )

    # A stable sort on the penalty alone, so the vote ranking survives wherever the signal is silent
    # — which, with most of the library never played, is most candidates.
    return sorted(candidates, key=penalty)
