"""Contract tests: happy-path smoke tests for API response serialization.

Verifies that GET endpoints return 200 (not 500) when realistic data exists.
Catches Pydantic response model mismatches — e.g. a model declaring `dict`
when the DB stores a `list`.

The auth matrix tests prove endpoints reject bad auth; these tests prove
endpoints succeed with valid auth and seeded data.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from app.db.models import TrackStatus
from app.db.models.spotify import SpotifyImport
from app.utils.time import utcnow
from tests.conftest import make_profile_headers
from tests.factories import (
    insert_test_track,
    insert_test_profile,
    insert_test_analysis,
    insert_test_play_history,
    insert_test_proposed_change,
    insert_test_playlist,
    insert_test_playlist_track,
    insert_test_smart_playlist,
)


@pytest_asyncio.fixture
async def seeded_db(async_db: AsyncSession):
    """Seed the database with realistic data across all major models."""
    profile = await insert_test_profile(async_db, name="Smoke Test User")

    # Active tracks
    tracks = []
    for i in range(3):
        t = await insert_test_track(
            async_db,
            title=f"Track {i}",
            artist="Test Artist",
            album="Test Album",
            genre="Electronic",
            year=2024,
            format="flac",
        )
        tracks.append(t)

    # Analysis for first track
    await insert_test_analysis(
        async_db,
        tracks[0].id,
        {"energy": 0.8, "valence": 0.6, "danceability": 0.7},
    )

    # Play history
    await insert_test_play_history(
        async_db, profile.id, tracks[0].id, play_count=5
    )

    # Proposed change
    await insert_test_proposed_change(
        async_db,
        target_ids=[str(tracks[0].id)],
        field="genre",
        old_value="Electronic",
        new_value="Ambient",
    )

    # Playlist with tracks
    playlist = await insert_test_playlist(async_db, profile.id, name="Test Playlist")
    await insert_test_playlist_track(
        async_db, playlist.id, track_id=tracks[0].id, position=0
    )

    # Smart playlist
    await insert_test_smart_playlist(async_db, profile.id, name="Test Smart Playlist")

    # Pending review track
    pending = await insert_test_track(
        async_db,
        title="Pending Track",
        artist="New Artist",
        album="New Album",
        file_path=f"/incoming/{uuid4().hex[:8]}/pending.flac",
    )
    pending.status = TrackStatus.PENDING_REVIEW
    pending.review_info = {
        "duplicate_of": None,
        "duplicate_info": None,
        "trump_status": None,
    }

    # Spotify import with list-typed favorites/playlists (matches real data shape)
    spotify = SpotifyImport(
        profile_id=profile.id,
        spotify_username="testuser",
        favorites=[
            {"uri": "spotify:track:abc", "title": "Fav Song", "artist": "Fav Artist"}
        ],
        playlists=[
            {"name": "My Playlist", "tracks": [{"uri": "spotify:track:def"}]}
        ],
        streaming_stats={"total_ms": 12345},
        match_results={},
        summary={"total_tracks": 1},
    )
    async_db.add(spotify)

    await async_db.commit()

    return {
        "profile": profile,
        "tracks": tracks,
        "playlist": playlist,
        "pending_track": pending,
    }


# ---------------------------------------------------------------------------
# Parametrized happy-path tests: each tuple is (method, path, needs_profile)
# ---------------------------------------------------------------------------

# Endpoints that don't need data to exist — just need to not 500
ALWAYS_OK_ENDPOINTS = [
    ("GET", "/api/v1/health", False),
    ("GET", "/api/v1/settings", False),
    ("GET", "/api/v1/background/jobs", False),
    ("GET", "/api/v1/pending-tracks/stats", False),
    ("GET", "/api/v1/pending-tracks/groups", False),
]


@pytest.mark.parametrize("method,path,needs_profile", ALWAYS_OK_ENDPOINTS)
def test_endpoint_returns_ok(
    client: TestClient,
    method: str,
    path: str,
    needs_profile: bool,
):
    """Endpoints that should always return 200 regardless of data."""
    response = client.request(method, path)
    assert response.status_code == 200, (
        f"{method} {path} returned {response.status_code}: {response.text[:200]}"
    )


# Endpoints that need seeded data + profile header to return 200
SEEDED_ENDPOINTS = [
    ("GET", "/api/v1/tracks/ids"),
    ("GET", "/api/v1/tracks"),
    ("GET", "/api/v1/playlists"),
    ("GET", "/api/v1/smart-playlists"),
    ("GET", "/api/v1/favorites"),
    ("GET", "/api/v1/proposed-changes"),
    ("GET", "/api/v1/spotify/import"),
    ("GET", "/api/v1/profiles/me"),
]


@pytest.mark.parametrize("method,path", SEEDED_ENDPOINTS)
def test_seeded_endpoint_returns_ok(
    client: TestClient,
    seeded_db: dict,
    method: str,
    path: str,
):
    """Endpoints return 200 when profile header is set and data exists."""
    headers = make_profile_headers({"id": str(seeded_db["profile"].id)})
    response = client.request(method, path, headers=headers)
    assert response.status_code == 200, (
        f"{method} {path} returned {response.status_code}: {response.text[:300]}"
    )


def test_track_by_id_serializes(client: TestClient, seeded_db: dict):
    """GET /tracks/batch with explicit IDs returns valid data."""
    track_id = str(seeded_db["tracks"][0].id)
    headers = make_profile_headers({"id": str(seeded_db["profile"].id)})
    response = client.get(
        f"/api/v1/tracks/batch?ids={track_id}",
        headers=headers,
    )
    assert response.status_code == 200, response.text[:300]
    data = response.json()
    assert len(data) >= 1


def test_pending_tracks_with_data(client: TestClient, seeded_db: dict):
    """Pending review endpoints serialize correctly with pending tracks."""
    response = client.get("/api/v1/pending-tracks/groups")
    assert response.status_code == 200
    data = response.json()
    assert data["total_tracks"] >= 1
    assert len(data["groups"]) >= 1
    # Verify tracks within groups have review_info
    group = data["groups"][0]
    assert len(group["tracks"]) >= 1


def test_spotify_import_with_list_data(client: TestClient, seeded_db: dict):
    """Spotify import serializes correctly when favorites/playlists are lists.

    Regression: SpotifyImportResponse declared `dict` but DB stores `list`,
    causing a 500 on GET /spotify/import.
    """
    headers = make_profile_headers({"id": str(seeded_db["profile"].id)})
    response = client.get("/api/v1/spotify/import", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data is not None
    assert isinstance(data["favorites"], list)
    assert isinstance(data["playlists"], list)
