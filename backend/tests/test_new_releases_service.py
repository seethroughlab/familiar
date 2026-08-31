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
    """After Pass 2, the MBID on the canonical ``Artist`` row is the
    authoritative source — the resolver writes it during scan/backfill
    when the tag MBID's MB-canonical name plausibly matches the tag. We
    set both the track tag MBID and the Artist row MBID here to mimic
    that post-resolver state."""
    from sqlalchemy import select

    from app.db.models import Artist

    track = await insert_test_track(async_db, artist="Aphex Twin")
    track.musicbrainz_artist_id = "f22942a1-6f70-4f48-866e-238cb2308fbd"
    aphex_artist = (
        await async_db.execute(
            select(Artist).where(Artist.name == "Aphex Twin")
        )
    ).scalar_one()
    aphex_artist.musicbrainz_id = "f22942a1-6f70-4f48-866e-238cb2308fbd"
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


# ---------------------------------------------------------------------------
# ADR-0099: the dedup must be scoped to its own discovery context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_discovered_release_is_scoped_to_its_own_discovery_context(async_db):
    """A release already cached under a *different* context must not block this one.

    This is the nineteen-night outage, in one test. ``external_album_cache`` does not
    enforce uniqueness on ``release_id`` globally — it carries three *partial* unique
    indexes, one per ``discovery_context`` — so the same release legitimately exists
    once per context. ``save_discovered_release`` deduped on ``release_id`` alone and
    called ``scalar_one_or_none()``, which raises ``MultipleResultsFound`` the moment
    two rows come back.

    In production exactly one release did this: ``b9df3445-4699-4221-9994-734c1c912468``
    ("Reality Awaits"), present as both ``artist_new_release`` and
    ``listening_profile_recommendation``. That single row crashed the nightly discovery
    job every night from 2026-08-11 to 2026-08-30.

    Against the old code this test raises rather than fails.
    """
    shared_release_id = "b9df3445-4699-4221-9994-734c1c912468"

    async_db.add(
        ExternalAlbumCache(
            release_id=shared_release_id,
            discovery_context="listening_profile_recommendation",
            artist_name="Bruised Sky",
            artist_name_normalized=normalize_artist_name("Bruised Sky"),
            release_name="Reality Awaits",
        )
    )
    await async_db.flush()

    service = NewReleasesService(async_db)
    saved = await service.save_discovered_release(
        artist_name="Bruised Sky",
        release_id=shared_release_id,
        release_name="Reality Awaits",
    )

    assert saved is not None, "a new context is a new row, not a duplicate"

    result = await async_db.execute(
        select(ExternalAlbumCache).where(
            ExternalAlbumCache.release_id == shared_release_id
        )
    )
    contexts = sorted(row.discovery_context for row in result.scalars().all())
    assert contexts == ["artist_new_release", "listening_profile_recommendation"]


@pytest.mark.asyncio
async def test_save_discovered_release_second_call_is_a_no_op_not_an_error(async_db):
    """Re-saving within the same context returns None and does not raise.

    The upsert replaced a check-then-write, so this pins the contract that the
    conflict path is silent: ``None`` means "already had it", which is what the
    ``releases_new`` counter is built on.
    """
    service = NewReleasesService(async_db)

    first = await service.save_discovered_release(
        artist_name="Boards of Canada",
        release_id="rg-same-context",
        release_name="Tomorrow's Harvest",
    )
    second = await service.save_discovered_release(
        artist_name="Boards of Canada",
        release_id="rg-same-context",
        release_name="Tomorrow's Harvest",
    )

    assert first is not None
    assert second is None

    result = await async_db.execute(
        select(ExternalAlbumCache).where(
            ExternalAlbumCache.release_id == "rg-same-context"
        )
    )
    assert len(result.scalars().all()) == 1


def test_index_predicates_match_the_model():
    """The literal ON CONFLICT predicates must equal the model's index predicates.

    ``_INDEX_WHERE_BY_CONTEXT`` restates each partial index's ``postgresql_where`` as a
    literal, because PostgreSQL cannot infer a partial index from a parameterised
    predicate. That makes it a second source of truth, and this asserts the two agree —
    the first copy of this knowledge is what drifted.
    """
    from app.db.models import ExternalAlbumCache as EAC
    from app.services.external_albums_helpers import _INDEX_WHERE_BY_CONTEXT

    model_predicates = {
        str(idx.dialect_options["postgresql"]["where"])
        for idx in EAC.__table__.indexes
        if idx.unique and idx.dialect_options["postgresql"].get("where") is not None
    }
    mapped_predicates = {str(clause) for clause in _INDEX_WHERE_BY_CONTEXT.values()}

    assert mapped_predicates == model_predicates, (
        "every partial unique index needs an entry, and every entry an index — "
        "artist_new_release was missing from the map, which is ADR-0099"
    )


