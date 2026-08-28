"""`GET /library/artists` must not resolve artist images on the request path.

Written after measuring the endpoint at **4.1 seconds per page** of 100 against 0.12 for
`/library/albums` doing the same shape of work. The cause was `resolve_many_artist_images`, which
reads the image cache and then spends up to its four-second `wikipedia_timeout` resolving whatever
missed — a Wikipedia round trip while a listener waits, on every page of a browse screen.

It is the same defect as the external-albums endpoint at 71 seconds: expensive external calls on a
request path. And as there, the background mechanism already existed — `schedule_background_resolve`
was being called three lines below, for whatever the synchronous attempt failed to find.

These assert the two halves of the fix separately, because each fails differently: doing the network
work makes the endpoint slow, and *not* scheduling the background work makes the images never
arrive at all.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.db.models import Artist, ExternalArtistImageCache, Track, TrackStatus
from app.services import artist_image
from app.services.artist_resolver import normalize_artist_name
from app.utils.time import utcnow
from tests.conftest import make_profile_headers


async def _artist_with_a_track(db, name: str, *, image_url: str | None = None) -> Artist:
    artist = Artist(id=uuid4(), name=name, sort_name=name, image_url=image_url)
    db.add(artist)
    await db.flush()
    db.add(
        Track(
            id=uuid4(),
            file_path=f"/music/{uuid4().hex}.mp3",
            file_hash=uuid4().hex,
            title="Song",
            artist=name,
            album="Album",
            canonical_artist_id=artist.id,
            status=TrackStatus.ACTIVE,
        )
    )
    await db.commit()
    return artist


@pytest.fixture(autouse=True)
def never_touch_the_network(monkeypatch):
    """Any Wikipedia call from a request is a failure, not a slow test.

    Also stops `schedule_background_resolve` from spawning a real task, which would reach the
    network from the background chain and make the suite depend on it.
    """

    async def _boom(*args, **kwargs):
        raise AssertionError("the request path must not resolve artist images")

    monkeypatch.setattr(artist_image, "_resolve_via_wikipedia", _boom)


@pytest.mark.asyncio
async def test_listing_artists_does_not_wait_on_wikipedia(
    async_db, client, test_profile, monkeypatch
):
    scheduled: list = []
    monkeypatch.setattr(
        artist_image, "schedule_background_resolve", lambda items: scheduled.append(items)
    )
    await _artist_with_a_track(async_db, "Nobody Has A Picture Of")

    response = client.get("/api/v1/library/artists", headers=make_profile_headers(test_profile))

    assert response.status_code == 200, response.text
    names = [a["name"] for a in response.json()["items"]]
    assert "Nobody Has A Picture Of" in names, "the artist is still listed, just without a photo"


@pytest.mark.asyncio
async def test_the_misses_are_handed_to_the_background_resolver(
    async_db, client, test_profile, monkeypatch
):
    """Otherwise the fix is just "never show artist images"."""
    scheduled: list = []
    monkeypatch.setattr(
        artist_image, "schedule_background_resolve", lambda items: scheduled.append(items)
    )
    await _artist_with_a_track(async_db, "Needs Resolving")

    client.get("/api/v1/library/artists", headers=make_profile_headers(test_profile))

    handed_over = [name for batch in scheduled for name, _ in batch]
    assert "Needs Resolving" in handed_over


@pytest.mark.asyncio
async def test_an_image_already_in_the_cache_is_still_served(
    async_db, client, test_profile, monkeypatch
):
    """The cheap half is kept.

    Removing the whole resolver would have been simpler and wrong: `resolve_many_artist_images`
    reads a local cache table *before* it reaches for the network, and dropping that read would blank
    every artist whose image was resolved by an earlier background pass but not yet written onto the
    `Artist` row.
    """
    monkeypatch.setattr(artist_image, "schedule_background_resolve", lambda items: None)
    name = "Cached Already"
    await _artist_with_a_track(async_db, name)
    async_db.add(
        ExternalArtistImageCache(
            name_normalized=normalize_artist_name(name),
            # Non-nullable, and `image_checked_at` is what makes this a *hit* rather than a row —
            # `_read_cached` only counts entries inside their TTL, so a row without a timestamp is
            # invisible and this test would pass for the wrong reason.
            artist_name=name,
            image_url="https://example.com/cached.jpg",
            image_checked_at=utcnow(),
        )
    )
    await async_db.commit()

    response = client.get("/api/v1/library/artists", headers=make_profile_headers(test_profile))

    assert response.status_code == 200, response.text
    served = {a["name"]: a["image_url"] for a in response.json()["items"]}
    assert served[name] == "https://example.com/cached.jpg"
