"""Tests for organizer API routes."""

from fastapi.testclient import TestClient

from tests.conftest import make_profile_headers


class TestOrganizerAPI:
    """Tests for /api/v1/library/organize endpoints."""

    def test_list_templates(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        response = client.get("/api/v1/library/organize/templates", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "templates" in data
        assert isinstance(data["templates"], list)

    def test_preview_requires_body(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        # Preview with no body should fail validation
        response = client.post("/api/v1/library/organize/preview", headers=headers)
        assert response.status_code in (400, 422)
