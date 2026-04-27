"""Service-level tests for the listening-profile external-albums lane (#2 in Discover)."""

from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import ExternalAlbumCache
from app.services.new_releases import DISCOVERY_CONTEXT as ARTIST_NEW_RELEASE
from app.services.recommendations import (
    LISTENING_PROFILE_CONTEXT,
    RecommendationsService,
)
from tests.factories import (
    insert_test_play_history,
    insert_test_profile,
    insert_test_track,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lastfm_similar(name: str, match: float = 0.9) -> dict[str, Any]:
    return {"name": name, "match": str(match), "url": f"https://last.fm/music/{name}"}


def _mb_search(name: str, mb_id: str, score: int = 95) -> dict[str, Any]:
    return {"name": name, "musicbrainz_artist_id": mb_id, "score": score}


def _mb_release(rg_id: str, title: str) -> dict[str, Any]:
    return {
        "musicbrainz_release_group_id": rg_id,
        "title": title,
        "release_type": "Album",
        "release_date": "2024-06-01",
        "release_date_parsed": "2024-06-01T00:00:00",
        "artwork_url": f"https://coverartarchive.org/release-group/{rg_id}/front-250",
    }


class _StubLastfm:
    def __init__(self, configured: bool, similar: dict[str, list[dict]] | None = None):
        self._configured = configured
        self._similar = similar or {}
        self.calls: list[str] = []

    def is_configured(self) -> bool:
        return self._configured

    async def get_similar_artists(self, artist: str, limit: int = 10):
        self.calls.append(artist)
        return self._similar.get(artist, [])


async def _seed_top_played(async_db) -> tuple:
    profile = await insert_test_profile(async_db)
    # Two artists with different play counts
    track_radio = await insert_test_track(
        async_db, artist="Radiohead", album="OK Computer"
    )
    track_porti = await insert_test_track(
        async_db, artist="Portishead", album="Dummy"
    )
    # Radiohead is the top-played
    await insert_test_play_history(
        async_db, profile.id, track_radio.id, play_count=20
    )
    await insert_test_play_history(
        async_db, profile.id, track_porti.id, play_count=5
    )
    await async_db.commit()
    return profile, track_radio, track_porti


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seeds_from_top_played_artists(async_db, monkeypatch):
    profile, _, _ = await _seed_top_played(async_db)

    service = RecommendationsService(async_db)
    stub = _StubLastfm(
        configured=True,
        similar={"Radiohead": [_lastfm_similar("Thom Yorke", 0.9)]},
    )
    service.lastfm = stub
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.search_artist",
        lambda name: _mb_search("Thom Yorke", "mb-thom"),
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.get_artist_releases_recent",
        lambda mb_id, days_back, release_types: [_mb_release("rg-anima", "ANIMA")],
    )

    rows = await service.get_listening_profile_external_albums(
        profile.id, refresh=True
    )
    await async_db.commit()

    # Top-played artist (Radiohead) was seeded
    assert "Radiohead" in stub.calls
    assert len(rows) == 1
    assert rows[0]["release_name"] == "ANIMA"


@pytest.mark.asyncio
async def test_persists_with_correct_context_and_null_playlist(async_db, monkeypatch):
    profile, _, _ = await _seed_top_played(async_db)

    service = RecommendationsService(async_db)
    service.lastfm = _StubLastfm(
        configured=True,
        similar={"Radiohead": [_lastfm_similar("Thom Yorke", 0.9)]},
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.search_artist",
        lambda name: _mb_search("Thom Yorke", "mb-thom"),
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.get_artist_releases_recent",
        lambda mb_id, days_back, release_types: [_mb_release("rg-anima", "ANIMA")],
    )

    await service.get_listening_profile_external_albums(profile.id, refresh=True)
    await async_db.commit()

    persisted = (
        await async_db.execute(select(ExternalAlbumCache))
    ).scalars().all()
    assert len(persisted) == 1
    assert persisted[0].discovery_context == LISTENING_PROFILE_CONTEXT
    assert persisted[0].source_playlist_id is None