@pytest.mark.asyncio
async def test_save_does_not_raise_when_a_release_already_exists_in_two_contexts(
    async_db,
):
    """The crash itself: two pre-existing rows for one release_id.

    This is the state production reached and the one that actually took the job
    down. The recommendations writer upserts scoped to its own context, so it will
    happily add a ``listening_profile_recommendation`` row for a release that
    already has an ``artist_new_release`` row. Once both exist, the next discovery
    run selected on ``release_id`` alone, got two rows back, and
    ``scalar_one_or_none()`` raised ``MultipleResultsFound`` — aborting the batch.

    Nineteen consecutive nights, from one release.
    """
    release_id = "b9df3445-4699-4221-9994-734c1c912468"

    for context in ("artist_new_release", "listening_profile_recommendation"):
        async_db.add(
            ExternalAlbumCache(
                release_id=release_id,
                discovery_context=context,
                artist_name="Bruised Sky",
                artist_name_normalized=normalize_artist_name("Bruised Sky"),
                release_name="Reality Awaits",
            )
        )
    await async_db.flush()

    service = NewReleasesService(async_db)

    # Must not raise. The release is already cached in this context, so this is a
    # no-op — but a no-op, not an exception that ends the run.
    result = await service.save_discovered_release(
        artist_name="Bruised Sky",
        release_id=release_id,
        release_name="Reality Awaits",
    )
    assert result is None


# ---------------------------------------------------------------------------
# ADR-0099 point 1: the read path is a database query, and stays one
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_releases_view_never_calls_musicbrainz(async_db, monkeypatch):
    """The load-bearing assertion of Phase 1.

    Reading the returned releases proves the cache is wired up; it does not prove
    the live scan is gone. So MusicBrainz is made to explode: if any code path
    still reaches it, this test raises rather than quietly passing.

    That path is what hung an MCP host for 240 seconds on 2026-08-30.
    """
    def _explode(*args, **kwargs):
        raise AssertionError("the read path called MusicBrainz — ADR-0099 point 1")

    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.get_artist_releases_recent", _explode
    )
    monkeypatch.setattr("app.services.metadata.musicbrainz.search_artist", _explode)

    async_db.add(
        ExternalAlbumCache(
            release_id="rg-view-1",
            discovery_context=DISCOVERY_CONTEXT,
            artist_name="Tycho",
            artist_name_normalized=normalize_artist_name("Tycho"),
            release_name="Anotherwave",
            release_date=utcnow().replace(tzinfo=None) - timedelta(days=3),
            discovered_at=utcnow().replace(tzinfo=None),
        )
    )
    await async_db.flush()

    view = await NewReleasesService(async_db).get_new_releases_view()

    assert [r["title"] for r in view["releases"]] == ["Anotherwave"]
    assert view["as_of"] is not None
    assert view["age_hours"] is not None and view["age_hours"] < 1


@pytest.mark.asyncio
async def test_new_releases_view_reports_never_run_distinctly(async_db):
    """An empty cache is 'discovery has not run', not 'there is nothing new'."""
    view = await NewReleasesService(async_db).get_new_releases_view()

    assert view["releases"] == []
    assert view["as_of"] is None
    assert view["age_hours"] is None
    assert "not the same as" in view["note"]


@pytest.mark.asyncio
async def test_new_releases_view_reports_stale_data_as_stale(async_db):
    """Five days old is what production actually served while the job crashed."""
    old = utcnow().replace(tzinfo=None) - timedelta(days=5)
    async_db.add(
        ExternalAlbumCache(
            release_id="rg-view-stale",
            discovery_context=DISCOVERY_CONTEXT,
            artist_name="Coil",
            artist_name_normalized=normalize_artist_name("Coil"),
            release_name="Aqua Regalia",
            release_date=old,
            discovered_at=old,
        )
    )
    await async_db.flush()

    view = await NewReleasesService(async_db).get_new_releases_view()

    assert view["age_hours"] >= 100
    assert "stale" in view["note"]
    assert "5 day(s) ago" in view["note"]


@pytest.mark.asyncio
async def test_new_releases_view_excludes_dismissed(async_db):
    """A dismissal is the listener's decision and the read path must honour it."""
    now = utcnow().replace(tzinfo=None)
    for release_id, dismissed in (("rg-keep", False), ("rg-drop", True)):
        async_db.add(
            ExternalAlbumCache(
                release_id=release_id,
                discovery_context=DISCOVERY_CONTEXT,
                artist_name="Squarepusher",
                artist_name_normalized=normalize_artist_name("Squarepusher"),
                release_name=release_id,
                release_date=now,
                discovered_at=now,
                dismissed=dismissed,
            )
        )
    await async_db.flush()

    view = await NewReleasesService(async_db).get_new_releases_view()
    assert [r["title"] for r in view["releases"]] == ["rg-keep"]


@pytest.mark.asyncio
async def test_new_releases_view_in_library_comes_from_the_precompute(async_db):
    """`local_album_match` was computed at write time; the read does no matching."""
    now = utcnow().replace(tzinfo=None)
    async_db.add(
        ExternalAlbumCache(
            release_id="rg-owned",
            discovery_context=DISCOVERY_CONTEXT,
            artist_name="Brian Eno",
            artist_name_normalized=normalize_artist_name("Brian Eno"),
            release_name="Afterlife",
            release_date=now,
            discovered_at=now,
            local_album_match=True,
        )
    )
    await async_db.flush()

    view = await NewReleasesService(async_db).get_new_releases_view()
    assert view["releases"][0]["in_library"] is True
    assert view["new_releases_not_in_library"] == 0
