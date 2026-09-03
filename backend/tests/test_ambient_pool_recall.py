"""The candidate pool has to be the size the ranker was written around.

**pgvector's HNSW index returns at most `hnsw.ef_search` rows, whatever the LIMIT says**, and the
default is 40. So `get_candidates` asked for 150 and received 40 from the day the index was created
— a quarter of its pool — and nothing anywhere said so. The results were neither slow nor visibly
wrong; they were simply drawn from a much smaller set.

It surfaced as ambient sessions ending after a handful of windows with "running low on matching
tracks". Every transition excludes what has just played, so a pool of 40 drains in minutes where 150
does not. Radio, playlist generation, collection suggestions and the offline manifest all rank
through the same function and were quietly working from the smaller pool too.

**Only `test_ef_search_is_set` actually catches the regression, and the rest are honest about not
doing so.** A 200-row synthetic library will not reproduce the cap: the planner does not take the
HNSW path on a table that small, even with `enable_seqscan` off, so `get_candidates` returns the
full LIMIT with or without the fix. Two attempts at forcing it failed — the first set
`enable_seqscan` before a `commit()` that discarded it, and passed for the wrong reason.

Reproducing it properly needs a library big enough for the index to be worth using, which is not
something to build in a fixture. So the guard is the setting itself, and the pool assertions below
are what they look like: checks that a healthy library ranks against a healthy pool.
"""

import pytest
from sqlalchemy import text

from app.services.ambient import CANDIDATE_EF_SEARCH, CANDIDATE_POOL, get_candidates
from tests.factories import insert_test_analysis, insert_test_track

# Comfortably past the pgvector default of 40, and past `CANDIDATE_POOL` too, so a query that
# honours neither is distinguishable from one that honours only the LIMIT.
LIBRARY = 200


def _embedding(index: int) -> list[float]:
    """A 512-dim unit-ish vector that varies per track, so distances differ."""
    vector = [0.0] * 512
    vector[index % 512] = 1.0
    vector[(index * 7 + 3) % 512] = 0.5
    return vector


@pytest.fixture
async def library(async_db):
    tracks = []
    for i in range(LIBRARY):
        track = await insert_test_track(
            async_db, title=f"Track {i}", artist=f"Artist {i % 20}", duration_seconds=240.0
        )
        await insert_test_analysis(
            async_db,
            track.id,
            {
                "energy": 0.5,
                "brightness": 0.5,
                "valence": 0.5,
                "key": "C",
                "bpm": 120.0,
                "instrumentalness": 0.8,
                "speechiness": 0.1,
                "embedding": _embedding(i),
            },
        )
        tracks.append(track)
    await async_db.commit()

    # **After the commit, and without LOCAL — both matter.** On a 200-row table the planner picks a
    # sequential scan, which has no `ef_search` and happily returns everything the LIMIT asks for,
    # so the bug does not reproduce and these tests pass against the broken code. Forcing the index
    # is what makes a small library behave like the 26,000-track one where this was found.
    #
    # The first attempt set it before the inserts, where the `commit()` above promptly discarded it
    # — the tests still passed, and for the wrong reason.
    await async_db.execute(text("SET enable_seqscan = off"))
    return tracks


async def test_the_pool_is_not_capped_at_the_pgvector_default(async_db, library):
    """A healthy library ranks against a healthy pool.

    **Not the regression test** — see the module note. On 200 rows this passes with or without
    `ef_search` set, because the planner never reaches for the index. It is here to catch a pool
    that collapses for some *other* reason: a filter that excludes too much, a join that drops rows.
    """
    _, pool_size, collapsed = await get_candidates(async_db, current_track_id=library[0].id)

    assert pool_size > 40, (
        f"pool of {pool_size} is the pgvector ef_search default — the LIMIT is being ignored"
    )
    assert pool_size > CANDIDATE_POOL * 0.8
    assert not collapsed


async def test_a_large_library_never_reports_a_collapsed_pool(async_db, library):
    """`pool_collapsed` is what the client turns into "Session ended".

    With 200 analysed tracks it must never fire, however many have already played.
    """
    seed = library[0]
    recent = [t.id for t in library[1:40]]

    _, pool_size, collapsed = await get_candidates(
        async_db, current_track_id=seed.id, recent_track_ids=recent
    )

    assert not collapsed, f"a 200-track library collapsed at pool_size={pool_size}"
    assert pool_size > 40


async def test_a_session_can_walk_many_windows_without_draining(async_db, library):
    """The failure was cumulative, so this reproduces the shape rather than one call.

    Each step excludes everything played so far, exactly as the client does. At the default
    `ef_search` this runs out; it must not.
    """
    current = library[0].id
    played: list = [current]

    for step in range(20):
        candidates, pool_size, collapsed = await get_candidates(
            async_db, current_track_id=current, recent_track_ids=played, limit=10
        )
        assert candidates, f"ran out of candidates at step {step} (pool {pool_size})"
        assert not collapsed, f"pool collapsed at step {step} (pool {pool_size})"
        current = candidates[0].descriptor.track_id
        played.append(current)


async def test_ef_search_is_set(async_db, library):
    """**The regression test, and the only one here that is.**

    Measured on the real 26,000-track library: the same query returns 40 rows at the default and 150
    with this raised. Since a small library cannot reproduce that, this asserts the setting rather
    than its effect — and it does fail when the `SET LOCAL` is removed.

    `SET LOCAL` rather than `SET`, so nothing else on the connection inherits a wider search and
    pays for it.
    """
    await get_candidates(async_db, current_track_id=library[0].id)

    # Still inside the fixture's transaction, so a `SET LOCAL` is visible; what matters is that the
    # value is the one this module asked for rather than something a previous caller left behind.
    current = (await async_db.execute(text("SHOW hnsw.ef_search"))).scalar()
    assert int(current) == CANDIDATE_EF_SEARCH


def test_the_search_list_is_larger_than_the_pool_it_feeds():
    """`ef_search` is the size of the list the index keeps, so asking for exactly `CANDIDATE_POOL`
    would make the last candidate the worst one the search happened to hold."""
    assert CANDIDATE_EF_SEARCH > CANDIDATE_POOL
