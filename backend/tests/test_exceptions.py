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


# `TestSanitizeLLMErrors` lived here and is gone with the provider layer (ADR-0048 step 4). It
# asserted that `anthropic.*` and `openai.*` SDK errors were mapped to user-facing copy naming the
# active provider. Familiar no longer imports either SDK or calls any model, so those branches
# matched types nothing could raise.

