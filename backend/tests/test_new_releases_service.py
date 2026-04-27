"""Tests for NewReleasesService (MusicBrainz-only revival)."""

from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from app.db.models import (
    ArtistCheckCache,
    ExternalAlbumCache,
)
from app.services.new_releases import (
    DISCOVERY_CONTEXT,
    NewReleasesService,
    normalize_artist_name,
)
from app.utils.time import utcnow
from tests.factories import (
    insert_test_play_history,
    insert_test_profile,
    insert_test_track,
)


# ---------------------------------------------------------------------------
# Pure function: normalization
# ---------------------------------------------------------------------------


def test_normalize_artist_name_lowercase_strip():
    assert normalize_artist_name("  Radiohead  ") == "radiohead"


def test_normalize_artist_name_strips_diacritics():
    # NFKD-decomposable diacritics get stripped; non-decomposable letters (ð) stay.
    assert normalize_artist_name("Sigur Rós") == "sigur ros"
    assert normalize_artist_name("Beyoncé") == "beyonce"


def test_normalize_artist_name_collapses_whitespace():
    assert normalize_artist_name("Talking   Heads") == "talking heads"


# ---------------------------------------------------------------------------
# Library artists discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_library_artists_dedupes_and_prefers_album_artist(async_db):
    await insert_test_track(
        async_db, title="Track A", artist="The Beatles", album="Abbey Road"
    )
    await insert_test_track(
        async_db, title="Track B", artist="The Beatles", album="Abbey Road"
    )
    # Same artist, no MB id
    await insert_test_track(
        async_db, title="Track C", artist="Radiohead", album="OK Computer"
    )
    await async_db.commit()

    service = NewReleasesService(async_db)
    artists = await service.get_library_artists()

    names = {a["name"] for a in artists}
    assert "The Beatles" in names
    assert "Radiohead" in names
    # Dedup: each artist should appear exactly once
    assert len(artists) == len({a["normalized_name"] for a in artists})


@pytest.mark.asyncio
async def test_get_library_artists_propagates_musicbrainz_id(async_db):
    track = await insert_test_track(async_db, artist="Aphex Twin")
    track.musicbrainz_artist_id = "f22942a1-6f70-4f48-866e-238cb2308fbd"
    await async_db.commit()

    service = NewReleasesService(async_db)
    artists = await service.get_library_artists()

    aphex = next(a for a in artists if a["name"] == "Aphex Twin")
    assert aphex["musicbrainz_artist_id"] == "f22942a1-6f70-4f48-866e-238cb2308fbd"


# ---------------------------------------------------------------------------
# Local-album-match logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_if_user_has_release_via_mb_album_id(async_db):
    track = await insert_test_track(async_db, artist="Foo", album="Bar")
    track.musicbrainz_album_id = "abc-123"
    await async_db.commit()

    service = NewReleasesService(async_db)
    # MB id short-circuit: matches even if names differ
    assert await service.check_if_user_has_release(
        "Different Artist", "Different Album", musicbrainz_album_id="abc-123"
    )
    # Wrong MB id and unrelated names → no match
    assert not await service.check_if_user_has_release(
        "Totally Unrelated", "Nothing Else", musicbrainz_album_id="other-id"
    )


@pytest.mark.asyncio
async def test_check_if_user_has_release_exact_match(async_db):
    await insert_test_track(async_db, artist="Foo", album="Bar")
    await async_db.commit()

    service = NewReleasesService(async_db)
    assert await service.check_if_user_has_release("FOO", "bar")
    assert not await service.check_if_user_has_release("Foo", "Different Album")


@pytest.mark.asyncio
async def test_check_if_user_has_release_fuzzy_match(async_db):
    # 90%+ on album with same artist should match (combined score >=85).
    await insert_test_track(
        async_db, artist="The Strokes", album="Is This It"
    )
    await async_db.commit()

    service = NewReleasesService(async_db)
    # Slight typo in album, exact artist
    assert await service.check_if_user_has_release("The Strokes", "Is This It!")


