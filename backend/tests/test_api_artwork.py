"""Tests for artwork API routes."""

from fastapi.testclient import TestClient

from tests.conftest import make_profile_headers


class TestArtworkAPI:
    """Tests for /api/v1/artwork endpoints."""

    def test_queue_artwork_requires_body(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        response = client.post("/api/v1/artwork/queue", headers=headers)
        assert response.status_code in (400, 422)

    def test_queue_artwork_valid_request(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        response = client.post(
            "/api/v1/artwork/queue",
            json={"artist": "Radiohead", "album": "OK Computer"},
            headers=headers,
        )
        # Should return 202 Accepted or 200
        assert response.status_code in (200, 202)

    def test_get_artwork_status(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        # Status endpoint takes an album_hash path param
        response = client.get(
            "/api/v1/artwork/status/abc123",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "exists" in data or "album_hash" in data
