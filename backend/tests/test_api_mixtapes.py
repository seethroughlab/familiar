"""API contract tests for the /mixtapes routes.

The render runs in a background task and shells out to ffmpeg, so we patch
the task entry point to a no-op for these tests. End-to-end render is
exercised in test_mixtape_export.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.db.models import MixTape
from tests.factories import (
    insert_test_playlist,
    insert_test_playlist_track,
    insert_test_profile,
    insert_test_track,
)


@pytest_asyncio.fixture
async def playlist_with_tracks(async_db) -> dict:
    """A profile + a playlist with three tracks. Returns ids as strings."""
    profile = await insert_test_profile(async_db)
    playlist = await insert_test_playlist(async_db, profile.id)
    for i in range(3):
        track = await insert_test_track(async_db, title=f"Song {i}")
        await insert_test_playlist_track(async_db, playlist.id, track_id=track.id, position=i)
    await async_db.commit()
    return {
        "profile_id": str(profile.id),
        "playlist_id": str(playlist.id),
    }


def _headers(profile_id: str) -> dict[str, str]:
    return {"X-Profile-ID": profile_id}


@pytest.mark.asyncio
async def test_create_mixtape_kicks_off_render(client: TestClient, playlist_with_tracks: dict) -> None:
    """POST /mixtapes accepts the request and creates a pending row."""
    with patch(
        "app.api.routes.mixtapes.run_mixtape_export",
        new_callable=AsyncMock,
    ):
        response = client.post(
            "/api/v1/mixtapes",
            json={
                "name": "My Mix",
                "source_playlist_id": playlist_with_tracks["playlist_id"],
                "crossfade_seconds": 5,
            },
            headers=_headers(playlist_with_tracks["profile_id"]),
        )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["name"] == "My Mix"
    assert body["status"] == "pending"
    assert body["crossfade_seconds"] == 5
    assert body["byline"] is None


@pytest.mark.asyncio
async def test_create_mixtape_persists_byline(client: TestClient, playlist_with_tracks: dict) -> None:
    """A byline in the create payload is persisted and surfaced on GET."""
    with patch(
        "app.api.routes.mixtapes.run_mixtape_export",
        new_callable=AsyncMock,
    ):
        response = client.post(
            "/api/v1/mixtapes",
            json={
                "name": "Birthday Mix",
                "source_playlist_id": playlist_with_tracks["playlist_id"],
                "byline": "  Jeff  ",  # whitespace should be stripped
            },
            headers=_headers(playlist_with_tracks["profile_id"]),
        )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["byline"] == "Jeff"

    fetched = client.get(
        f"/api/v1/mixtapes/{body['id']}",
        headers=_headers(playlist_with_tracks["profile_id"]),
    )
    assert fetched.status_code == 200
    assert fetched.json()["byline"] == "Jeff"


@pytest.mark.asyncio
async def test_create_mixtape_empty_byline_becomes_null(
    client: TestClient, playlist_with_tracks: dict
) -> None:
    """An empty-string byline is normalized to null on persistence."""
    with patch(
        "app.api.routes.mixtapes.run_mixtape_export",
        new_callable=AsyncMock,
    ):
        response = client.post(
            "/api/v1/mixtapes",
            json={
                "name": "Mix",
                "source_playlist_id": playlist_with_tracks["playlist_id"],
                "byline": "   ",
            },
            headers=_headers(playlist_with_tracks["profile_id"]),
        )
    assert response.status_code == 202
    assert response.json()["byline"] is None


@pytest.mark.asyncio
async def test_create_mixtape_rejects_both_sources(
    client: TestClient, playlist_with_tracks: dict
) -> None:
    """Specifying both source_playlist_id and source_smart_playlist_id is invalid."""
    response = client.post(
        "/api/v1/mixtapes",
        json={
            "name": "Bad",
            "source_playlist_id": playlist_with_tracks["playlist_id"],
            "source_smart_playlist_id": playlist_with_tracks["playlist_id"],
        },
        headers=_headers(playlist_with_tracks["profile_id"]),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_mixtape_rejects_neither_source(
    client: TestClient, playlist_with_tracks: dict
) -> None:
    """At least one source must be specified."""
    response = client.post(
        "/api/v1/mixtapes",
        json={"name": "Bad"},
        headers=_headers(playlist_with_tracks["profile_id"]),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_mixtape_rejects_too_few_tracks(client: TestClient, async_db) -> None:
    """A playlist with fewer than MIN_TRACKS tracks cannot be exported."""
    profile = await insert_test_profile(async_db)
    playlist = await insert_test_playlist(async_db, profile.id)
    track = await insert_test_track(async_db)
    await insert_test_playlist_track(async_db, playlist.id, track_id=track.id, position=0)
    await async_db.commit()

    response = client.post(
        "/api/v1/mixtapes",
        json={"name": "Tiny", "source_playlist_id": str(playlist.id)},
        headers=_headers(str(profile.id)),
    )
    assert response.status_code == 400
    assert "at least" in response.json()["message"].lower()


@pytest.mark.asyncio
async def test_concurrent_render_returns_409(
    client: TestClient, async_db, playlist_with_tracks: dict
) -> None:
    """A second render request while one is in flight is rejected."""
    from uuid import UUID
    in_flight = MixTape(
        profile_id=UUID(playlist_with_tracks["profile_id"]),
        name="Already Going",
        source_playlist_id=UUID(playlist_with_tracks["playlist_id"]),
        track_ids=[],
        status="rendering",
    )
    async_db.add(in_flight)
    await async_db.commit()

    with patch(
        "app.api.routes.mixtapes.run_mixtape_export",
        new_callable=AsyncMock,
    ):
        response = client.post(
            "/api/v1/mixtapes",
            json={
                "name": "Second Mix",
                "source_playlist_id": playlist_with_tracks["playlist_id"],
            },
            headers=_headers(playlist_with_tracks["profile_id"]),
        )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_get_mixtape_returns_404_for_other_profile(
    client: TestClient, async_db, playlist_with_tracks: dict
) -> None:
    """A profile cannot see another profile's mixtape."""
    from uuid import UUID
    other_profile = await insert_test_profile(async_db, name="Other")
    mixtape = MixTape(
        profile_id=other_profile.id,
        name="Theirs",
        source_playlist_id=UUID(playlist_with_tracks["playlist_id"]),
        track_ids=[],
        status="ready",
    )
    async_db.add(mixtape)
    await async_db.commit()

    response = client.get(
        f"/api/v1/mixtapes/{mixtape.id}",
        headers=_headers(playlist_with_tracks["profile_id"]),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_download_blocked_until_ready(
    client: TestClient, async_db, playlist_with_tracks: dict
) -> None:
    """GET /mixtapes/{id}/download returns 409 if the render isn't done."""
    from uuid import UUID
    mixtape = MixTape(
        profile_id=UUID(playlist_with_tracks["profile_id"]),
        name="Pending",
        source_playlist_id=UUID(playlist_with_tracks["playlist_id"]),
        track_ids=[],
        status="rendering",
    )
    async_db.add(mixtape)
    await async_db.commit()

    response = client.get(
        f"/api/v1/mixtapes/{mixtape.id}/download",
        headers=_headers(playlist_with_tracks["profile_id"]),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_list_mixtapes_scopes_to_profile(
    client: TestClient, async_db, playlist_with_tracks: dict
) -> None:
    """GET /mixtapes only returns the requesting profile's mixtapes."""
    from uuid import UUID
    mine = MixTape(
        profile_id=UUID(playlist_with_tracks["profile_id"]),
        name="Mine",
        source_playlist_id=UUID(playlist_with_tracks["playlist_id"]),
        track_ids=[],
        status="ready",
    )
    other_profile = await insert_test_profile(async_db, name="Other")
    theirs = MixTape(
        profile_id=other_profile.id,
        name="Theirs",
        source_playlist_id=UUID(playlist_with_tracks["playlist_id"]),
        track_ids=[],
        status="ready",
    )
    async_db.add_all([mine, theirs])
    await async_db.commit()

    response = client.get(
        "/api/v1/mixtapes",
        headers=_headers(playlist_with_tracks["profile_id"]),
    )
    assert response.status_code == 200
    names = {m["name"] for m in response.json()}
    assert "Mine" in names
    assert "Theirs" not in names
