"""Tests for the manual merge-search endpoint.

Endpoint: GET /api/v1/admin/artists/search?q=...&limit=20
Behavior: case-insensitive substring match on Artist.name and
Artist.sort_name; ordered by track count desc; empty query returns
empty results.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.api.routes.admin_artists import search_artists
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


async def _make_artist(db, name: str, sort_name: str | None = None, *, mbid: str | None = None) -> Artist:
    artist = Artist(name=name, sort_name=sort_name or name, musicbrainz_id=mbid)
    db.add(artist)
    await db.flush()
    return artist


@pytest.mark.asyncio
async def test_search_substring_match_on_name(async_db):
    a = await _make_artist(async_db, "Various Artists")
    b = await _make_artist(async_db, "Various")
    await _make_artist(async_db, "Cocteau Twins")
    async_db.add(_new_track(file="t1", artist_id=a.id))
    async_db.add(_new_track(file="t2", artist_id=b.id))
    await async_db.commit()

    profile = type("FakeProfile", (), {"id": uuid4()})()
    response = await search_artists(
        db=async_db, profile=profile, q="various"  # type: ignore[arg-type]
    )

    names = {r.name for r in response.results}
    assert names == {"Various Artists", "Various"}


@pytest.mark.asyncio
async def test_search_matches_sort_name(async_db):
    """Querying 'beatles' surfaces an artist whose sort_name is 'Beatles, The'."""
    await _make_artist(async_db, "The Beatles", sort_name="Beatles, The", mbid="mb-beatles")
    await async_db.commit()

    profile = type("FakeProfile", (), {"id": uuid4()})()
    response = await search_artists(
        db=async_db, profile=profile, q="beatles"  # type: ignore[arg-type]
    )

    assert len(response.results) == 1
    assert response.results[0].name == "The Beatles"


@pytest.mark.asyncio
async def test_search_orders_by_track_count_desc(async_db):
    big = await _make_artist(async_db, "Various Artists")
    small = await _make_artist(async_db, "Various")
    for i in range(10):
        async_db.add(_new_track(file=f"big-{i}", artist_id=big.id))
    async_db.add(_new_track(file="small-1", artist_id=small.id))
    await async_db.commit()

    profile = type("FakeProfile", (), {"id": uuid4()})()
    response = await search_artists(
        db=async_db, profile=profile, q="various"  # type: ignore[arg-type]
    )

    assert [r.name for r in response.results] == ["Various Artists", "Various"]
    assert response.results[0].track_count == 10
    assert response.results[1].track_count == 1


@pytest.mark.asyncio
async def test_search_empty_query_returns_empty(async_db):
    await _make_artist(async_db, "The Beatles")
    await async_db.commit()

    profile = type("FakeProfile", (), {"id": uuid4()})()
    assert (
        await search_artists(db=async_db, profile=profile, q="")  # type: ignore[arg-type]
    ).results == []
    assert (
        await search_artists(db=async_db, profile=profile, q="   ")  # type: ignore[arg-type]
    ).results == []


@pytest.mark.asyncio
async def test_search_honors_limit(async_db):
    for i in range(5):
        await _make_artist(async_db, f"Various #{i}")
    await async_db.commit()

    profile = type("FakeProfile", (), {"id": uuid4()})()
    response = await search_artists(
        db=async_db, profile=profile, q="various", limit=2  # type: ignore[arg-type]
    )
    assert len(response.results) == 2
