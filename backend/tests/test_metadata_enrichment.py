"""Tests for metadata enrichment - placeholder detection and missing field identification."""

from unittest.mock import MagicMock

from app.services.metadata_enrichment import get_missing_fields, is_field_missing


class TestIsFieldMissing:
    """Tests for is_field_missing helper."""

    def test_none_is_missing(self):
        assert is_field_missing(None) is True

    def test_empty_string_is_missing(self):
        assert is_field_missing("") is True

    def test_whitespace_is_missing(self):
        assert is_field_missing("   ") is True

    def test_unknown_placeholder(self):
        assert is_field_missing("Unknown") is True

    def test_unknown_lowercase(self):
        assert is_field_missing("unknown") is True

    def test_track_number_placeholder(self):
        assert is_field_missing("Track 01") is True

    def test_untitled_placeholder(self):
        assert is_field_missing("Untitled") is True

    def test_various_artists_placeholder(self):
        assert is_field_missing("Various Artists") is True

    def test_valid_value(self):
        assert is_field_missing("Radiohead") is False

    def test_numeric_value(self):
        assert is_field_missing(2024) is False

    def test_zero_is_not_missing(self):
        assert is_field_missing(0) is False


class TestGetMissingFields:
    """Tests for get_missing_fields helper."""

    def test_all_fields_present(self):
        track = MagicMock()
        track.title = "Creep"
        track.artist = "Radiohead"
        track.album = "Pablo Honey"
        track.genre = "Alternative"
        track.year = 1993
        assert get_missing_fields(track) == []

    def test_missing_title(self):
        track = MagicMock()
        track.title = None
        track.artist = "Radiohead"
        track.album = "Pablo Honey"
        track.genre = "Alternative"
        track.year = 1993
        assert "title" in get_missing_fields(track)

    def test_missing_genre(self):
        track = MagicMock()
        track.title = "Creep"
        track.artist = "Radiohead"
        track.album = "Pablo Honey"
        track.genre = None
        track.year = 1993
        assert "genre" in get_missing_fields(track)

    def test_placeholder_artist(self):
        track = MagicMock()
        track.title = "Creep"
        track.artist = "Unknown"
        track.album = "Pablo Honey"
        track.genre = "Alternative"
        track.year = 1993
        assert "artist" in get_missing_fields(track)

    def test_multiple_missing(self):
        track = MagicMock()
        track.title = None
        track.artist = None
        track.album = "Pablo Honey"
        track.genre = "Alternative"
        track.year = 1993
        missing = get_missing_fields(track)
        assert "title" in missing
        assert "artist" in missing
        assert len(missing) == 2
