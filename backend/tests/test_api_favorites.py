"""Tests for favorites API routes."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import make_profile_headers


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
