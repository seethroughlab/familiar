"""
Tests for the tracks API endpoints.

Note: These tests run against the actual database which may have existing data.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PlayEvent
from tests.conftest import make_profile_headers
from tests.factories import insert_test_track


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


@pytest_asyncio.fixture
async def listen_event_track(async_db: AsyncSession):
    """A track of our own, so these do not depend on the library having been scanned."""
    track = await insert_test_track(async_db, title="Timestamped", artist="Test")
    await async_db.commit()
    return str(track.id)


@pytest.mark.asyncio
async def test_listen_event_accepts_a_client_timestamp(
    client: TestClient, test_profile: dict, listen_event_track: str, async_db: AsyncSession
) -> None:
    """An event replayed from an offline queue keeps the time it actually happened.

    Without this the server stamps arrival time, so a queue drained hours later would date every
    event to the moment the network came back — misdating precisely the listening that needed
    queueing (ADR-0004 point 7).
    """
    headers = make_profile_headers(test_profile)

    # Offset-aware, as a Swift or browser client sends it. The column is naive UTC, and comparing
    # the two raises — the defect that made the queue-session endpoints 500 on first contact.
    happened = datetime.now(UTC) - timedelta(hours=3)
    response = client.post(
        f"/api/v1/tracks/{listen_event_track}/skipped",
        headers=headers,
        json={
            "played_seconds": 12.0,
            "track_duration": 200.0,
            "reason": "user",
            "started_at": happened.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "skipped"

    # Asserting the *stored* value, not just a 200. Pydantic drops unknown fields silently, so a
    # server that ignored `started_at` entirely would still answer 200 and this test would pass
    # while proving nothing.
    stored = (
        (
            await async_db.execute(
                select(PlayEvent)
                .where(PlayEvent.track_id == UUID(listen_event_track))
                .order_by(PlayEvent.started_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert stored is not None
    drift = abs((stored.started_at - happened.replace(tzinfo=None)).total_seconds())
    assert drift < 5, f"stored {stored.started_at}, expected about {happened}"


@pytest.mark.asyncio
async def test_listen_event_timestamp_cannot_be_in_the_future(
    client: TestClient, test_profile: dict, listen_event_track: str, async_db: AsyncSession
) -> None:
    """A device with a fast clock must not write events into the future.

    Anything reading a "recent listening" window would keep finding them, forever.
    """
    headers = make_profile_headers(test_profile)
    response = client.post(
        f"/api/v1/tracks/{listen_event_track}/skipped",
        headers=headers,
        json={
            "played_seconds": 5.0,
            "track_duration": 200.0,
            "reason": "user",
            "started_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        },
    )
    assert response.status_code == 200, response.text

    stored = (
        (
            await async_db.execute(
                select(PlayEvent)
                .where(PlayEvent.track_id == UUID(listen_event_track))
                .order_by(PlayEvent.started_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert stored is not None
    assert stored.started_at <= datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=5)
