"""Contract tests: route-specific error shape validation.

Each test triggers a known error path and verifies the response uses the
standard error envelope: {"error": true, "status_code": N, "message": "..."}.
"""

from fastapi.testclient import TestClient

from tests.conftest import assert_error_shape

ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def test_tracks_stream_invalid_track_id_validation_error_shape(client: TestClient) -> None:
    response = client.get("/api/v1/tracks/not-a-uuid/stream")
    assert_error_shape(response, status_code=422)
    assert "track_id" in response.json()["detail"]


def test_artwork_by_hash_invalid_size_error_shape(client: TestClient) -> None:
    response = client.get("/api/v1/artwork/abc123/invalid-size")
    assert_error_shape(response, status_code=400)
    assert "Size must be" in response.json()["message"]


def test_settings_update_validation_error_shape(client: TestClient) -> None:
    response = client.put("/api/v1/settings", json={"external_features_enabled": "not-a-bool"})
    assert_error_shape(response, status_code=422)
    assert "external_features_enabled" in response.json()["detail"]


def test_profiles_get_nonexistent_error_shape(client: TestClient) -> None:
    response = client.get(f"/api/v1/profiles/{ZERO_UUID}")
    assert_error_shape(response, status_code=404)
    assert "Profile not found" in response.json()["message"]


def test_videos_search_invalid_track_id_error_shape(client: TestClient) -> None:
    response = client.get("/api/v1/videos/not-a-uuid/search")
    assert_error_shape(response, status_code=422)
    assert "track_id" in response.json()["detail"]


def test_missing_relocate_nonexistent_path_error_shape(client: TestClient) -> None:
    response = client.post(
        "/api/v1/library/missing/relocate",
        json={"search_path": "/nonexistent/path/that/does/not/exist"},
    )
    assert_error_shape(response, status_code=400)


def test_import_preview_wrong_filetype_error_shape(client: TestClient, test_profile: dict) -> None:
    response = client.post(
        "/api/v1/export-import/import/preview",
        files={"file": ("data.txt", b"hello", "text/plain")},
        headers={"X-Profile-ID": str(test_profile["id"])},
    )
    assert_error_shape(response, status_code=400)
    assert "JSON" in response.json()["message"]


def test_export_import_requires_valid_json_error_shape(client: TestClient, test_profile: dict) -> None:
    response = client.post(
        "/api/v1/export-import/import/preview",
        files={"file": ("data.json", b"not json at all", "application/json")},
        headers={"X-Profile-ID": str(test_profile["id"])},
    )
    assert_error_shape(response, status_code=400)
    assert "not valid JSON" in response.json()["message"]


def test_library_missing_invalid_track_id_error_shape(client: TestClient) -> None:
    response = client.post(
        "/api/v1/library/missing/not-a-uuid/locate",
        json={"new_path": "/some/path"},
    )
    assert_error_shape(response, status_code=400)
    # Route validates path existence before track ID, so we get a path error
    assert "does not exist" in response.json()["message"]


def test_chat_no_api_key_error_shape(client: TestClient) -> None:
    """Chat uses CurrentProfile (optional) — without API key it returns 503."""
    response = client.post("/api/v1/chat", json={"message": "hello"})
    assert_error_shape(response, status_code=503)
    assert "API key" in response.json()["message"] or "not configured" in response.json()["message"]


def test_chat_invalid_profile_header_error_shape(client: TestClient) -> None:
    response = client.post(
        "/api/v1/chat",
        json={"message": "hello"},
        headers={"X-Profile-ID": "not-a-uuid"},
    )
    assert_error_shape(response, status_code=400)
    assert response.json()["message"] == "Invalid profile ID format"


# The SPA fallback only exists in production, where `backend/static/` is created during the Docker
# build. The suite runs without it, so the route below is never registered and FastAPI's own 404
# answers instead — which is exactly why the defect these two guard survived unseen.
#
# They call the handler directly for that reason. Going through `client` would assert the behaviour
# of a route that is not mounted, and pass whatever the handler did.


async def test_spa_fallback_raises_for_unmatched_api_paths() -> None:
    """An unmatched `/api/` path must 404, not 200.

    It used to `return {"detail": "Not found"}`, which FastAPI serialises as an ordinary body with
    **HTTP 200**. Every mistyped or renamed API route therefore answered success-shaped, and a
    generated client (ADR-0007) failed while decoding a 200 rather than handling a typed 404.

    Found through the Apple client's artist pages: `/library/artists/{artist_name}` is path-keyed,
    and the 79 artists whose names contain a slash produced precisely this.
    """
    import pytest

    from app.api.exceptions import NotFoundError
    from app.main import spa_fallback

    for path in (
        "api/v1/nope",
        "api/v1/library/artists/Kruder/Dorfmeister",
        "docs/nope",
        "openapi.json/nope",
        "health/nope",
    ):
        with pytest.raises(NotFoundError) as caught:
            await spa_fallback(path)
        assert caught.value.status_code == 404


async def test_spa_fallback_still_serves_the_app_for_client_routes() -> None:
    """Everything that is not the API is still the single-page app.

    The counterpart to the test above: raising for too much would turn every client-side route into
    a 404 and take the web app down.
    """
    from fastapi.responses import FileResponse

    from app.main import spa_fallback

    for path in ("", "library", "playlists/abc", "settings/audio"):
        assert isinstance(await spa_fallback(path), FileResponse)