# ---------------------------------------------------------------------------
# Persistence: save_discovered_release
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_discovered_release_idempotent(async_db):
    service = NewReleasesService(async_db)

    first = await service.save_discovered_release(
        artist_name="Aphex Twin",
        release_id="rg-12345",
        release_name="SAW II Reissue",
    )
    second = await service.save_discovered_release(
        artist_name="Aphex Twin",
        release_id="rg-12345",
        release_name="SAW II Reissue",
    )
    assert first is not None
    assert second is None  # unique on release_id

    # Stored with the artist_new_release context
    result = await async_db.execute(
        select(ExternalAlbumCache).where(ExternalAlbumCache.release_id == "rg-12345")
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].discovery_context == DISCOVERY_CONTEXT


@pytest.mark.asyncio
async def test_save_discovered_release_local_album_match_flag(async_db):
    await insert_test_track(async_db, artist="Aphex Twin", album="SAW II")
    await async_db.commit()

    service = NewReleasesService(async_db)
    saved = await service.save_discovered_release(
        artist_name="Aphex Twin",
        release_id="rg-99999",
        release_name="SAW II",
    )
    assert saved is not None
    assert saved.local_album_match is True


# ---------------------------------------------------------------------------
# Cache window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_check_artist_cache_window(async_db):
    service = NewReleasesService(async_db)

    # No cache entry → check
    assert await service.should_check_artist("brandnew artist")

    # Fresh cache → don't check
    fresh = ArtistCheckCache(
        artist_name_normalized="recent",
        last_checked_at=utcnow() - timedelta(hours=1),
    )
    async_db.add(fresh)
    await async_db.commit()
    assert not await service.should_check_artist("recent")

    # Stale cache → check
    stale = ArtistCheckCache(
        artist_name_normalized="stale",
        last_checked_at=utcnow() - timedelta(hours=48),
    )
    async_db.add(stale)
    await async_db.commit()
    assert await service.should_check_artist("stale")


# ---------------------------------------------------------------------------
# Listing & filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_cached_releases_filters_by_discovery_context(async_db):
    """Pass-2 records (playlist_recommendation) must not appear in #3 listings."""
    nr = ExternalAlbumCache(
        release_id="rg-A",
        discovery_context=DISCOVERY_CONTEXT,
        artist_name="A",
        artist_name_normalized="a",
        release_name="New release A",
    )
    pr = ExternalAlbumCache(
        release_id="rg-B",
        discovery_context="playlist_recommendation",
        artist_name="B",
        artist_name_normalized="b",
        release_name="Recommended for playlist B",
    )
    async_db.add_all([nr, pr])
    await async_db.commit()

    service = NewReleasesService(async_db)
    releases = await service.get_cached_releases(limit=50)
    ids = {r["id"] for r in releases}
    assert str(nr.id) in ids
    assert str(pr.id) not in ids


@pytest.mark.asyncio
async def test_get_cached_releases_excludes_dismissed_and_owned_by_default(async_db):
    base = dict(
        discovery_context=DISCOVERY_CONTEXT,
        artist_name="X",
        artist_name_normalized="x",
        release_name="r",
    )
    visible = ExternalAlbumCache(release_id="rg-vis", **base)
    dismissed = ExternalAlbumCache(release_id="rg-dis", dismissed=True, **base)
    owned = ExternalAlbumCache(release_id="rg-own", local_album_match=True, **base)
    async_db.add_all([visible, dismissed, owned])
    await async_db.commit()

    service = NewReleasesService(async_db)

    default = await service.get_cached_releases(limit=50)
    assert {r["id"] for r in default} == {str(visible.id)}

    inc_dismissed = await service.get_cached_releases(limit=50, include_dismissed=True)
    assert {str(visible.id), str(dismissed.id)} <= {r["id"] for r in inc_dismissed}

    inc_owned = await service.get_cached_releases(limit=50, include_owned=True)
    assert {str(visible.id), str(owned.id)} <= {r["id"] for r in inc_owned}


