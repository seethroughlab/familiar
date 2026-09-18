"""
Tests for the settings API endpoints.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.services.app_settings import AppSettingsService


@pytest.fixture
def temp_settings_service():
    """Create a temporary settings service for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings_path = Path(tmpdir) / "settings.json"
        service = AppSettingsService(settings_path=settings_path)
        yield service


@pytest.fixture
def mock_settings_service(temp_settings_service):
    """Mock the global settings service with our test service."""
    with patch(
        "app.api.routes.settings.get_app_settings_service",
        return_value=temp_settings_service,
    ):
        yield temp_settings_service


def test_get_settings_default(
    client: TestClient,
    mock_settings_service: AppSettingsService,
) -> None:
    """Test getting default settings."""
    response = client.get("/api/v1/settings")
    assert response.status_code == 200
    data = response.json()

    # Secrets should be None initially
    assert data["lastfm_api_key"] is None

    # Status fields
    assert data["lastfm_configured"] is False


def test_update_settings(
    client: TestClient,
    mock_settings_service: AppSettingsService,
) -> None:
    """Test updating settings."""
    response = client.put(
        "/api/v1/settings",
        json={
            "acoustid_api_key": "acoustid-test123456789",
        },
    )
    assert response.status_code == 200
    data = response.json()

    # Key should be masked in response
    assert data["acoustid_api_key"].startswith("acou")
    assert "•" in data["acoustid_api_key"]


def test_update_lastfm_credentials(
    client: TestClient,
    mock_settings_service: AppSettingsService,
) -> None:
    """Test updating Last.fm credentials."""
    response = client.put(
        "/api/v1/settings",
        json={
            "lastfm_api_key": "test_lastfm_key_12345",
            "lastfm_api_secret": "test_lastfm_secret_67890",
        },
    )
    assert response.status_code == 200
    data = response.json()

    # Should now be configured
    assert data["lastfm_configured"] is True


def test_settings_persist(
    client: TestClient,
    mock_settings_service: AppSettingsService,
) -> None:
    """Test that settings persist across requests."""
    # Update a setting
    client.put(
        "/api/v1/settings",
        json={"acoustid_api_key": "acoustid-persistent-key"},
    )

    # Clear the in-memory cache
    mock_settings_service._settings = None

    # Get settings again - should still have the key
    response = client.get("/api/v1/settings")
    assert response.status_code == 200
    data = response.json()

    # Should still be there (masked)
    assert data["acoustid_api_key"] is not None
    assert data["acoustid_api_key"].startswith("acou")


def test_clear_lastfm_settings(
    client: TestClient,
    mock_settings_service: AppSettingsService,
) -> None:
    """Test clearing Last.fm credentials."""
    # First set credentials
    client.put(
        "/api/v1/settings",
        json={
            "lastfm_api_key": "test_key",
            "lastfm_api_secret": "test_secret",
        },
    )

    # Clear them
    response = client.delete("/api/v1/settings/lastfm")
    assert response.status_code == 200
    assert response.json()["status"] == "cleared"

    # Verify they're gone
    get_response = client.get("/api/v1/settings")
    data = get_response.json()
    assert data["lastfm_configured"] is False


def test_partial_update(
    client: TestClient,
    mock_settings_service: AppSettingsService,
) -> None:
    """Test that partial updates don't overwrite other settings."""
    # Set a setting
    client.put(
        "/api/v1/settings",
        json={
            "acoustid_api_key": "acoustid-key1",
            "community_cache_enabled": True,
        },
    )

    # Update only one setting
    client.put(
        "/api/v1/settings",
        json={"community_cache_enabled": False},
    )

    # Verify both are preserved
    response = client.get("/api/v1/settings")
    data = response.json()

    assert data["acoustid_api_key"] is not None  # Still set
    assert data["community_cache_enabled"] is False  # Updated


class TestSoulseekSettings:
    """ADR-0116: the slskd address is a setting like any outbound integration, key masked."""

    def test_unconfigured_by_default(self, client: TestClient, mock_settings_service) -> None:
        data = client.get("/api/v1/settings").json()
        assert data["soulseek_configured"] is False
        assert data["soulseek_url"] is None

    def test_url_and_key_round_trip_with_the_key_masked(
        self, client: TestClient, mock_settings_service: AppSettingsService
    ) -> None:
        response = client.put(
            "/api/v1/settings",
            json={"soulseek_url": "http://slskd:5030", "soulseek_api_key": "abcdefghijklmnop"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["soulseek_configured"] is True
        assert data["soulseek_url"] == "http://slskd:5030"
        assert data["soulseek_api_key"] == "abcd" + "•" * 8
        assert mock_settings_service.get().soulseek_api_key == "abcdefghijklmnop"

    def test_an_empty_url_clears_it(
        self, client: TestClient, mock_settings_service: AppSettingsService
    ) -> None:
        mock_settings_service.update(soulseek_url="http://slskd:5030")
        data = client.put("/api/v1/settings", json={"soulseek_url": ""}).json()
        assert data["soulseek_configured"] is False

    # The status route receives its operation from the container (ADR-0130 point 3), so a test
    # overrides `get_services` on the real app rather than patching module attributes.

    def test_status_reports_unconfigured_without_probing(self, client: TestClient) -> None:
        from app.api.deps import get_services
        from app.container import Services

        client.app.dependency_overrides[get_services] = Services.unconfigured  # type: ignore[attr-defined]
        try:
            data = client.get("/api/v1/soulseek/status").json()
        finally:
            del client.app.dependency_overrides[get_services]  # type: ignore[attr-defined]
        assert data == {
            "configured": False, "url": None, "reachable": False, "logged_in": False,
            "username": None, "version": None, "shared_files": None, "error": None,
        }

    def test_status_probes_the_configured_address(self, client: TestClient) -> None:
        import httpx

        from app.api.deps import get_services
        from tests.test_soulseek import FakeSlskd, services_for

        services = services_for(httpx.MockTransport(FakeSlskd().handler))
        client.app.dependency_overrides[get_services] = lambda: services  # type: ignore[attr-defined]
        try:
            data = client.get("/api/v1/soulseek/status").json()
        finally:
            del client.app.dependency_overrides[get_services]  # type: ignore[attr-defined]
        assert data["configured"] is True
        assert data["url"] == "http://slskd:5030"
        assert data["logged_in"] is True
        assert data["username"] == "otterbad"
