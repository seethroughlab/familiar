"""Route-level tests for /api/v1/new-releases."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.models import ExternalAlbumCache
from app.services.new_releases import DISCOVERY_CONTEXT
from tests.conftest import make_profile_headers


def _seed_release(
    async_db,
    *,
    release_id: str,
    artist: str = "Test Artist",
    name: str = "Test Release",
    dismissed: bool = False,
    local_album_match: bool = False,
    discovery_context: str = DISCOVERY_CONTEXT,
) -> ExternalAlbumCache:
    rel = ExternalAlbumCache(
        release_id=release_id,
        discovery_context=discovery_context,
        artist_name=artist,
        artist_name_normalized=artist.lower(),
        release_name=name,
        dismissed=dismissed,
        local_album_match=local_album_match,
    )
    async_db.add(rel)
    return rel


class TestListNewReleases:
    @pytest.mark.asyncio
    async def test_empty(self, async_db, client: TestClient):
        """An empty cache reports *why* it is empty, not just that it is.

        `as_of: None` means discovery has never written a release — which is not
        the same as "there is nothing new", though both render as an empty list.
        Telling them apart is ADR-0099 points 7 and 8, and the reason a five-day
        gap went unnoticed for five days.
        """
        await async_db.commit()
        resp = client.get("/api/v1/new-releases")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {
            "releases": [],
            "total": 0,
            "limit": 50,
            "offset": 0,
            "as_of": None,
            "age_hours": None,
        }

    @pytest.mark.asyncio
    async def test_reports_when_discovery_last_found_something(
        self, async_db, client: TestClient
    ):
        """A populated cache carries its own age, so a client can say how old it is."""
        _seed_release(async_db, release_id="rg-freshness", artist="Tycho")
        await async_db.commit()

        data = client.get("/api/v1/new-releases").json()

        assert data["as_of"] is not None
        assert data["age_hours"] is not None
        assert data["age_hours"] < 24

    @pytest.mark.asyncio
    async def test_excludes_dismissed_and_owned_by_default(
        self, async_db, client: TestClient
    ):
        _seed_release(async_db, release_id="rg-vis", name="Visible")
        _seed_release(async_db, release_id="rg-dis", name="Dismissed", dismissed=True)
        _seed_release(
            async_db, release_id="rg-own", name="Owned", local_album_match=True
        )
        # Pass-2 record (different context) should never appear here.
        _seed_release(
            async_db,
            release_id="rg-pl",
            name="From Playlist",
            discovery_context="playlist_recommendation",
        )
        await async_db.commit()

        resp = client.get("/api/v1/new-releases")
        assert resp.status_code == 200
        names = [r["release_name"] for r in resp.json()["releases"]]
        assert names == ["Visible"]

    @pytest.mark.asyncio
    async def test_include_flags(self, async_db, client: TestClient):
        _seed_release(async_db, release_id="rg-vis2", name="Visible")
        _seed_release(async_db, release_id="rg-dis2", name="Dismissed", dismissed=True)
        _seed_release(
            async_db, release_id="rg-own2", name="Owned", local_album_match=True
        )
        await async_db.commit()

        resp = client.get(
            "/api/v1/new-releases", params={"include_dismissed": "true"}
        )
        assert resp.status_code == 200
        names = {r["release_name"] for r in resp.json()["releases"]}
        assert {"Visible", "Dismissed"} <= names

        resp = client.get("/api/v1/new-releases", params={"include_owned": "true"})
        assert resp.status_code == 200
        names = {r["release_name"] for r in resp.json()["releases"]}
        assert {"Visible", "Owned"} <= names

    @pytest.mark.asyncio
    async def test_release_payload_includes_purchase_links_and_artwork_fallback(
        self, async_db, client: TestClient
    ):
        _seed_release(async_db, release_id="rg-payload", artist="Foo", name="Bar")
        await async_db.commit()

        resp = client.get("/api/v1/new-releases")
        assert resp.status_code == 200
        rel = resp.json()["releases"][0]
        assert rel["release_name"] == "Bar"
        assert rel["artist_name"] == "Foo"
        # Fallback artwork URL when no explicit artwork is stored
        assert rel["artwork_url"].endswith("/release-group/rg-payload/front-250")
        assert isinstance(rel["purchase_links"], dict)
        assert rel["local_album_match"] is False
        assert rel["dismissed"] is False


class TestStatus:
    def test_requires_profile(self, client: TestClient):
        resp = client.get("/api/v1/new-releases/status")
        assert resp.status_code in (400, 401, 422)

    def test_returns_expected_keys(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        resp = client.get("/api/v1/new-releases/status", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        for key in (
            "total_releases_found",
            "new_releases_available",
            "artists_in_library",
            "artists_checked",
            "last_check_at",
            "progress",
            "rotation",
        ):
            assert key in data
        for key in (
            "total_artists_in_rotation",
            "checked_this_week",
            "remaining_this_week",
            "estimated_days_to_complete",
        ):
            assert key in data["rotation"]


class TestDismiss:
    def test_dismiss_unknown_returns_404(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        resp = client.post(
            f"/api/v1/new-releases/{uuid4()}/dismiss", headers=headers
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_dismiss_hides_from_default_list(
        self, async_db, client: TestClient, test_profile: dict
    ):
        rel = _seed_release(async_db, release_id="rg-to-dismiss", name="GoneSoon")
        await async_db.commit()

        headers = make_profile_headers(test_profile)
        resp = client.post(
            f"/api/v1/new-releases/{rel.id}/dismiss", headers=headers
        )
        assert resp.status_code == 200

        # No longer in default listing
        listing = client.get("/api/v1/new-releases").json()
        assert rel.release_name not in {r["release_name"] for r in listing["releases"]}


class TestTriggerCheck:
    def test_check_starts_background_task(
        self, monkeypatch, client: TestClient, test_profile: dict
    ):
        from app.services.background import manager as bg_manager

        called: dict[str, object] = {}

        async def fake_run_new_releases_check(self, **kwargs):
            called.update(kwargs)
            return {"status": "success"}

        monkeypatch.setattr(
            bg_manager.BackgroundManager,
            "run_new_releases_check",
            fake_run_new_releases_check,
            raising=True,
        )

        headers = make_profile_headers(test_profile)
        resp = client.post(
            "/api/v1/new-releases/check?days_back=30&force=true", headers=headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

    def test_batch_check_starts_background_task(
        self, monkeypatch, client: TestClient, test_profile: dict
    ):
        from app.services.background import manager as bg_manager

        async def fake_prioritized(self, **kwargs):
            return {"status": "success"}

        monkeypatch.setattr(
            bg_manager.BackgroundManager,
            "run_prioritized_new_releases_check",
            fake_prioritized,
            raising=True,
        )

        headers = make_profile_headers(test_profile)
        resp = client.post(
            "/api/v1/new-releases/check/batch?batch_size=20",
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "started"
        assert "batch size: 20" in body["message"]
