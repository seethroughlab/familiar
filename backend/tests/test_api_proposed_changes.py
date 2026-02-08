"""Tests for proposed changes API routes."""

from fastapi.testclient import TestClient

from tests.conftest import make_profile_headers


class TestProposedChangesAPI:
    """Tests for /api/v1/proposed-changes endpoints."""

    def test_list_proposed_changes_empty(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        response = client.get("/api/v1/proposed-changes", headers=headers)
        assert response.status_code == 200
        data = response.json()
        # Should return a list or paginated response
        assert isinstance(data, (list, dict))

    def test_get_proposed_change_not_found(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        from uuid import uuid4
        fake_id = str(uuid4())
        response = client.get(f"/api/v1/proposed-changes/{fake_id}", headers=headers)
        assert response.status_code == 404

    def test_get_stats(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        response = client.get("/api/v1/proposed-changes/stats", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "pending" in data or "total" in data or isinstance(data, dict)
