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
    assert data["anthropic_api_key"] is None

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
            "anthropic_api_key": "sk-ant-test123456789",
        },
    )
    assert response.status_code == 200
    data = response.json()

    # Key should be masked in response
    assert data["anthropic_api_key"].startswith("sk-a")
    assert "•" in data["anthropic_api_key"]


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
        json={"anthropic_api_key": "sk-ant-persistent-key"},
    )

    # Clear the in-memory cache
    mock_settings_service._settings = None

    # Get settings again - should still have the key
    response = client.get("/api/v1/settings")
    assert response.status_code == 200
    data = response.json()

    # Should still be there (masked)
    assert data["anthropic_api_key"] is not None
    assert data["anthropic_api_key"].startswith("sk-a")


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
            "anthropic_api_key": "sk-ant-key1",
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

    assert data["anthropic_api_key"] is not None  # Still set
    assert data["community_cache_enabled"] is False  # Updated


def test_llm_provider_defaults_to_anthropic(
    client: TestClient,
    mock_settings_service: AppSettingsService,
) -> None:
    """When nothing is set, the settings response should report 'anthropic'."""
    response = client.get("/api/v1/settings")
    data = response.json()
    assert data["llm_provider"] == "anthropic"
    assert data["openai_configured"] is False
    assert data["openai_api_key"] is None


def test_llm_provider_round_trip(
    client: TestClient,
    mock_settings_service: AppSettingsService,
) -> None:
    """The openai_* fields should round-trip through PUT/GET (key masked)."""
    response = client.put(
        "/api/v1/settings",
        json={
            "llm_provider": "openai",
            "openai_api_key": "sk-oa-test123456789",
            "openai_base_url": "https://api.groq.com/openai/v1",
            "openai_chat_model": "llama-3.3-70b-versatile",
            "openai_utility_model": "llama-3.1-8b-instant",
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["llm_provider"] == "openai"
    assert data["openai_base_url"] == "https://api.groq.com/openai/v1"
    assert data["openai_chat_model"] == "llama-3.3-70b-versatile"
    assert data["openai_utility_model"] == "llama-3.1-8b-instant"
    # Key must be masked (matches anthropic_api_key convention)
    assert data["openai_api_key"].startswith("sk-o")
    assert "•" in data["openai_api_key"]
    assert data["openai_configured"] is True


def test_openai_configured_requires_model_names(
    client: TestClient,
    mock_settings_service: AppSettingsService,
) -> None:
    """base_url is optional, but model names must be set to count as configured."""
    response = client.put(
        "/api/v1/settings",
        json={
            "llm_provider": "openai",
            "openai_api_key": "sk-oa-test",
            # chat/utility models omitted
        },
    )
    data = response.json()
    assert data["openai_configured"] is False
