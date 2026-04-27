"""Service-level tests for the playlist external-albums lane (#2)."""

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import ArtistCheckCache, ExternalAlbumCache
from app.services.recommendations import (
    PLAYLIST_REC_CONTEXT,
    RecommendationsService,
)
from app.utils.time import utcnow
from tests.factories import (
    insert_test_playlist,
    insert_test_playlist_track,
    insert_test_profile,
    insert_test_track,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lastfm_similar(name: str, match: float = 0.9) -> dict[str, Any]:
    return {"name": name, "match": str(match), "url": f"https://last.fm/music/{name}"}


def _make_mb_search(name: str, mb_id: str, score: int = 95) -> dict[str, Any]:
    return {"name": name, "musicbrainz_artist_id": mb_id, "score": score}


def _make_mb_release(rg_id: str, title: str) -> dict[str, Any]:
    return {
        "musicbrainz_release_group_id": rg_id,
        "title": title,
        "release_type": "Album",
        "release_date": "2024-06-01",
        "release_date_parsed": "2024-06-01T00:00:00",
        "artwork_url": f"https://coverartarchive.org/release-group/{rg_id}/front-250",
    }


async def _seed_playlist(async_db, name: str = "Mix") -> tuple:
    profile = await insert_test_profile(async_db)
    playlist = await insert_test_playlist(async_db, profile.id, name=name)
    track = await insert_test_track(async_db, artist="Radiohead", album="OK Computer")
    await insert_test_playlist_track(async_db, playlist.id, track_id=track.id)
    await async_db.commit()
    return profile, playlist, track


class _StubLastfm:
    """Drop-in stand-in for LastfmService used in service-level tests."""

    def __init__(self, configured: bool, similar: dict[str, list[dict]] | None = None):
        self._configured = configured
        self._similar = similar or {}
        self.calls: list[str] = []

    def is_configured(self) -> bool:
        return self._configured

    async def get_similar_artists(self, artist: str, limit: int = 10):
        self.calls.append(artist)
        return self._similar.get(artist, [])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lastfm_not_configured_returns_empty(async_db, monkeypatch):
    profile, playlist, _ = await _seed_playlist(async_db)

    service = RecommendationsService(async_db)
    service.lastfm = _StubLastfm(configured=False)

    rows = await service.get_playlist_external_albums(playlist.id, refresh=True)
    assert rows == []

    # No cache writes
    result = await async_db.execute(select(ExternalAlbumCache))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_compute_persists_with_correct_context_and_playlist_id(
    async_db, monkeypatch
):
    profile, playlist, _ = await _seed_playlist(async_db)

    service = RecommendationsService(async_db)
    service.lastfm = _StubLastfm(
        configured=True,
        similar={"Radiohead": [_make_lastfm_similar("Thom Yorke", 0.85)]},
    )

    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.search_artist",
        lambda name: _make_mb_search("Thom Yorke", "mb-thom"),
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.get_artist_releases_recent",
        lambda mb_id, days_back, release_types: [
            _make_mb_release("rg-anima", "ANIMA"),
            _make_mb_release("rg-tomorrows", "Tomorrow's Modern Boxes"),
        ],
    )

    rows = await service.get_playlist_external_albums(playlist.id, refresh=True)
    await async_db.commit()
    assert len(rows) == 2
    assert {r["release_name"] for r in rows} == {"ANIMA", "Tomorrow's Modern Boxes"}

    # All persisted with correct context + playlist
    persisted = (
        await async_db.execute(select(ExternalAlbumCache))
    ).scalars().all()
    assert len(persisted) == 2
    assert all(p.discovery_context == PLAYLIST_REC_CONTEXT for p in persisted)
    assert all(p.source_playlist_id == playlist.id for p in persisted)
    assert all(p.musicbrainz_artist_id == "mb-thom" for p in persisted)
    # match_score from Last.fm propagated
    assert all((p.extra_data or {}).get("match_score") == 0.85 for p in persisted)


