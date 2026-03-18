"""
Tests for the tracks API endpoints.

Note: These tests run against the actual database which may have existing data.
"""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import make_profile_headers


def test_list_tracks_returns_valid_response(client: TestClient) -> None:
    """Test that listing tracks returns a valid paginated response."""
    response = client.get("/api/v1/tracks")
    assert response.status_code == 200
    data = response.json()

    # Verify response structure
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert isinstance(data["items"], list)
    assert data["page"] == 1
    assert data["page_size"] == 50


def test_list_tracks_pagination(client: TestClient) -> None:
    """Test track list pagination works."""
    # Get first page with page_size=2
    response = client.get("/api/v1/tracks?page=1&page_size=2")
    assert response.status_code == 200
    data = response.json()

    assert len(data["items"]) <= 2
    assert data["page"] == 1
    assert data["page_size"] == 2

    # Get second page
    response = client.get("/api/v1/tracks?page=2&page_size=2")
    assert response.status_code == 200
    data = response.json()
    assert data["page"] == 2


def test_list_tracks_search(client: TestClient) -> None:
    """Test searching tracks."""
    response = client.get("/api/v1/tracks?search=test")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data


def test_list_tracks_filter_by_artist(client: TestClient) -> None:
    """Test filtering tracks by artist."""
    response = client.get("/api/v1/tracks?artist=test")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data


def test_list_tracks_filter_by_genre(client: TestClient) -> None:
    """Test filtering tracks by genre."""
    response = client.get("/api/v1/tracks?genre=Rock")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data


def test_list_tracks_filter_by_album(client: TestClient) -> None:
    """Test filtering tracks by album."""
    response = client.get("/api/v1/tracks?album=test")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data


def test_get_track_not_found(client: TestClient) -> None:
    """Test getting a non-existent track returns 404."""
    response = client.get(f"/api/v1/tracks/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["message"] == "Track not found"


def test_record_play_requires_profile(client: TestClient) -> None:
    """Test that recording a play requires a profile."""
    response = client.post(
        f"/api/v1/tracks/{uuid4()}/played",
        json={},
    )
    assert response.status_code == 401


def test_get_play_stats(client: TestClient, test_profile: dict) -> None:
    """Test getting play statistics for a profile."""
    headers = make_profile_headers(test_profile)

    response = client.get("/api/v1/tracks/stats/plays", headers=headers)
    assert response.status_code == 200
    data = response.json()

    assert "total_plays" in data
    assert "unique_tracks" in data
    assert "top_tracks" in data


def test_get_track_if_exists(client: TestClient) -> None:
    """Test getting a track returns proper data if tracks exist."""
    # First get the list to find a track ID
    list_response = client.get("/api/v1/tracks?page_size=1")
    assert list_response.status_code == 200
    items = list_response.json()["items"]

    if items:
        # If there are tracks, test getting one
        track_id = items[0]["id"]
        response = client.get(f"/api/v1/tracks/{track_id}")
        assert response.status_code == 200
        data = response.json()

        # Verify track response structure
        assert "id" in data
        assert "title" in data
        assert "artist" in data
        assert "album" in data
        assert "file_path" in data


def test_record_play_and_stats(client: TestClient, test_profile: dict) -> None:
    """Test recording a play updates statistics."""
    headers = make_profile_headers(test_profile)

    # Get initial stats
    initial_stats = client.get("/api/v1/tracks/stats/plays", headers=headers)
    assert initial_stats.status_code == 200
    initial_plays = initial_stats.json()["total_plays"]

    # Find a track to play
    list_response = client.get("/api/v1/tracks?page_size=1")
    items = list_response.json()["items"]

    if items:
        track_id = items[0]["id"]

        # Record a play
        play_response = client.post(
            f"/api/v1/tracks/{track_id}/played",
            headers=headers,
            json={"duration_seconds": 120.0},
        )
        assert play_response.status_code == 200
        play_data = play_response.json()
        assert play_data["track_id"] == track_id
        assert play_data["play_count"] >= 1

        # Check stats increased
        new_stats = client.get("/api/v1/tracks/stats/plays", headers=headers)
        assert new_stats.status_code == 200
        assert new_stats.json()["total_plays"] == initial_plays + 1