# ---------------------------------------------------------------------------
# Dismiss
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dismiss_release_flips_flag(async_db):
    profile = await insert_test_profile(async_db)
    rel = ExternalAlbumCache(
        release_id="rg-dismiss-me",
        discovery_context=DISCOVERY_CONTEXT,
        artist_name="A",
        artist_name_normalized="a",
        release_name="r",
    )
    async_db.add(rel)
    await async_db.commit()

    service = NewReleasesService(async_db)
    ok = await service.dismiss_release(rel.id, profile.id)
    assert ok is True
    await async_db.refresh(rel)
    assert rel.dismissed is True
    assert rel.dismissed_by_profile_id == profile.id

    # Bogus ID returns False
    bogus = await service.dismiss_release(UUID(int=0), profile.id)
    assert bogus is False


# ---------------------------------------------------------------------------
# Prioritization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_prioritized_artists_batch_orders_by_recency_and_skips_recent_checks(
    async_db,
):
    profile = await insert_test_profile(async_db)
    now = utcnow()

    # Three tracks with distinct artists
    t_recent = await insert_test_track(async_db, artist="Recent Heavy", album="A")
    t_old = await insert_test_track(async_db, artist="Old Light", album="B")
    t_recent2 = await insert_test_track(async_db, artist="Recent Light", album="C")

    # Listening: Recent Heavy played a lot recently; Old Light played once long ago;
    # Recent Light played once recently.
    await insert_test_play_history(
        async_db, profile.id, t_recent.id,
        play_count=50, last_played_at=now - timedelta(days=1),
    )
    await insert_test_play_history(
        async_db, profile.id, t_old.id,
        play_count=1, last_played_at=now - timedelta(days=300),
    )
    await insert_test_play_history(
        async_db, profile.id, t_recent2.id,
        play_count=1, last_played_at=now - timedelta(days=2),
    )
    await async_db.commit()

    service = NewReleasesService(async_db)
    batch = await service.get_prioritized_artists_batch(
        profile_id=profile.id, batch_size=10
    )

    names = [a["name"] for a in batch]
    # All three present; Recent Heavy first (high recency + high frequency).
    assert names[0] == "Recent Heavy"
    assert set(names) == {"Recent Heavy", "Recent Light", "Old Light"}

    # Mark "Recent Heavy" as recently checked → exclude from next batch
    cache = ArtistCheckCache(
        artist_name_normalized="recent heavy",
        last_checked_at=now - timedelta(days=1),
    )
    async_db.add(cache)
    await async_db.commit()

    batch2 = await service.get_prioritized_artists_batch(
        profile_id=profile.id, batch_size=10, min_days_since_check=7
    )
    names2 = [a["name"] for a in batch2]
    assert "Recent Heavy" not in names2
    assert {"Recent Light", "Old Light"} <= set(names2)


# ---------------------------------------------------------------------------
# Status / rotation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_check_status_aggregates(async_db):
    await insert_test_track(async_db, artist="A", album="x")
    await insert_test_track(async_db, artist="B", album="y")
    rel = ExternalAlbumCache(
        release_id="rg-stat",
        discovery_context=DISCOVERY_CONTEXT,
        artist_name="A",
        artist_name_normalized="a",
        release_name="r",
    )
    cache = ArtistCheckCache(
        artist_name_normalized="a",
        last_checked_at=utcnow(),
    )
    async_db.add_all([rel, cache])
    await async_db.commit()

    service = NewReleasesService(async_db)
    status = await service.get_check_status()
    assert status["artists_in_library"] == 2
    assert status["artists_checked"] == 1
    assert status["new_releases_available"] == 1
    assert status["last_check_at"] is not None
    assert isinstance(datetime.fromisoformat(status["last_check_at"]), datetime)