@pytest.mark.asyncio
async def test_release_id_uniqueness_within_listening_profile(async_db, monkeypatch):
    profile, _, _ = await _seed_top_played(async_db)

    service = RecommendationsService(async_db)
    service.lastfm = _StubLastfm(
        configured=True,
        similar={
            "Radiohead": [_lastfm_similar("Thom Yorke", 0.9)],
            "Portishead": [_lastfm_similar("Thom Yorke", 0.7)],
        },
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.search_artist",
        lambda name: _mb_search("Thom Yorke", "mb-thom"),
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.get_artist_releases_recent",
        lambda mb_id, days_back, release_types: [_mb_release("rg-anima", "ANIMA")],
    )

    await service.get_listening_profile_external_albums(profile.id, refresh=True)
    await async_db.commit()
    rows = (await async_db.execute(select(ExternalAlbumCache))).scalars().all()
    assert len(rows) == 1

    # Recompute is idempotent
    await service.get_listening_profile_external_albums(profile.id, refresh=True)
    await async_db.commit()
    rows = (await async_db.execute(select(ExternalAlbumCache))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_does_not_collide_with_artist_new_release_row(async_db, monkeypatch):
    """Same release_id can exist as both a #3 row AND a listening-profile row."""
    profile, _, _ = await _seed_top_played(async_db)

    # Pre-seed a #3 row with the same release_id we're about to recommend
    nr = ExternalAlbumCache(
        release_id="rg-anima",
        discovery_context=ARTIST_NEW_RELEASE,
        artist_name="Thom Yorke",
        artist_name_normalized="thom yorke",
        release_name="ANIMA",
    )
    async_db.add(nr)
    await async_db.commit()

    service = RecommendationsService(async_db)
    service.lastfm = _StubLastfm(
        configured=True,
        similar={"Radiohead": [_lastfm_similar("Thom Yorke", 0.9)]},
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.search_artist",
        lambda name: _mb_search("Thom Yorke", "mb-thom"),
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.get_artist_releases_recent",
        lambda mb_id, days_back, release_types: [_mb_release("rg-anima", "ANIMA")],
    )

    await service.get_listening_profile_external_albums(profile.id, refresh=True)
    await async_db.commit()

    rows = (
        await async_db.execute(
            select(ExternalAlbumCache).where(
                ExternalAlbumCache.release_id == "rg-anima"
            )
        )
    ).scalars().all()
    contexts = {r.discovery_context for r in rows}
    assert contexts == {ARTIST_NEW_RELEASE, LISTENING_PROFILE_CONTEXT}


@pytest.mark.asyncio
async def test_lastfm_not_configured_returns_empty(async_db, monkeypatch):
    profile, _, _ = await _seed_top_played(async_db)

    service = RecommendationsService(async_db)
    service.lastfm = _StubLastfm(configured=False)

    rows = await service.get_listening_profile_external_albums(
        profile.id, refresh=True
    )
    assert rows == []
    persisted = (
        await async_db.execute(select(ExternalAlbumCache))
    ).scalars().all()
    assert persisted == []


@pytest.mark.asyncio
async def test_ttl_skips_recompute(async_db, monkeypatch):
    profile, _, _ = await _seed_top_played(async_db)

    service = RecommendationsService(async_db)
    stub = _StubLastfm(
        configured=True,
        similar={"Radiohead": [_lastfm_similar("Thom Yorke", 0.9)]},
    )
    service.lastfm = stub
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.search_artist",
        lambda name: _mb_search("Thom Yorke", "mb-thom"),
    )
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.get_artist_releases_recent",
        lambda mb_id, days_back, release_types: [_mb_release("rg-anima", "ANIMA")],
    )

    await service.get_listening_profile_external_albums(profile.id, refresh=True)
    await async_db.commit()
    initial_calls = list(stub.calls)

    # Within TTL → no Last.fm hit
    await service.get_listening_profile_external_albums(profile.id, refresh=False)
    assert stub.calls == initial_calls

    # Force refresh → re-hits
    await service.get_listening_profile_external_albums(profile.id, refresh=True)
    assert len(stub.calls) > len(initial_calls)


@pytest.mark.asyncio
async def test_no_play_history_returns_empty(async_db, monkeypatch):
    """Fresh profile with no listening history → no seeds → empty result."""
    profile = await insert_test_profile(async_db)
    await async_db.commit()

    service = RecommendationsService(async_db)
    stub = _StubLastfm(configured=True)
    service.lastfm = stub

    rows = await service.get_listening_profile_external_albums(
        profile.id, refresh=True
    )
    assert rows == []
    # Last.fm shouldn't have been called either (no seeds to query)
    assert stub.calls == []
