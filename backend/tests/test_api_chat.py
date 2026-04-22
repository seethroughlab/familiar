"""
Tests for the chat API endpoints.

These tests focus on input validation and rate limiting.
"""

from fastapi.testclient import TestClient

from tests.conftest import make_profile_headers


def test_chat_validation_empty_message(client: TestClient, test_profile: dict) -> None:
    """Test that empty message is rejected."""
    response = client.post(
        "/api/v1/chat",
        json={"message": ""},
        headers=make_profile_headers(test_profile),
    )
    assert response.status_code == 422
    assert "message" in response.text.lower()


def test_chat_validation_whitespace_message(client: TestClient, test_profile: dict) -> None:
    """Test that whitespace-only message is rejected."""
    response = client.post(
        "/api/v1/chat",
        json={"message": "   "},
        headers=make_profile_headers(test_profile),
    )
    assert response.status_code == 422
    assert "whitespace" in response.text.lower() or "empty" in response.text.lower()


def test_chat_validation_message_too_long(client: TestClient, test_profile: dict) -> None:
    """Test that message exceeding max length is rejected."""
    # Max is 10,000 characters
    long_message = "x" * 10001
    response = client.post(
        "/api/v1/chat",
        json={"message": long_message},
        headers=make_profile_headers(test_profile),
    )
    assert response.status_code == 422


def test_chat_validation_invalid_role(client: TestClient, test_profile: dict) -> None:
    """Test that invalid role in history is rejected."""
    response = client.post(
        "/api/v1/chat",
        json={
            "message": "Hello",
            "history": [{"role": "system", "content": "test"}],
        },
        headers=make_profile_headers(test_profile),
    )
    assert response.status_code == 422
    assert "role" in response.text.lower()


def test_chat_validation_history_content_too_long(client: TestClient, test_profile: dict) -> None:
    """Test that history message content exceeding max length is rejected."""
    # Max is 50,000 characters per history message
    long_content = "x" * 50001
    response = client.post(
        "/api/v1/chat",
        json={
            "message": "Hello",
            "history": [{"role": "user", "content": long_content}],
        },
        headers=make_profile_headers(test_profile),
    )
    assert response.status_code == 422


def test_chat_validation_too_many_history_messages(client: TestClient, test_profile: dict) -> None:
    """Test that too many history messages is rejected."""
    # Max is 100 messages
    history = [{"role": "user", "content": "test"} for _ in range(101)]
    response = client.post(
        "/api/v1/chat",
        json={"message": "Hello", "history": history},
        headers=make_profile_headers(test_profile),
    )
    assert response.status_code == 422


def test_chat_valid_request_format(client: TestClient, test_profile: dict) -> None:
    """Test that a valid chat request format is accepted.

    Note: This test doesn't verify the LLM response, just that the request
    format is valid and reaches the endpoint.
    """
    response = client.post(
        "/api/v1/chat",
        json={
            "message": "Hello, play something",
            "history": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello! How can I help?"},
            ],
        },
        headers=make_profile_headers(test_profile),
    )
    # Should either work (200) or fail because LLM not configured (503)
    # But should NOT be a validation error (422)
    assert response.status_code in [200, 503]


def test_chat_status_endpoint(client: TestClient) -> None:
    """Test the chat status endpoint."""
    response = client.get("/api/v1/chat/status")
    assert response.status_code == 200
    data = response.json()
    assert "configured" in data
    assert "provider" in data
    assert isinstance(data["configured"], bool)


def test_chat_status_reflects_selected_provider(client: TestClient) -> None:
    """Trap 2 regression: selecting openai without openai credentials must
    report configured=False even if ANTHROPIC_API_KEY is set.

    We exercise the service helpers directly so this test doesn't depend on
    how the TestClient wires settings storage.
    """
    import tempfile
    from pathlib import Path
    from unittest.mock import patch

    from app.services.app_settings import AppSettingsService

    with tempfile.TemporaryDirectory() as tmpdir:
        svc = AppSettingsService(settings_path=Path(tmpdir) / "settings.json")
        # Select openai but only set anthropic key.
        svc.update(llm_provider="openai", anthropic_api_key="sk-ant-xxx")

        with patch(
            "app.api.routes.chat.get_app_settings_service", return_value=svc
        ):
            response = client.get("/api/v1/chat/status")

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "openai"
    assert data["configured"] is False
