"""
Tests for custom exception handling.
"""

from fastapi.testclient import TestClient

from app.api.exceptions import (
    ConflictError,
    FamiliarError,
    NotFoundError,
    ServiceUnavailableError,
    TrackNotFoundError,
    ValidationError,
)


def test_familiar_error_base_class() -> None:
    """Test base exception class."""
    error = FamiliarError(message="Test error", detail="Extra info")
    assert error.message == "Test error"
    assert error.detail == "Extra info"
    assert error.status_code == 500
    assert str(error) == "Test error"


def test_not_found_error() -> None:
    """Test not found exception."""
    error = NotFoundError()
    assert error.status_code == 404
    assert "not found" in error.message.lower()


def test_track_not_found_error() -> None:
    """Test track not found exception."""
    error = TrackNotFoundError()
    assert error.status_code == 404
    assert "track" in error.message.lower()


def test_validation_error() -> None:
    """Test validation exception."""
    error = ValidationError(detail="Field 'name' is required")
    assert error.status_code == 400
    assert error.detail == "Field 'name' is required"


def test_conflict_error() -> None:
    """Test conflict exception."""
    error = ConflictError()
    assert error.status_code == 409


def test_service_unavailable_error() -> None:
    """Test service unavailable exception."""
    error = ServiceUnavailableError()
    assert error.status_code == 503


def test_exception_extra_fields() -> None:
    """Test that extra fields are stored."""
    error = FamiliarError(
        message="Test",
        detail="Detail",
        track_id="abc123",
        user_id="user456",
    )
    assert error.extra["track_id"] == "abc123"
    assert error.extra["user_id"] == "user456"


def test_track_not_found_api_response(client: TestClient) -> None:
    """Test that non-existent track returns proper 404."""
    response = client.get("/api/v1/tracks/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_invalid_uuid_format(client: TestClient) -> None:
    """Test that invalid UUID format is rejected."""
    response = client.get("/api/v1/tracks/not-a-uuid")
    assert response.status_code == 422


class TestSanitizeLLMErrors:
    """sanitize_error_for_client maps provider SDK errors to user-facing text."""

    def test_anthropic_auth_names_anthropic_when_anthropic_selected(self, monkeypatch):
        import anthropic
        from unittest.mock import MagicMock

        from app.api.exceptions import sanitize_error_for_client

        def fake_svc():
            m = MagicMock()
            m.get_active_provider.return_value = "anthropic"
            return m

        monkeypatch.setattr(
            "app.services.app_settings.get_app_settings_service", fake_svc
        )
        err = anthropic.AuthenticationError(
            message="bad",
            response=MagicMock(status_code=401),
            body={"error": {"message": "bad"}},
        )
        msg = sanitize_error_for_client(err)
        assert "Anthropic" in msg

    def test_openai_auth_names_openai_when_openai_selected(self, monkeypatch):
        import openai
        from unittest.mock import MagicMock

        from app.api.exceptions import sanitize_error_for_client

        def fake_svc():
            m = MagicMock()
            m.get_active_provider.return_value = "openai"
            return m

        monkeypatch.setattr(
            "app.services.app_settings.get_app_settings_service", fake_svc
        )
        err = openai.AuthenticationError(
            message="bad",
            response=MagicMock(status_code=401),
            body={"error": {"message": "bad"}},
        )
        msg = sanitize_error_for_client(err)
        assert "OpenAI" in msg

    def test_openai_rate_limit(self):
        import openai
        from unittest.mock import MagicMock

        from app.api.exceptions import sanitize_error_for_client

        err = openai.RateLimitError(
            message="slow down",
            response=MagicMock(status_code=429),
            body={"error": {"message": "slow down"}},
        )
        assert "Rate limit" in sanitize_error_for_client(err)

    def test_openai_connection_error(self):
        import openai

        from app.api.exceptions import sanitize_error_for_client

        err = openai.APIConnectionError(request=None)  # type: ignore[arg-type]
        msg = sanitize_error_for_client(err)
        assert "connect" in msg.lower() or "connection" in msg.lower()
