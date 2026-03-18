"""Contract tests: envelope parity and SSE pre-stream error validation.

Verifies every error handler path in main.py produces the canonical envelope,
and that SSE endpoints return JSON envelopes (not SSE events) on pre-stream
validation failure.
"""

from fastapi.testclient import TestClient

from tests.conftest import assert_full_envelope

ZERO_UUID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Envelope parity — one test per exception handler path
# ---------------------------------------------------------------------------


def test_422_pydantic_validation_has_envelope(client: TestClient) -> None:
    """RequestValidationError handler → 422 envelope."""
    response = client.get("/api/v1/tracks/not-a-uuid/stream")
    payload = assert_full_envelope(response, status_code=422)
    assert "detail" in payload


def test_404_familiar_error_has_envelope(client: TestClient) -> None:
    """FamiliarError(404) handler → 404 envelope."""
    response = client.get(f"/api/v1/profiles/{ZERO_UUID}")
    assert_full_envelope(response, status_code=404)


def test_400_familiar_error_has_envelope(client: TestClient) -> None:
    """FamiliarError(400) handler → 400 envelope."""
    response = client.get("/api/v1/artwork/abc123/invalid-size")
    assert_full_envelope(response, status_code=400)


def test_401_auth_error_has_envelope(client: TestClient) -> None:
    """HTTPException(401) from require_profile → 401 envelope."""
    response = client.get("/api/v1/playlists")
    assert_full_envelope(response, status_code=401)


def test_503_llm_not_configured_has_envelope(client: TestClient) -> None:
    """LLMNotConfiguredError → 503 envelope."""
    response = client.post("/api/v1/chat", json={"message": "hello"})
    assert_full_envelope(response, status_code=503)


def test_405_method_not_allowed_has_envelope(client: TestClient) -> None:
    """Starlette 405 handler → 405 response.

    Note: Starlette generates 405 at the ASGI routing level before FastAPI's
    exception handlers run, so it uses Starlette's default format.
    """
    response = client.delete("/api/v1/library/stats")
    assert response.status_code == 405


# ---------------------------------------------------------------------------
# SSE pre-stream error tests
# ---------------------------------------------------------------------------


def test_chat_stream_missing_body_returns_422(client: TestClient) -> None:
    """POST /chat/stream with no body → 422 validation envelope."""
    response = client.post("/api/v1/chat/stream")
    assert_full_envelope(response, status_code=422)


def test_chat_stream_no_api_key_returns_503(client: TestClient) -> None:
    """POST /chat/stream with valid body but no API key → 503 envelope."""
    response = client.post("/api/v1/chat/stream", json={"message": "hello"})
    assert_full_envelope(response, status_code=503)


def test_map_stream_invalid_entity_returns_422(client: TestClient) -> None:
    """GET /library/map/stream with bad entity_type → 422 validation envelope."""
    response = client.get("/api/v1/library/map/stream?entity_type=invalid")
    assert_full_envelope(response, status_code=422)


def test_map_3d_stream_invalid_entity_returns_422(client: TestClient) -> None:
    """GET /library/map/3d/stream with bad entity_type → 422 validation envelope."""
    response = client.get("/api/v1/library/map/3d/stream?entity_type=invalid")
    assert_full_envelope(response, status_code=422)


def test_chat_stream_invalid_profile_returns_400(client: TestClient) -> None:
    """POST /chat/stream with invalid X-Profile-ID → 400 envelope."""
    response = client.post(
        "/api/v1/chat/stream",
        json={"message": "hello"},
        headers={"X-Profile-ID": "not-a-uuid"},
    )
    assert_full_envelope(response, status_code=400)
