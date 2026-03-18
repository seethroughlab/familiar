"""
Health check and basic API tests for the Familiar API.
"""

from uuid import uuid4

from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient) -> None:
    """Test the health endpoint returns healthy status."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_api_root(client: TestClient) -> None:
    """Test the root endpoint returns a response."""
    response = client.get("/")
    # Could be 200 with API info (dev) or serve index.html (prod)
    assert response.status_code == 200


def test_openapi_schema(client: TestClient) -> None:
    """Test that OpenAPI schema is accessible."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert data["info"]["title"] == "Familiar"
    assert "paths" in data


def test_docs_endpoint(client: TestClient) -> None:
    """Test that Swagger docs are accessible."""
    response = client.get("/docs")
    assert response.status_code == 200


def test_invalid_profile_id_format(client: TestClient) -> None:
    """Test that invalid profile ID format returns 400."""
    response = client.get(
        "/api/v1/playlists",
        headers={"X-Profile-ID": "not-a-uuid"},
    )
    assert response.status_code == 400
    assert "Invalid profile ID format" in response.json()["message"]


def test_nonexistent_profile_id(client: TestClient) -> None:
    """Test that non-existent profile ID returns 401."""
    response = client.get(
        "/api/v1/playlists",
        headers={"X-Profile-ID": str(uuid4())},
    )
    assert response.status_code == 401
    assert "Invalid profile ID" in response.json()["message"]
