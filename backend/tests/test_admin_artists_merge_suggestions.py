"""Tests for the merge-suggestions endpoint.

Endpoint: GET /api/v1/admin/artists/merge-suggestions
Behavior: groups artists whose canonicalized name (article-decoration
stripped) collides; orders MBID-bearing first; sorts groups by total
track count desc.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.api.routes.admin_artists import get_merge_suggestions
from app.db.models import Artist, Track, TrackStatus


def _new_track(*, file: str, artist_id) -> Track:
    return Track(
        id=uuid4(),
        file_path=f"/music/{file}.mp3",
        file_hash=f"hash-{file}",
        title=file,
        artist="x",
        canonical_artist_id=artist_id,
        status=TrackStatus.ACTIVE,
    )


async def _make_artist(db, name: str, *, mbid: str | None = None) -> Artist:
    artist = Artist(name=name, sort_name=name, musicbrainz_id=mbid)
    db.add(artist)
    await db.flush()
    return artist


@pytest.mark.asyncio
async def test_suggestions_groups_beatles_cluster(async_db):
    """The classic case: 'Beatles', 'The Beatles', 'Beatles, The' all
    canonicalize to 'beatles'."""
    a = await _make_artist(async_db, "The Beatles", mbid="mb-beatles")
    b = await _make_artist(async_db, "Beatles")
    c = await _make_artist(async_db, "Beatles, The")
    # Tracks so the suggestion has track counts.
    async_db.add(_new_track(file="t1", artist_id=a.id))
    async_db.add(_new_track(file="t2", artist_id=a.id))
    async_db.add(_new_track(file="t3", artist_id=b.id))
    async_db.add(_new_track(file="t4", artist_id=c.id))
    await async_db.commit()

    profile = type("FakeProfile", (), {"id": uuid4()})()
    result = await get_merge_suggestions(
        db=async_db, profile=profile, limit=100  # type: ignore[arg-type]
    )

    assert len(result.suggestions) == 1
    suggestion = result.suggestions[0]
    assert suggestion.canonical_form == "beatles"
    assert {c.id for c in suggestion.candidates} == {str(a.id), str(b.id), str(c.id)}
    # MBID-bearing first → "The Beatles" is suggested keep.
    assert suggestion.suggested_keep_id == str(a.id)


@pytest.mark.asyncio
async def test_suggestions_excludes_singletons(async_db):
    """Artists with no name-twin don't appear in suggestions."""
    await _make_artist(async_db, "Slowdive")
    await _make_artist(async_db, "Cocteau Twins")
    await async_db.commit()

    profile = type("FakeProfile", (), {"id": uuid4()})()
    result = await get_merge_suggestions(
        db=async_db, profile=profile, limit=100  # type: ignore[arg-type]
    )

    assert result.suggestions == []


@pytest.mark.asyncio
async def test_suggestions_orders_by_total_track_count(async_db):
    """Most-impactful merges first."""
    # Cluster A: "Foo" / "The Foo" — 2 + 5 = 7 tracks.
    a1 = await _make_artist(async_db, "Foo", mbid="mb-foo")
    a2 = await _make_artist(async_db, "The Foo")
    # Cluster B: "Bar" / "The Bar" — 100 tracks total.
    b1 = await _make_artist(async_db, "Bar")
    b2 = await _make_artist(async_db, "The Bar", mbid="mb-bar")

    for i in range(2):
        async_db.add(_new_track(file=f"a1-{i}", artist_id=a1.id))
    for i in range(5):
        async_db.add(_new_track(file=f"a2-{i}", artist_id=a2.id))
    for i in range(50):
        async_db.add(_new_track(file=f"b1-{i}", artist_id=b1.id))
    for i in range(50):
        async_db.add(_new_track(file=f"b2-{i}", artist_id=b2.id))
    await async_db.commit()

    profile = type("FakeProfile", (), {"id": uuid4()})()
    result = await get_merge_suggestions(
        db=async_db, profile=profile, limit=100  # type: ignore[arg-type]
    )

    assert len(result.suggestions) == 2
    # Bar cluster (100 tracks) before Foo cluster (7 tracks).
    assert result.suggestions[0].canonical_form == "bar"
    assert result.suggestions[1].canonical_form == "foo"


@pytest.mark.asyncio
async def test_suggestions_mbid_artists_rank_first_within_group(async_db):
    """Within a cluster, MBID-bearing artist is the suggested keep."""
    no_mbid = await _make_artist(async_db, "Beatles")  # no MBID
    has_mbid = await _make_artist(async_db, "The Beatles", mbid="mb-beatles")
    async_db.add(_new_track(file="t1", artist_id=no_mbid.id))
    async_db.add(_new_track(file="t2", artist_id=no_mbid.id))
    # Has-MBID artist with FEWER tracks but MBID still wins as keep.
    async_db.add(_new_track(file="t3", artist_id=has_mbid.id))
    await async_db.commit()

    profile = type("FakeProfile", (), {"id": uuid4()})()
    result = await get_merge_suggestions(
        db=async_db, profile=profile, limit=100  # type: ignore[arg-type]
    )

    assert len(result.suggestions) == 1
    suggestion = result.suggestions[0]
    assert suggestion.suggested_keep_id == str(has_mbid.id)
    # MBID-bearing first in the candidates list.
    assert suggestion.candidates[0].id == str(has_mbid.id)
    assert suggestion.candidates[0].musicbrainz_id == "mb-beatles"
