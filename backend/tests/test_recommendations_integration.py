"""Integration tests for RecommendationsService against real PostgreSQL.

Tests the recommendation flow with mocked external services (Last.fm, Bandcamp).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.recommendations import RecommendationsService
from tests.factories import (
    insert_test_playlist,
    insert_test_playlist_track,
    insert_test_profile,
    insert_test_track,
)


@pytest.fixture
async def profile(async_db):
    p = await insert_test_profile(async_db)
    await async_db.commit()
    return p


@pytest.fixture
def mock_lastfm():
    """Create a mock Last.fm service.

    is_configured() is sync, so use MagicMock for it. The async methods
    (get_similar_artists, get_similar_tracks) use AsyncMock.
    """
    mock = MagicMock()
    mock.is_configured.return_value = True
    mock.get_similar_artists = AsyncMock(return_value=[
        {
            "name": "Recommended Artist",
            "match": "0.85",
            "url": "http://lastfm.com/artist",
            "image": [{"#text": "http://img.com/art.jpg", "size": "large"}],
        },
    ])
    mock.get_similar_tracks = AsyncMock(return_value=[
        {
            "name": "Recommended Track",
            "artist": {"name": "Recommended Artist"},
            "match": "0.75",
            "url": "http://lastfm.com/track",
        },
    ])
    return mock


@pytest.fixture
def mock_bandcamp():
    """Create a mock Bandcamp service."""
    mock = AsyncMock()
    result = MagicMock()
    result.name = "Bandcamp Artist"
    result.url = "http://bandcamp.com"
    result.image_url = "http://img.com/bc.jpg"
    mock.search.return_value = [result]
    mock.close = AsyncMock()
    return mock


class TestEmptyPlaylist:
    @pytest.mark.asyncio
    async def test_empty_playlist_returns_empty(self, async_db, profile, mock_lastfm, mock_bandcamp):
        playlist = await insert_test_playlist(async_db, profile.id, is_auto_generated=True)
        await async_db.commit()

        with patch("app.services.recommendations.get_lastfm_service", return_value=mock_lastfm), \
             patch("app.services.recommendations.BandcampService", return_value=mock_bandcamp):
            svc = RecommendationsService(db=async_db)
            recs = await svc.get_playlist_recommendations(playlist.id)
            await svc.close()

        assert recs.artists == []
        assert recs.tracks == []


class TestLastfmFlow:
    @pytest.mark.asyncio
    async def test_lastfm_recommendations(self, async_db, profile, mock_lastfm, mock_bandcamp):
        playlist = await insert_test_playlist(async_db, profile.id, is_auto_generated=True)
        t = await insert_test_track(async_db, title="Source Song", artist="Source Artist")
        await insert_test_playlist_track(async_db, playlist.id, track_id=t.id, position=0)
        await async_db.commit()

        with patch("app.services.recommendations.get_lastfm_service", return_value=mock_lastfm), \
             patch("app.services.recommendations.BandcampService", return_value=mock_bandcamp):
            svc = RecommendationsService(db=async_db)
            recs = await svc.get_playlist_recommendations(playlist.id)
            await svc.close()

        assert "lastfm" in recs.sources_used
        assert len(recs.artists) >= 1
        assert recs.artists[0].name == "Recommended Artist"
        assert recs.artists[0].source == "lastfm"
        assert recs.artists[0].match_score == 0.85


class TestBandcampFallback:
    @pytest.mark.asyncio
    async def test_bandcamp_when_lastfm_unconfigured(self, async_db, profile, mock_bandcamp):
        playlist = await insert_test_playlist(async_db, profile.id, is_auto_generated=True)
        t = await insert_test_track(async_db, title="BC Song", artist="BC Artist")
        await insert_test_playlist_track(async_db, playlist.id, track_id=t.id, position=0)
        await async_db.commit()

        mock_lastfm_unconfigured = MagicMock()
        mock_lastfm_unconfigured.is_configured.return_value = False

        with patch("app.services.recommendations.get_lastfm_service", return_value=mock_lastfm_unconfigured), \
             patch("app.services.recommendations.BandcampService", return_value=mock_bandcamp):
            svc = RecommendationsService(db=async_db)
            recs = await svc.get_playlist_recommendations(playlist.id)
            await svc.close()

        assert "bandcamp" in recs.sources_used
        assert len(recs.artists) >= 1
        assert recs.artists[0].source == "bandcamp"


class TestDedupeArtists:
    @pytest.mark.asyncio
    async def test_dedupe_keeps_highest_score(self, async_db, profile, mock_bandcamp):
        playlist = await insert_test_playlist(async_db, profile.id, is_auto_generated=True)
        # Two tracks by different artists
        t1 = await insert_test_track(async_db, title="Song1", artist="Artist A")
        t2 = await insert_test_track(async_db, title="Song2", artist="Artist B")
        await insert_test_playlist_track(async_db, playlist.id, track_id=t1.id, position=0)
        await insert_test_playlist_track(async_db, playlist.id, track_id=t2.id, position=1)
        await async_db.commit()

        # Both artists recommend the same "Recommended Artist" but with different scores
        mock_lastfm = MagicMock()
        mock_lastfm.is_configured.return_value = True
        mock_lastfm.get_similar_artists = AsyncMock(side_effect=[
            [{"name": "Shared Rec", "match": "0.9", "url": "http://a.com", "image": []}],
            [{"name": "Shared Rec", "match": "0.5", "url": "http://b.com", "image": []}],
            [], [], [],
        ])
        mock_lastfm.get_similar_tracks = AsyncMock(return_value=[])

        with patch("app.services.recommendations.get_lastfm_service", return_value=mock_lastfm), \
             patch("app.services.recommendations.BandcampService", return_value=mock_bandcamp):
            svc = RecommendationsService(db=async_db)
            recs = await svc.get_playlist_recommendations(playlist.id)
            await svc.close()

        # Should be deduplicated, keeping the higher score
        shared = [a for a in recs.artists if a.name == "Shared Rec"]
        assert len(shared) == 1
        assert shared[0].match_score == 0.9
