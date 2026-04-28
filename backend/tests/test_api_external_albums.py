"""Route-level tests for the playlist external-albums GET + generic dismiss."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.models import ExternalAlbumCache
from app.services.new_releases import DISCOVERY_CONTEXT as ARTIST_NEW_RELEASE
from app.services.recommendations import PLAYLIST_REC_CONTEXT
from tests.conftest import make_profile_headers


def _seed_external(
    async_db,
    *,
    release_id: str,
    discovery_context: str,
    source_playlist_id=None,
    artist: str = "Test Artist",
    name: str = "Test Release",
    match_score: float = 0.5,
) -> ExternalAlbumCache:
    rel = ExternalAlbumCache(
        release_id=release_id,
        discovery_context=discovery_context,
        source_playlist_id=source_playlist_id,
        artist_name=artist,
        artist_name_normalized=artist.lower(),
        release_name=name,
        extra_data={"match_score": match_score},
    )
    async_db.add(rel)
    return rel


def _create_playlist(client: TestClient, profile: dict, *, name: str = "Mix") -> dict:
    headers = make_profile_headers(profile)
    resp = client.post(
        "/api/v1/playlists",
        json={"name": name, "description": None},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class _StubLastfmConfigured:
    def is_configured(self) -> bool:
        return True

    async def get_similar_artists(self, artist: str, limit: int = 10):
        return []


class _StubLastfmUnconfigured:
    def is_configured(self) -> bool:
        return False

    async def get_similar_artists(self, artist: str, limit: int = 10):
        return []


def _patch_lastfm_singleton(monkeypatch, configured: bool):
    """Replace the Last.fm singleton used by RecommendationsService."""
    from app.services import lastfm as lastfm_mod
    stub = _StubLastfmConfigured() if configured else _StubLastfmUnconfigured()
    monkeypatch.setattr(lastfm_mod, "_lastfm_service", stub, raising=False)
    monkeypatch.setattr(lastfm_mod, "get_lastfm_service", lambda: stub)


# ---------------------------------------------------------------------------
# GET /playlists/{id}/recommendations/external-albums
# ---------------------------------------------------------------------------


class TestGetExternalAlbums:
    @pytest.mark.asyncio
    async def test_returns_cached_ordered_by_match_score(
        self, async_db, client: TestClient, test_profile: dict, monkeypatch
    ):
        _patch_lastfm_singleton(monkeypatch, configured=True)

        playlist = _create_playlist(client, test_profile)
        from uuid import UUID
        pl_id = UUID(playlist["id"])

        _seed_external(
            async_db,
            release_id="rg-low",
            discovery_context=PLAYLIST_REC_CONTEXT,
            source_playlist_id=pl_id,
            name="Low Match",
            match_score=0.2,
        )
        _seed_external(
            async_db,
            release_id="rg-high",
            discovery_context=PLAYLIST_REC_CONTEXT,
            source_playlist_id=pl_id,
            name="High Match",
            match_score=0.95,
        )
        await async_db.commit()

        headers = make_profile_headers(test_profile)
        resp = client.get(
            f"/api/v1/playlists/{playlist['id']}/recommendations/external-albums?limit=10",
            headers=headers,
        )
        assert resp.status_code == 200
        names = [a["release_name"] for a in resp.json()["albums"]]
        assert names == ["High Match", "Low Match"]

    def test_works_for_manual_playlist(
        self, client: TestClient, test_profile: dict, monkeypatch
    ):
        _patch_lastfm_singleton(monkeypatch, configured=True)

        playlist = _create_playlist(client, test_profile, name="Manual mix")
        # Manual playlist (is_auto_generated=False by default)

        headers = make_profile_headers(test_profile)
        resp = client.get(
            f"/api/v1/playlists/{playlist['id']}/recommendations/external-albums",
            headers=headers,
        )
        # Empty cache + Last.fm stub returns no similar — but no AI gate rejection
        assert resp.status_code == 200
        assert resp.json() == {"albums": []}

    def test_returns_404_for_other_profile(
        self, client: TestClient, test_profile: dict
    ):
        playlist = _create_playlist(client, test_profile)

        # Make a separate profile
        other = client.post(
            "/api/v1/profiles", json={"name": "Other"}
        ).json()
        other_headers = make_profile_headers(other)

        resp = client.get(
            f"/api/v1/playlists/{playlist['id']}/recommendations/external-albums",
            headers=other_headers,
        )
        assert resp.status_code in (404, 401)

    def test_lastfm_unconfigured_returns_empty(
        self, client: TestClient, test_profile: dict, monkeypatch
    ):
        _patch_lastfm_singleton(monkeypatch, configured=False)
        playlist = _create_playlist(client, test_profile)

        headers = make_profile_headers(test_profile)
        resp = client.get(
            f"/api/v1/playlists/{playlist['id']}/recommendations/external-albums?refresh=true",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json() == {"albums": []}


# ---------------------------------------------------------------------------
# POST /external-albums/{id}/dismiss
# ---------------------------------------------------------------------------


class TestDismissExternalAlbum:
    def test_unknown_returns_404(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        resp = client.post(
            f"/api/v1/external-albums/{uuid4()}/dismiss", headers=headers
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_dismiss_playlist_recommendation_row(
        self, async_db, client: TestClient, test_profile: dict, monkeypatch
    ):
        _patch_lastfm_singleton(monkeypatch, configured=True)
        playlist = _create_playlist(client, test_profile)
        from uuid import UUID
        pl_id = UUID(playlist["id"])

        rel = _seed_external(
            async_db,
            release_id="rg-pl-dismiss",
            discovery_context=PLAYLIST_REC_CONTEXT,
            source_playlist_id=pl_id,
            name="DismissMe",
        )
        await async_db.commit()

        headers = make_profile_headers(test_profile)
        resp = client.post(
            f"/api/v1/external-albums/{rel.id}/dismiss", headers=headers
        )
        assert resp.status_code == 200

        # No longer in default playlist listing
        resp2 = client.get(
            f"/api/v1/playlists/{playlist['id']}/recommendations/external-albums",
            headers=headers,
        )
        names = {a["release_name"] for a in resp2.json()["albums"]}
        assert "DismissMe" not in names

    @pytest.mark.asyncio
    async def test_dismiss_works_on_artist_new_release_row(
        self, async_db, client: TestClient, test_profile: dict
    ):
        # Same generic endpoint should work for #3 rows too
        rel = _seed_external(
            async_db,
            release_id="rg-anr-dismiss",
            discovery_context=ARTIST_NEW_RELEASE,
            source_playlist_id=None,
            name="NewReleaseToDismiss",
        )
        await async_db.commit()

        headers = make_profile_headers(test_profile)
        resp = client.post(
            f"/api/v1/external-albums/{rel.id}/dismiss", headers=headers
        )
        assert resp.status_code == 200

        # And the legacy /new-releases listing now hides it
        listing = client.get("/api/v1/new-releases").json()
        assert "NewReleaseToDismiss" not in {
            r["release_name"] for r in listing["releases"]
        }


# ---------------------------------------------------------------------------
# Backwards compat
# ---------------------------------------------------------------------------


class TestLegacyNewReleasesDismissStillWorks:
    @pytest.mark.asyncio
    async def test_legacy_endpoint_dismisses_artist_new_release_row(
        self, async_db, client: TestClient, test_profile: dict
    ):
        rel = _seed_external(
            async_db,
            release_id="rg-legacy",
            discovery_context=ARTIST_NEW_RELEASE,
            source_playlist_id=None,
            name="LegacyDismiss",
        )
        await async_db.commit()

        headers = make_profile_headers(test_profile)
        resp = client.post(
            f"/api/v1/new-releases/{rel.id}/dismiss", headers=headers
        )
        assert resp.status_code == 200

        listing = client.get("/api/v1/new-releases").json()
        assert "LegacyDismiss" not in {
            r["release_name"] for r in listing["releases"]
        }
