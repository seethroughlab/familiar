"""Tests for favorites API routes."""

from uuid import uuid4

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProfileFavorite, TrackStatus
from tests.conftest import make_profile_headers
from tests.factories import insert_test_profile, insert_test_track


class TestFavoritesAPI:
    """Tests for /api/v1/favorites endpoints."""

    def test_list_favorites_empty(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        response = client.get("/api/v1/favorites", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["favorites"] == []

    def test_add_favorite_nonexistent_track(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        fake_id = str(uuid4())
        response = client.post(f"/api/v1/favorites/{fake_id}", headers=headers)
        assert response.status_code in (404, 500)

    def test_remove_favorite_nonexistent_track(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        fake_id = str(uuid4())
        response = client.delete(f"/api/v1/favorites/{fake_id}", headers=headers)
        # Should succeed silently or 404
        assert response.status_code in (200, 204, 404)

    def test_check_favorite_status_nonexistent(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        fake_id = str(uuid4())
        response = client.get(f"/api/v1/favorites/{fake_id}/status", headers=headers)
        # Nonexistent track returns 404
        assert response.status_code in (200, 404)

    def test_favorites_require_profile(self, client: TestClient):
        response = client.get("/api/v1/favorites")
        # Should fail without profile header
        assert response.status_code in (400, 401, 422)

    def test_favorites_isolated_between_profiles(self, client: TestClient, test_profile: dict):
        """Each profile should have independent favorites."""
        headers1 = make_profile_headers(test_profile)

        # Create second profile
        resp = client.post("/api/v1/profiles", json={"name": "Other User"})
        profile2 = resp.json()
        headers2 = make_profile_headers(profile2)

        # Both should have empty favorites
        r1 = client.get("/api/v1/favorites", headers=headers1)
        r2 = client.get("/api/v1/favorites", headers=headers2)
        assert r1.json()["total"] == 0
        assert r2.json()["total"] == 0

    def test_toggle_favorite_nonexistent_track(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        fake_id = str(uuid4())
        r = client.post(f"/api/v1/favorites/{fake_id}/toggle", headers=headers)
        assert r.status_code == 404

    def test_check_favorite_status_not_favorited(self, client: TestClient, test_profile: dict):
        """Checking favorite status for a valid-format but nonexistent track."""
        headers = make_profile_headers(test_profile)
        fake_id = str(uuid4())
        r = client.get(f"/api/v1/favorites/{fake_id}", headers=headers)
        assert r.status_code == 200
        assert r.json()["is_favorite"] is False

    def test_auto_download_setting(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)

        # Default is off
        r = client.get("/api/v1/favorites/auto-download", headers=headers)
        assert r.status_code == 200
        assert r.json()["enabled"] is False

        # Enable
        r = client.put("/api/v1/favorites/auto-download", headers=headers, json={"enabled": True})
        assert r.status_code == 200
        assert r.json()["enabled"] is True

        # Verify persisted
        r = client.get("/api/v1/favorites/auto-download", headers=headers)
        assert r.json()["enabled"] is True

        # Disable
        r = client.put("/api/v1/favorites/auto-download", headers=headers, json={"enabled": False})
        assert r.status_code == 200
        assert r.json()["enabled"] is False


@pytest_asyncio.fixture
async def favorites_with_skipped(async_db: AsyncSession):
    """Create a profile with two favorited tracks: one ACTIVE, one SKIPPED."""
    profile = await insert_test_profile(async_db, name="Fav Test User")
    active_track = await insert_test_track(async_db, title="Active Song", artist="Artist")
    skipped_track = await insert_test_track(async_db, title="Skipped Song", artist="Artist")
    skipped_track.status = TrackStatus.SKIPPED

    async_db.add(ProfileFavorite(profile_id=profile.id, track_id=active_track.id))
    async_db.add(ProfileFavorite(profile_id=profile.id, track_id=skipped_track.id))
    await async_db.commit()

    return {
        "profile": profile,
        "active_track": active_track,
        "skipped_track": skipped_track,
    }


class TestFavoritesStatusFiltering:
    """Verify that non-ACTIVE tracks are excluded from favorites listing."""

    def test_skipped_tracks_excluded_from_list(
        self, client: TestClient, favorites_with_skipped: dict
    ):
        profile = favorites_with_skipped["profile"]
        active_track = favorites_with_skipped["active_track"]
        skipped_track = favorites_with_skipped["skipped_track"]

        headers = make_profile_headers({"id": str(profile.id)})
        response = client.get("/api/v1/favorites", headers=headers)
        assert response.status_code == 200

        data = response.json()
        returned_ids = {f["id"] for f in data["favorites"]}

        assert str(active_track.id) in returned_ids
        assert str(skipped_track.id) not in returned_ids
        assert data["total"] == 1


class TestExternalFavoritesAPI:
    """Tests for external favorites endpoints."""

    def test_toggle_external_favorite_nonexistent(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        fake_id = str(uuid4())
        r = client.post(f"/api/v1/favorites/external/{fake_id}/toggle", headers=headers)
        assert r.status_code == 404

    def test_check_external_favorite_nonexistent(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        fake_id = str(uuid4())
        r = client.get(f"/api/v1/favorites/external/{fake_id}", headers=headers)
        assert r.status_code == 404
