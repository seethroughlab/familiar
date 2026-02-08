"""Tests for recommendations service - deduplication logic."""

from app.services.recommendations import Recommendations, RecommendedArtist, RecommendedTrack


class TestRecommendedArtist:
    def test_creation(self):
        artist = RecommendedArtist(
            name="Test Artist",
            source="lastfm",
            match_score=0.95,
            image_url=None,
            external_url="https://last.fm/artist",
            local_track_count=5,
        )
        assert artist.name == "Test Artist"
        assert artist.source == "lastfm"
        assert artist.match_score == 0.95
        assert artist.local_track_count == 5


class TestRecommendedTrack:
    def test_creation(self):
        track = RecommendedTrack(
            title="Test Track",
            artist="Test Artist",
            source="lastfm",
            match_score=0.90,
            external_url="https://last.fm/track",
            local_track_id=None,
        )
        assert track.title == "Test Track"
        assert track.artist == "Test Artist"
        assert track.local_track_id is None

    def test_with_local_track(self):
        track = RecommendedTrack(
            title="Local Track",
            artist="Artist",
            source="lastfm",
            match_score=1.0,
            external_url=None,
            local_track_id="some-uuid",
            album="Album Name",
        )
        assert track.local_track_id == "some-uuid"
        assert track.album == "Album Name"


class TestRecommendations:
    def test_empty_recommendations(self):
        recs = Recommendations(artists=[], tracks=[], sources_used=[])
        assert len(recs.artists) == 0
        assert len(recs.tracks) == 0
        assert recs.sources_used == []

    def test_with_data(self):
        artists = [
            RecommendedArtist("A1", "lastfm", 0.9, None, None, 0),
            RecommendedArtist("A2", "bandcamp", 0.8, None, None, 3),
        ]
        tracks = [
            RecommendedTrack("T1", "A1", "lastfm", 0.85, None, None),
        ]
        recs = Recommendations(artists=artists, tracks=tracks, sources_used=["lastfm", "bandcamp"])
        assert len(recs.artists) == 2
        assert len(recs.tracks) == 1
        assert "lastfm" in recs.sources_used
