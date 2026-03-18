"""Integration tests for playlists API - reorder, item removal.

These tests insert real data via async_db, then use the sync TestClient.
"""

from unittest.mock import AsyncMock, patch

import pytest

from tests.factories import (
    insert_test_playlist,
    insert_test_playlist_track,
    insert_test_profile,
    insert_test_track,
)


@pytest.fixture
async def profile_with_headers(async_db):
    """Create a profile and return (profile, headers) tuple."""
    p = await insert_test_profile(async_db)
    await async_db.commit()
    return p, {"X-Profile-ID": str(p.id)}


class TestReorderTracks:
    @pytest.mark.asyncio
    async def test_reorder(self, async_db, client, profile_with_headers):
        profile, headers = profile_with_headers
        playlist = await insert_test_playlist(async_db, profile.id, name="Reorder Test")
        t1 = await insert_test_track(async_db, title="First")
        t2 = await insert_test_track(async_db, title="Second")
        t3 = await insert_test_track(async_db, title="Third")
        pt1 = await insert_test_playlist_track(async_db, playlist.id, track_id=t1.id, position=0)
        pt2 = await insert_test_playlist_track(async_db, playlist.id, track_id=t2.id, position=1)
        pt3 = await insert_test_playlist_track(async_db, playlist.id, track_id=t3.id, position=2)
        await async_db.commit()

        # Reverse order using playlist_track_ids
        resp = client.put(
            f"/api/v1/playlists/{playlist.id}/tracks/reorder",
            json={"playlist_track_ids": [str(pt3.id), str(pt2.id), str(pt1.id)]},
            headers=headers,
        )
        assert resp.status_code == 200
        tracks = resp.json()["tracks"]
        titles = [t["title"] for t in tracks]
        assert titles == ["Third", "Second", "First"]


class TestRemoveItem:
    @pytest.mark.asyncio
    async def test_remove_by_playlist_track_id(self, async_db, client, profile_with_headers):
        profile, headers = profile_with_headers
        playlist = await insert_test_playlist(async_db, profile.id, name="Remove Test")
        t = await insert_test_track(async_db, title="RemoveMe")
        pt = await insert_test_playlist_track(async_db, playlist.id, track_id=t.id, position=0)
        await async_db.commit()

        resp = client.delete(
            f"/api/v1/playlists/{playlist.id}/items/{pt.id}",
            headers=headers,
        )
        assert resp.status_code == 204

        # Verify removed
        resp = client.get(f"/api/v1/playlists/{playlist.id}", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["tracks"]) == 0

    @pytest.mark.asyncio
    async def test_remove_by_track_id(self, async_db, client, profile_with_headers):
        profile, headers = profile_with_headers
        playlist = await insert_test_playlist(async_db, profile.id, name="Remove Track Test")
        t = await insert_test_track(async_db, title="RemoveByTrackId")
        await insert_test_playlist_track(async_db, playlist.id, track_id=t.id, position=0)
        await async_db.commit()

        resp = client.delete(
            f"/api/v1/playlists/{playlist.id}/tracks/{t.id}",
            headers=headers,
        )
        assert resp.status_code == 204


class TestRecommendations:
    @pytest.mark.asyncio
    async def test_recommendations_requires_auto_generated(self, async_db, client, profile_with_headers):
        profile, headers = profile_with_headers
        playlist = await insert_test_playlist(
            async_db, profile.id, name="Manual", is_auto_generated=False
        )
        await async_db.commit()

        resp = client.get(
            f"/api/v1/playlists/{playlist.id}/recommendations",
            headers=headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_recommendations_mock_lastfm(self, async_db, client, profile_with_headers):
        profile, headers = profile_with_headers
        playlist = await insert_test_playlist(
            async_db, profile.id, name="AI Playlist", is_auto_generated=True
        )
        t = await insert_test_track(async_db, title="PlaylistSong", artist="ArtistX")
        await insert_test_playlist_track(async_db, playlist.id, track_id=t.id, position=0)
        await async_db.commit()

        mock_lastfm = AsyncMock()
        mock_lastfm.is_configured.return_value = True
        mock_lastfm.get_similar_artists.return_value = [
            {"name": "Similar Artist", "match": "0.8", "url": "http://example.com", "image": []},
        ]
        mock_lastfm.get_similar_tracks.return_value = [
            {"name": "Similar Track", "artist": {"name": "Similar Artist"}, "match": "0.7", "url": "http://example.com"},
        ]

        with patch("app.api.routes.playlists.recommendations.RecommendationsService") as MockRecSvc:
            instance = AsyncMock()
            instance.get_playlist_recommendations.return_value = AsyncMock(
                artists=[],
                tracks=[],
                sources_used=["lastfm"],
            )
            instance.close = AsyncMock()
            MockRecSvc.return_value = instance

            resp = client.get(
                f"/api/v1/playlists/{playlist.id}/recommendations",
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "artists" in data
            assert "tracks" in data
            assert "sources_used" in data
