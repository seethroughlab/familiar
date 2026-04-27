"""Route-level tests for /library/discover/external-albums."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.models import ExternalAlbumCache
from app.services.new_releases import DISCOVERY_CONTEXT as ARTIST_NEW_RELEASE
from app.services.recommendations import LISTENING_PROFILE_CONTEXT
from tests.conftest import make_profile_headers


def _seed(async_db, **kwargs) -> ExternalAlbumCache:
    rel = ExternalAlbumCache(**kwargs)
    async_db.add(rel)
    return rel


class _StubLastfmConfigured:
    def is_configured(self) -> bool:
        return True

    async def get_similar_artists(self, artist: str, limit: int = 10):
        return []


def _patch_lastfm(monkeypatch):
    from app.services import lastfm as lastfm_mod
    stub = _StubLastfmConfigured()
    monkeypatch.setattr(lastfm_mod, "_lastfm_service", stub, raising=False)
    monkeypatch.setattr(lastfm_mod, "get_lastfm_service", lambda: stub)


class TestListeningProfileGet:
    def test_requires_profile(self, client: TestClient):
        resp = client.get("/api/v1/library/discover/external-albums")
        assert resp.status_code in (400, 401, 422)

    @pytest.mark.asyncio
    async def test_returns_cached_listening_profile_rows(
        self, async_db, client: TestClient, test_profile: dict, monkeypatch
    ):
        _patch_lastfm(monkeypatch)

        # Seed listening-profile rows; #3 rows must NOT appear in this listing.
        _seed(
            async_db,
            release_id="rg-lp-A",
            discovery_context=LISTENING_PROFILE_CONTEXT,
            source_playlist_id=None,
            artist_name="Foo",
            artist_name_normalized="foo",
            release_name="Listening A",
            extra_data={"match_score": 0.9},
        )
        _seed(
            async_db,
            release_id="rg-lp-B",
            discovery_context=LISTENING_PROFILE_CONTEXT,
            source_playlist_id=None,
            artist_name="Bar",
            artist_name_normalized="bar",
            release_name="Listening B",
            extra_data={"match_score": 0.5},
        )
        # Co-existing #3 row with the same release_id as listening-profile A
        # (allowed by partial unique indexes; should NOT appear here).
        _seed(
            async_db,
            release_id="rg-lp-A",
            discovery_context=ARTIST_NEW_RELEASE,
            source_playlist_id=None,
            artist_name="Foo",
            artist_name_normalized="foo",
            release_name="Listening A (as new release)",
        )
        await async_db.commit()

        headers = make_profile_headers(test_profile)
        resp = client.get(
            "/api/v1/library/discover/external-albums?limit=10", headers=headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        names = [a["release_name"] for a in body["albums"]]
        # Highest match_score first; #3 row is filtered out
        assert names == ["Listening A", "Listening B"]

    def test_lastfm_unconfigured_returns_empty(
        self, client: TestClient, test_profile: dict, monkeypatch
    ):
        from app.services import lastfm as lastfm_mod

        class StubUnconfigured:
            def is_configured(self) -> bool:
                return False

            async def get_similar_artists(self, *a, **kw):
                return []

        stub = StubUnconfigured()
        monkeypatch.setattr(lastfm_mod, "_lastfm_service", stub, raising=False)
        monkeypatch.setattr(lastfm_mod, "get_lastfm_service", lambda: stub)

        headers = make_profile_headers(test_profile)
        resp = client.get(
            "/api/v1/library/discover/external-albums?refresh=true",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json() == {"albums": []}


class TestDismissViaGenericEndpoint:
    @pytest.mark.asyncio
    async def test_dismiss_listening_profile_row(
        self, async_db, client: TestClient, test_profile: dict, monkeypatch
    ):
        _patch_lastfm(monkeypatch)

        rel = _seed(
            async_db,
            release_id="rg-lp-dismiss",
            discovery_context=LISTENING_PROFILE_CONTEXT,
            source_playlist_id=None,
            artist_name="Foo",
            artist_name_normalized="foo",
            release_name="DismissMe",
        )
        await async_db.commit()

        headers = make_profile_headers(test_profile)
        resp = client.post(
            f"/api/v1/external-albums/{rel.id}/dismiss", headers=headers
        )
        assert resp.status_code == 200

        listing = client.get(
            "/api/v1/library/discover/external-albums", headers=headers
        ).json()
        assert "DismissMe" not in {a["release_name"] for a in listing["albums"]}

    def test_dismiss_unknown_returns_404(
        self, client: TestClient, test_profile: dict
    ):
        headers = make_profile_headers(test_profile)
        resp = client.post(
            f"/api/v1/external-albums/{uuid4()}/dismiss", headers=headers
        )
        assert resp.status_code == 404


class TestUUIDImportSanity:
    def test_uuid_imports(self):
        UUID("00000000-0000-0000-0000-000000000000")