@pytest.mark.asyncio
async def test_release_id_uniqueness_per_playlist(async_db, monkeypatch):
    profile_a, pl_a, _ = await _seed_playlist(async_db, name="A")
    pl_b = await insert_test_playlist(async_db, profile_a.id, name="B")
    track_b = await insert_test_track(
        async_db, artist="Portishead", album="Dummy"
    )
    await insert_test_playlist_track(async_db, pl_b.id, track_id=track_b.id)
    await async_db.commit()

    service = RecommendationsService(async_db)
    # Both seed artists return the SAME similar candidate, with the SAME release
    similar = {
        "Radiohead": [_make_lastfm_similar("Thom Yorke", 0.9)],
        "Portishead": [_make_lastfm_similar("Thom Yorke", 0.7)],
    }
    service.lastfm = _StubLastfm(configured=True, similar=similar)

    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.search_artist",
        lambda name: _make_mb_search("Thom Yorke", "mb-thom"),
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.get_artist_releases_recent",
        lambda mb_id, days_back, release_types: [_make_mb_release("rg-anima", "ANIMA")],
    )

    await service.get_playlist_external_albums(pl_a.id, refresh=True)
    await service.get_playlist_external_albums(pl_b.id, refresh=True)
    await async_db.commit()

    rows = (await async_db.execute(select(ExternalAlbumCache))).scalars().all()
    # Same release_id under two different playlists — two rows allowed
    assert len(rows) == 2
    assert {r.source_playlist_id for r in rows} == {pl_a.id, pl_b.id}

    # Re-running for pl_a is idempotent — still 2 total
    await service.get_playlist_external_albums(pl_a.id, refresh=True)
    await async_db.commit()
    rows2 = (await async_db.execute(select(ExternalAlbumCache))).scalars().all()
    assert len(rows2) == 2


@pytest.mark.asyncio
async def test_local_album_match_filter(async_db, monkeypatch):
    profile, playlist, _ = await _seed_playlist(async_db)
    # Seed a track that matches one of the recommended releases
    await insert_test_track(async_db, artist="Thom Yorke", album="ANIMA")
    await async_db.commit()

    service = RecommendationsService(async_db)
    service.lastfm = _StubLastfm(
        configured=True,
        similar={"Radiohead": [_make_lastfm_similar("Thom Yorke", 0.9)]},
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.search_artist",
        lambda name: _make_mb_search("Thom Yorke", "mb-thom"),
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.get_artist_releases_recent",
        lambda mb_id, days_back, release_types: [
            _make_mb_release("rg-anima", "ANIMA"),
            _make_mb_release("rg-other", "Other Album"),
        ],
    )

    rows = await service.get_playlist_external_albums(playlist.id, refresh=True)
    await async_db.commit()

    # Default read excludes local-album-match rows
    assert {r["release_name"] for r in rows} == {"Other Album"}

    # But the row IS persisted with local_album_match=True
    persisted = (
        await async_db.execute(
            select(ExternalAlbumCache).where(
                ExternalAlbumCache.release_name == "ANIMA"
            )
        )
    ).scalar_one()
    assert persisted.local_album_match is True


@pytest.mark.asyncio
async def test_dismiss_preserved_across_recompute(async_db, monkeypatch):
    profile, playlist, _ = await _seed_playlist(async_db)

    service = RecommendationsService(async_db)
    service.lastfm = _StubLastfm(
        configured=True,
        similar={"Radiohead": [_make_lastfm_similar("Thom Yorke", 0.9)]},
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.search_artist",
        lambda name: _make_mb_search("Thom Yorke", "mb-thom"),
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.get_artist_releases_recent",
        lambda mb_id, days_back, release_types: [_make_mb_release("rg-anima", "ANIMA")],
    )

    await service.get_playlist_external_albums(playlist.id, refresh=True)
    row = (await async_db.execute(select(ExternalAlbumCache))).scalar_one()

    row.dismissed = True
    row.dismissed_by_profile_id = profile.id
    await async_db.commit()

    # Refresh again
    rows = await service.get_playlist_external_albums(playlist.id, refresh=True)
    await async_db.commit()
    # The dismissed row stays out of the listing
    assert rows == []

    # And on the DB side, the row still exists with dismissed=True (not duplicated)
    persisted = (await async_db.execute(select(ExternalAlbumCache))).scalars().all()
    assert len(persisted) == 1
    assert persisted[0].dismissed is True


