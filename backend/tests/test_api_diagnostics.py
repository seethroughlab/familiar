"""Tests for diagnostics API routes."""

from fastapi.testclient import TestClient

from tests.conftest import make_profile_headers


class TestDiagnosticsAPI:
    """Tests for /api/v1/diagnostics endpoints."""

    def test_export_diagnostics(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        response = client.get("/api/v1/diagnostics/export", headers=headers)
        assert response.status_code == 200
        data = response.json()
        # Should include system info and health data
        assert "system" in data or "version" in data or "exported_at" in data

    def test_health_check(self, client: TestClient):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
