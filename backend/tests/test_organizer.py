"""Tests for library organizer - filename sanitization and path formatting."""

from unittest.mock import MagicMock

from app.services.organizer import LibraryOrganizer, sanitize_filename


class TestSanitizeFilename:
    """Tests for sanitize_filename helper."""

    def test_basic_passthrough(self):
        assert sanitize_filename("Hello World") == "Hello World"

    def test_none_returns_default(self):
        assert sanitize_filename(None) == "Unknown"

    def test_empty_returns_default(self):
        assert sanitize_filename("") == "Unknown"

    def test_custom_default(self):
        assert sanitize_filename(None, "Fallback") == "Fallback"

    def test_replaces_colon(self):
        assert sanitize_filename("Title: Subtitle") == "Title - Subtitle"

    def test_replaces_slash(self):
        assert sanitize_filename("AC/DC") == "AC-DC"

    def test_replaces_backslash(self):
        assert sanitize_filename("Back\\Slash") == "Back-Slash"

    def test_replaces_question_mark(self):
        assert sanitize_filename("What?") == "What"

    def test_replaces_asterisk(self):
        assert sanitize_filename("Star*s") == "Stars"

    def test_replaces_pipe(self):
        assert sanitize_filename("A|B") == "A-B"

    def test_replaces_double_quote(self):
        assert sanitize_filename('Say "Hello"') == "Say 'Hello'"

    def test_strips_leading_dots(self):
        result = sanitize_filename(".hidden")
        assert not result.startswith(".")

    def test_limits_length(self):
        long_name = "A" * 300
        result = sanitize_filename(long_name)
        assert len(result) <= 200

    def test_all_invalid_returns_default(self):
        result = sanitize_filename("???")
        assert result == "Unknown"

    def test_whitespace_only_returns_default(self):
        result = sanitize_filename("   ")
        assert result == "Unknown"


class TestLibraryOrganizerFormatPath:
    """Tests for LibraryOrganizer._format_path."""

    def _make_track(self, **overrides):
        track = MagicMock()
        track.title = overrides.get("title", "Test Track")
        track.artist = overrides.get("artist", "Test Artist")
        track.album_artist = overrides.get("album_artist", None)
        track.album = overrides.get("album", "Test Album")
        track.genre = overrides.get("genre", "Rock")
        track.year = overrides.get("year", 2024)
        track.track_number = overrides.get("track_number", 1)
        track.disc_number = overrides.get("disc_number", 1)
        track.file_path = overrides.get("file_path", "/music/old/track.mp3")
        return track

    def test_artist_album_template(self):
        from pathlib import Path
        from unittest.mock import AsyncMock

        organizer = LibraryOrganizer(db=AsyncMock(), library_root=Path("/music"))
        track = self._make_track()
        template = "{artist}/{album}/{track_number} - {title}"
        result = organizer._format_path(track, template)
        assert result == Path("/music/Test Artist/Test Album/01 - Test Track.mp3")

    def test_uses_album_artist_when_set(self):
        from pathlib import Path
        from unittest.mock import AsyncMock

        organizer = LibraryOrganizer(db=AsyncMock(), library_root=Path("/music"))
        track = self._make_track(album_artist="Various Artists")
        template = "{artist}/{album}/{track_number} - {title}"
        result = organizer._format_path(track, template)
        assert "Various Artists" in str(result)

    def test_genre_template(self):
        from pathlib import Path
        from unittest.mock import AsyncMock

        organizer = LibraryOrganizer(db=AsyncMock(), library_root=Path("/music"))
        track = self._make_track(genre="Electronic")
        template = "{genre}/{artist}/{album}/{track_number} - {title}"
        result = organizer._format_path(track, template)
        assert str(result).startswith("/music/Electronic/")

    def test_preserves_file_extension(self):
        from pathlib import Path
        from unittest.mock import AsyncMock

        organizer = LibraryOrganizer(db=AsyncMock(), library_root=Path("/music"))
        track = self._make_track(file_path="/music/old/track.flac")
        template = "{artist}/{album}/{track_number} - {title}"
        result = organizer._format_path(track, template)
        assert str(result).endswith(".flac")

    def test_zero_pads_track_number(self):
        from pathlib import Path
        from unittest.mock import AsyncMock

        organizer = LibraryOrganizer(db=AsyncMock(), library_root=Path("/music"))
        track = self._make_track(track_number=3)
        template = "{artist}/{album}/{track_number} - {title}"
        result = organizer._format_path(track, template)
        assert "03 - " in str(result)

    def test_missing_genre_uses_default(self):
        from pathlib import Path
        from unittest.mock import AsyncMock

        organizer = LibraryOrganizer(db=AsyncMock(), library_root=Path("/music"))
        track = self._make_track(genre=None)
        template = "{genre}/{artist}/{title}"
        result = organizer._format_path(track, template)
        assert "Unknown Genre" in str(result)


class TestHasCompleteMetadata:
    """Tests for LibraryOrganizer._has_complete_metadata."""

    def test_complete(self):
        from pathlib import Path
        from unittest.mock import AsyncMock

        organizer = LibraryOrganizer(db=AsyncMock(), library_root=Path("/music"))
        track = MagicMock()
        track.title = "Title"
        track.artist = "Artist"
        track.album = "Album"
        assert organizer._has_complete_metadata(track) is True

    def test_missing_title(self):
        from pathlib import Path
        from unittest.mock import AsyncMock

        organizer = LibraryOrganizer(db=AsyncMock(), library_root=Path("/music"))
        track = MagicMock()
        track.title = None
        track.artist = "Artist"
        track.album = "Album"
        assert organizer._has_complete_metadata(track) is False

    def test_missing_artist(self):
        from pathlib import Path
        from unittest.mock import AsyncMock

        organizer = LibraryOrganizer(db=AsyncMock(), library_root=Path("/music"))
        track = MagicMock()
        track.title = "Title"
        track.artist = None
        track.album = "Album"
        assert organizer._has_complete_metadata(track) is False

    def test_missing_album(self):
        from pathlib import Path
        from unittest.mock import AsyncMock

        organizer = LibraryOrganizer(db=AsyncMock(), library_root=Path("/music"))
        track = MagicMock()
        track.title = "Title"
        track.artist = "Artist"
        track.album = None
        assert organizer._has_complete_metadata(track) is False

    def test_empty_strings_are_falsy(self):
        from pathlib import Path
        from unittest.mock import AsyncMock

        organizer = LibraryOrganizer(db=AsyncMock(), library_root=Path("/music"))
        track = MagicMock()
        track.title = ""
        track.artist = "Artist"
        track.album = "Album"
        assert organizer._has_complete_metadata(track) is False
