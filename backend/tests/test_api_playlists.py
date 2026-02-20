"""
Tests for the playlists API endpoints.

Note: These tests create their own profiles and playlists via API.
"""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import make_profile_headers


def test_list_playlists_requires_profile(client: TestClient) -> None:
    """Test that listing playlists requires a profile."""
    response = client.get("/api/v1/playlists")
    assert response.status_code == 401


def test_list_playlists_new_profile(client: TestClient, test_profile: dict) -> None:
    """Test listing playlists for a new profile is empty."""
    headers = make_profile_headers(test_profile)
    response = client.get("/api/v1/playlists", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


def test_create_playlist(client: TestClient, test_profile: dict) -> None:
    """Test creating a new playlist."""
    headers = make_profile_headers(test_profile)
    response = client.post(
        "/api/v1/playlists",
        headers=headers,
        json={
            "name": "My Playlist",
            "description": "A test playlist",
        },
    )
    assert response.status_code == 201
    data = response.json()

    assert data["name"] == "My Playlist"
    assert data["description"] == "A test playlist"
    assert data["is_auto_generated"] is False
    assert data["tracks"] == []
    assert "id" in data
    assert "created_at" in data


def test_create_auto_generated_playlist(client: TestClient, test_profile: dict) -> None:
    """Test creating an auto-generated (AI) playlist."""
    headers = make_profile_headers(test_profile)
    response = client.post(
        "/api/v1/playlists",
        headers=headers,
        json={
            "name": "AI Playlist",
            "is_auto_generated": True,
            "generation_prompt": "Play something upbeat",
        },
    )
    assert response.status_code == 201
    data = response.json()

    assert data["is_auto_generated"] is True
    assert data["generation_prompt"] == "Play something upbeat"


def test_get_playlist(client: TestClient, test_profile: dict) -> None:
    """Test getting a playlist by ID."""
    headers = make_profile_headers(test_profile)

    # Create a playlist first
    create_response = client.post(
        "/api/v1/playlists",
        headers=headers,
        json={
            "name": "Test Playlist",
            "description": "Description",
        },
    )
    playlist_id = create_response.json()["id"]

    # Get the playlist
    response = client.get(
        f"/api/v1/playlists/{playlist_id}",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == playlist_id
    assert data["name"] == "Test Playlist"
    assert data["description"] == "Description"


def test_get_playlist_not_found(client: TestClient, test_profile: dict) -> None:
    """Test getting a non-existent playlist returns 404."""
    headers = make_profile_headers(test_profile)
    response = client.get(
        f"/api/v1/playlists/{uuid4()}",
        headers=headers,
    )
    assert response.status_code == 404


def test_update_playlist(client: TestClient, test_profile: dict) -> None:
    """Test updating a playlist's name and description."""
    headers = make_profile_headers(test_profile)

    # Create a playlist
    create_response = client.post(
        "/api/v1/playlists",
        headers=headers,
        json={"name": "Original Name", "description": "Original Description"},
    )
    playlist_id = create_response.json()["id"]

    # Update the playlist
    response = client.put(
        f"/api/v1/playlists/{playlist_id}",
        headers=headers,
        json={"name": "Updated Name", "description": "Updated Description"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["name"] == "Updated Name"
    assert data["description"] == "Updated Description"


def test_delete_playlist(client: TestClient, test_profile: dict) -> None:
    """Test deleting a playlist."""
    headers = make_profile_headers(test_profile)

    # Create a playlist
    create_response = client.post(
        "/api/v1/playlists",
        headers=headers,
        json={"name": "To Delete"},
    )
    playlist_id = create_response.json()["id"]

    # Delete the playlist
    response = client.delete(
        f"/api/v1/playlists/{playlist_id}",
        headers=headers,
    )
    assert response.status_code == 204

    # Verify it's gone
    get_response = client.get(
        f"/api/v1/playlists/{playlist_id}",
        headers=headers,
    )
    assert get_response.status_code == 404


def test_list_playlists_excludes_auto_generated(
    client: TestClient, test_profile: dict
) -> None:
    """Test filtering out auto-generated playlists."""
    headers = make_profile_headers(test_profile)

    # Create a manual playlist
    client.post(
        "/api/v1/playlists",
        headers=headers,
        json={"name": "Manual Playlist"},
    )

    # Create an auto-generated playlist
    client.post(
        "/api/v1/playlists",
        headers=headers,
        json={"name": "AI Playlist", "is_auto_generated": True},
    )

    # List all playlists
    response = client.get("/api/v1/playlists", headers=headers)
    assert len(response.json()) == 2

    # List only manual playlists
    response = client.get(
        "/api/v1/playlists?include_auto=false",
        headers=headers,
    )
    assert len(response.json()) == 1
    assert response.json()[0]["name"] == "Manual Playlist"


def test_add_tracks_to_playlist(client: TestClient, test_profile: dict) -> None:
    """Test adding tracks to an existing playlist (JSON body is parsed, not 422)."""
    headers = make_profile_headers(test_profile)

    # Create an empty playlist
    create_response = client.post(
        "/api/v1/playlists",
        headers=headers,
        json={"name": "Growing Playlist"},
    )
    playlist_id = create_response.json()["id"]

    # Send fake UUIDs — backend silently skips non-existent IDs
    fake_ids = ["00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"]
    response = client.post(
        f"/api/v1/playlists/{playlist_id}/tracks",
        headers=headers,
        json=fake_ids,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == playlist_id


def test_remove_track_from_playlist(client: TestClient, test_profile: dict) -> None:
    """Test removing a track from a playlist."""
    headers = make_profile_headers(test_profile)

    # Find a track to use
    list_response = client.get("/api/v1/tracks?page_size=2")
    tracks = list_response.json()["items"]

    if len(tracks) >= 2:
        track_ids = [t["id"] for t in tracks]

        # Create playlist with tracks
        create_response = client.post(
            "/api/v1/playlists",
            headers=headers,
            json={"name": "Playlist", "track_ids": track_ids},
        )
        playlist_id = create_response.json()["id"]
        assert len(create_response.json()["tracks"]) == 2

        # Remove first track
        response = client.delete(
            f"/api/v1/playlists/{playlist_id}/tracks/{track_ids[0]}",
            headers=headers,
        )
        assert response.status_code == 204

        # Verify track is gone
        get_response = client.get(
            f"/api/v1/playlists/{playlist_id}",
            headers=headers,
        )
        assert len(get_response.json()["tracks"]) == 1


def test_playlist_isolation_between_profiles(client: TestClient) -> None:
    """Test that profiles cannot see each other's playlists."""
    # Create two profiles
    profile1 = client.post(
        "/api/v1/profiles", json={"name": "User 1"}
    ).json()
    profile2 = client.post(
        "/api/v1/profiles", json={"name": "User 2"}
    ).json()

    headers1 = make_profile_headers(profile1)
    headers2 = make_profile_headers(profile2)

    # Profile 1 creates a playlist
    create_response = client.post(
        "/api/v1/playlists",
        headers=headers1,
        json={"name": "Profile 1's Playlist"},
    )
    playlist_id = create_response.json()["id"]

    # Profile 1 can see it
    response = client.get(f"/api/v1/playlists/{playlist_id}", headers=headers1)
    assert response.status_code == 200

    # Profile 2 cannot see it
    response = client.get(f"/api/v1/playlists/{playlist_id}", headers=headers2)
    assert response.status_code == 404

    # Profile 2's list is empty
    response = client.get("/api/v1/playlists", headers=headers2)
    assert response.json() == []