@pytest.mark.asyncio
async def test_source_playlist_scoping(async_db, monkeypatch):
    profile, pl_a, _ = await _seed_playlist(async_db, name="A")
    pl_b = await insert_test_playlist(async_db, profile.id, name="B")
    track_b = await insert_test_track(async_db, artist="Portishead", album="Dummy")
    await insert_test_playlist_track(async_db, pl_b.id, track_id=track_b.id)
    await async_db.commit()

    service = RecommendationsService(async_db)
    service.lastfm = _StubLastfm(
        configured=True,
        similar={
            "Radiohead": [_make_lastfm_similar("Thom Yorke", 0.9)],
            "Portishead": [_make_lastfm_similar("Beth Gibbons", 0.95)],
        },
    )

    artist_to_mb = {"Thom Yorke": "mb-thom", "Beth Gibbons": "mb-beth"}
    artist_to_release = {
        "mb-thom": [_make_mb_release("rg-anima", "ANIMA")],
        "mb-beth": [_make_mb_release("rg-lives-outgrown", "Lives Outgrown")],
    }
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.search_artist",
        lambda name: _make_mb_search(name, artist_to_mb[name]),
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.get_artist_releases_recent",
        lambda mb_id, days_back, release_types: artist_to_release[mb_id],
    )

    rows_a = await service.get_playlist_external_albums(pl_a.id, refresh=True)
    rows_b = await service.get_playlist_external_albums(pl_b.id, refresh=True)
    await async_db.commit()

    assert {r["release_name"] for r in rows_a} == {"ANIMA"}
    assert {r["release_name"] for r in rows_b} == {"Lives Outgrown"}


@pytest.mark.asyncio
async def test_ttl_skips_recompute(async_db, monkeypatch):
    profile, playlist, _ = await _seed_playlist(async_db)

    service = RecommendationsService(async_db)
    stub = _StubLastfm(
        configured=True,
        similar={"Radiohead": [_make_lastfm_similar("Thom Yorke", 0.9)]},
    )
    service.lastfm = stub
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.search_artist",
        lambda name: _make_mb_search("Thom Yorke", "mb-thom"),
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.get_artist_releases_recent",
        lambda mb_id, days_back, release_types: [_make_mb_release("rg-anima", "ANIMA")],
    )

    await service.get_playlist_external_albums(playlist.id, refresh=True)
    await async_db.commit()
    assert stub.calls == ["Radiohead"]

    # Second call within TTL → no Last.fm call
    await service.get_playlist_external_albums(playlist.id, refresh=False)
    assert stub.calls == ["Radiohead"]

    # refresh=True overrides TTL
    await service.get_playlist_external_albums(playlist.id, refresh=True)
    assert stub.calls == ["Radiohead", "Radiohead"]


@pytest.mark.asyncio
async def test_artist_check_cache_reuse(async_db, monkeypatch):
    profile, playlist, _ = await _seed_playlist(async_db)
    # Pre-warm ArtistCheckCache as if discovered by #3 task
    async_db.add(
        ArtistCheckCache(
            artist_name_normalized="thom yorke",
            musicbrainz_artist_id="mb-thom",
            last_checked_at=utcnow(),
        )
    )
    await async_db.commit()

    service = RecommendationsService(async_db)
    service.lastfm = _StubLastfm(
        configured=True,
        similar={"Radiohead": [_make_lastfm_similar("Thom Yorke", 0.9)]},
    )

    search_calls: list[str] = []

    def fake_search(name: str):
        search_calls.append(name)
        return _make_mb_search(name, "mb-from-search-DO-NOT-USE")

    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.search_artist", fake_search
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.get_artist_releases_recent",
        lambda mb_id, days_back, release_types: [_make_mb_release("rg-anima", "ANIMA")],
    )

    await service.get_playlist_external_albums(playlist.id, refresh=True)
    await async_db.commit()

    # search_artist NOT called because cache had the MB id
    assert search_calls == []

    persisted = (
        await async_db.execute(select(ExternalAlbumCache))
    ).scalars().all()
    assert len(persisted) == 1
    # Used the cached MB id, not the would-be search result
    assert persisted[0].musicbrainz_artist_id == "mb-thom"


@pytest.mark.asyncio
async def test_artist_check_cache_write_for_external_artist(async_db, monkeypatch):
    profile, playlist, _ = await _seed_playlist(async_db)

    service = RecommendationsService(async_db)
    service.lastfm = _StubLastfm(
        configured=True,
        similar={"Radiohead": [_make_lastfm_similar("Thom Yorke", 0.9)]},
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.search_artist",
        lambda name: _make_mb_search("Thom Yorke", "mb-thom"),
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.get_artist_releases_recent",
        lambda mb_id, days_back, release_types: [_make_mb_release("rg-anima", "ANIMA")],
    )

    await service.get_playlist_external_albums(playlist.id, refresh=True)
    await async_db.commit()

    cache_row = (
        await async_db.execute(
            select(ArtistCheckCache).where(
                ArtistCheckCache.artist_name_normalized == "thom yorke"
            )
        )
    ).scalar_one()
    assert cache_row.musicbrainz_artist_id == "mb-thom"
