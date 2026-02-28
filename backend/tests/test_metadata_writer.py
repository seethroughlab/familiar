"""Tests for the metadata_writer service.

Tests writing metadata to audio files in various formats (MP3, FLAC, M4A, OGG, AIFF).
Uses copies of fixture files to avoid modifying original test data.
"""

import shutil
import tempfile
from pathlib import Path

import pytest
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

from app.services.metadata.writer import (
    remove_artwork,
    write_lyrics,
    write_metadata,
)

# Path to test audio fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


@pytest.fixture(scope="module")
def temp_audio_dir():
    """Create a temporary directory with copies of audio files for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Copy an MP3 file for testing
        mp3_src = FIXTURES_DIR / "electronic_short.mp3"
        if mp3_src.exists():
            shutil.copy(mp3_src, tmpdir_path / "test.mp3")

        yield tmpdir_path


@pytest.fixture
def mp3_file(temp_audio_dir):
    """Provide a fresh copy of MP3 file for each test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        src = temp_audio_dir / "test.mp3"
        if src.exists():
            dst = tmpdir_path / "test.mp3"
            shutil.copy(src, dst)
            yield dst
        else:
            pytest.skip("MP3 fixture not available")


@pytest.fixture
def flac_file():
    """Create a minimal FLAC file for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        flac_path = tmpdir_path / "test.flac"

        # Create minimal FLAC from MP3 using mutagen's raw creation
        # FLAC requires actual audio data, so we'll convert from MP3 if available
        mp3_src = FIXTURES_DIR / "electronic_short.mp3"
        if not mp3_src.exists():
            pytest.skip("MP3 fixture not available for FLAC conversion")

        # Use ffmpeg if available, otherwise skip
        import subprocess
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(mp3_src), "-c:a", "flac", str(flac_path)],
                capture_output=True,
            )
            if result.returncode != 0:
                pytest.skip("ffmpeg failed for FLAC conversion")
        except FileNotFoundError:
            pytest.skip("ffmpeg not available for FLAC conversion")

        yield flac_path


@pytest.fixture
def m4a_file():
    """Create a minimal M4A file for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        m4a_path = tmpdir_path / "test.m4a"

        mp3_src = FIXTURES_DIR / "electronic_short.mp3"
        if not mp3_src.exists():
            pytest.skip("MP3 fixture not available for M4A conversion")

        import subprocess
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(mp3_src), "-c:a", "aac", "-b:a", "128k", str(m4a_path)],
                capture_output=True,
            )
            if result.returncode != 0:
                pytest.skip("ffmpeg failed for M4A conversion")
        except FileNotFoundError:
            pytest.skip("ffmpeg not available for M4A conversion")

        yield m4a_path


@pytest.fixture
def ogg_file():
    """Create a minimal OGG file for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        ogg_path = tmpdir_path / "test.ogg"

        mp3_src = FIXTURES_DIR / "electronic_short.mp3"
        if not mp3_src.exists():
            pytest.skip("MP3 fixture not available for OGG conversion")

        import subprocess
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(mp3_src), "-c:a", "libvorbis", "-q:a", "4", str(ogg_path)],
                capture_output=True,
            )
            if result.returncode != 0:
                pytest.skip("ffmpeg failed for OGG conversion")
        except FileNotFoundError:
            pytest.skip("ffmpeg not available for OGG conversion")

        yield ogg_path


@pytest.fixture
def aiff_file():
    """Create a minimal AIFF file for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        aiff_path = tmpdir_path / "test.aiff"

        mp3_src = FIXTURES_DIR / "electronic_short.mp3"
        if not mp3_src.exists():
            pytest.skip("MP3 fixture not available for AIFF conversion")

        import subprocess
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(mp3_src), "-c:a", "pcm_s16be", str(aiff_path)],
                capture_output=True,
            )
            if result.returncode != 0:
                pytest.skip("ffmpeg failed for AIFF conversion")
        except FileNotFoundError:
            pytest.skip("ffmpeg not available for AIFF conversion")

        yield aiff_path


class TestWriteMetadataMP3:
    """Tests for writing metadata to MP3 files."""

    def test_write_title(self, mp3_file):
        """Test writing title to MP3."""
        result = write_metadata(mp3_file, {"title": "Test Title"})
        assert result.success
        assert "title" in result.fields_written

        # Verify the metadata was written
        audio = ID3(mp3_file)
        assert str(audio.get("TIT2")) == "Test Title"

    def test_write_artist(self, mp3_file):
        """Test writing artist to MP3."""
        result = write_metadata(mp3_file, {"artist": "Test Artist"})
        assert result.success
        assert "artist" in result.fields_written

        audio = ID3(mp3_file)
        assert str(audio.get("TPE1")) == "Test Artist"

    def test_write_album(self, mp3_file):
        """Test writing album to MP3."""
        result = write_metadata(mp3_file, {"album": "Test Album"})
        assert result.success
        assert "album" in result.fields_written

        audio = ID3(mp3_file)
        assert str(audio.get("TALB")) == "Test Album"

    def test_write_year(self, mp3_file):
        """Test writing year to MP3."""
        result = write_metadata(mp3_file, {"year": "2024"})
        assert result.success
        assert "year" in result.fields_written

        audio = ID3(mp3_file)
        assert str(audio.get("TDRC")) == "2024"

    def test_write_track_number(self, mp3_file):
        """Test writing track number to MP3."""
        result = write_metadata(mp3_file, {"track_number": "5"})
        assert result.success
        assert "track_number" in result.fields_written

        audio = ID3(mp3_file)
        assert "5" in str(audio.get("TRCK"))

    def test_write_genre(self, mp3_file):
        """Test writing genre to MP3."""
        result = write_metadata(mp3_file, {"genre": "Electronic"})
        assert result.success
        assert "genre" in result.fields_written

        audio = ID3(mp3_file)
        assert str(audio.get("TCON")) == "Electronic"

    def test_write_multiple_fields(self, mp3_file):
        """Test writing multiple metadata fields at once."""
        metadata = {
            "title": "Multi Test",
            "artist": "Multi Artist",
            "album": "Multi Album",
            "year": "2025",
            "genre": "Rock",
        }
        result = write_metadata(mp3_file, metadata)
        assert result.success
        assert len(result.fields_written) == 5

        audio = ID3(mp3_file)
        assert str(audio.get("TIT2")) == "Multi Test"
        assert str(audio.get("TPE1")) == "Multi Artist"
        assert str(audio.get("TALB")) == "Multi Album"
        assert str(audio.get("TDRC")) == "2025"
        assert str(audio.get("TCON")) == "Rock"

    def test_unsupported_field_reported(self, mp3_file):
        """Test that unsupported fields are reported but don't cause failure."""
        result = write_metadata(mp3_file, {
            "title": "Test",
            "unsupported_field": "value",
        })
        assert result.success
        assert "title" in result.fields_written
        assert "unsupported_field" in result.unsupported_fields

    def test_nonexistent_file(self):
        """Test handling of non-existent file."""
        result = write_metadata(Path("/nonexistent/file.mp3"), {"title": "Test"})
        assert not result.success
        assert result.error is not None


class TestWriteMetadataFLAC:
    """Tests for writing metadata to FLAC files."""

    def test_write_title(self, flac_file):
        """Test writing title to FLAC."""
        result = write_metadata(flac_file, {"title": "FLAC Title"})
        assert result.success
        assert "title" in result.fields_written

        audio = FLAC(flac_file)
        assert audio.get("title") == ["FLAC Title"]

    def test_write_multiple_fields(self, flac_file):
        """Test writing multiple fields to FLAC."""
        metadata = {
            "title": "FLAC Multi",
            "artist": "FLAC Artist",
            "album": "FLAC Album",
        }
        result = write_metadata(flac_file, metadata)
        assert result.success
        assert len(result.fields_written) == 3


class TestWriteMetadataM4A:
    """Tests for writing metadata to M4A/MP4 files."""

    def test_write_title(self, m4a_file):
        """Test writing title to M4A."""
        result = write_metadata(m4a_file, {"title": "M4A Title"})
        assert result.success
        assert "title" in result.fields_written

        audio = MP4(m4a_file)
        assert audio.tags["\xa9nam"] == ["M4A Title"]

    def test_write_track_number(self, m4a_file):
        """Test writing track number to M4A (stored as tuple)."""
        result = write_metadata(m4a_file, {"track_number": "7"})
        assert result.success
        assert "track_number" in result.fields_written

        audio = MP4(m4a_file)
        # M4A stores track as (track, total) tuple
        assert audio.tags["trkn"][0][0] == 7


class TestWriteMetadataOGG:
    """Tests for writing metadata to OGG files."""

    def test_write_title(self, ogg_file):
        """Test writing title to OGG."""
        result = write_metadata(ogg_file, {"title": "OGG Title"})
        assert result.success
        assert "title" in result.fields_written

        audio = OggVorbis(ogg_file)
        assert audio.get("title") == ["OGG Title"]


class TestWriteLyrics:
    """Tests for writing lyrics to audio files."""

    def test_write_lyrics_mp3(self, mp3_file):
        """Test writing lyrics to MP3."""
        test_lyrics = "These are test lyrics\nWith multiple lines"
        result = write_lyrics(mp3_file, test_lyrics)
        assert result.success
        assert "lyrics" in result.fields_written

        # Verify lyrics were written
        audio = ID3(mp3_file)
        uslt_frames = audio.getall("USLT")
        assert len(uslt_frames) > 0
        assert test_lyrics in str(uslt_frames[0])

    def test_write_lyrics_flac(self, flac_file):
        """Test writing lyrics to FLAC."""
        test_lyrics = "FLAC lyrics content"
        result = write_lyrics(flac_file, test_lyrics)
        assert result.success

        audio = FLAC(flac_file)
        assert audio.get("LYRICS") == [test_lyrics]

    def test_write_lyrics_m4a(self, m4a_file):
        """Test writing lyrics to M4A."""
        test_lyrics = "M4A lyrics content"
        result = write_lyrics(m4a_file, test_lyrics)
        assert result.success

        audio = MP4(m4a_file)
        assert audio.tags["\xa9lyr"] == [test_lyrics]

    def test_write_lyrics_ogg(self, ogg_file):
        """Test writing lyrics to OGG."""
        test_lyrics = "OGG lyrics content"
        result = write_lyrics(ogg_file, test_lyrics)
        assert result.success

        audio = OggVorbis(ogg_file)
        assert audio.get("LYRICS") == [test_lyrics]

    def test_write_empty_lyrics_clears(self, mp3_file):
        """Test that writing empty lyrics clears existing lyrics."""
        # First write some lyrics
        write_lyrics(mp3_file, "Initial lyrics")

        # Then clear them
        result = write_lyrics(mp3_file, "")
        assert result.success

        audio = ID3(mp3_file)
        uslt_frames = audio.getall("USLT")
        # Should either be empty or have empty text
        if uslt_frames:
            assert str(uslt_frames[0]) == ""


class TestRemoveArtwork:
    """Tests for clearing artwork from audio files."""

    def test_remove_artwork_mp3_no_artwork(self, mp3_file):
        """Test clearing artwork from MP3 with no existing artwork."""
        result = remove_artwork(mp3_file)
        assert result.success

    def test_remove_artwork_flac_no_artwork(self, flac_file):
        """Test clearing artwork from FLAC with no existing artwork."""
        result = remove_artwork(flac_file)
        assert result.success

    def test_remove_artwork_m4a_no_artwork(self, m4a_file):
        """Test clearing artwork from M4A with no existing artwork."""
        result = remove_artwork(m4a_file)
        assert result.success

    def test_remove_artwork_unsupported_format(self):
        """Test clearing artwork from unsupported format."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = Path(f.name)
            f.write(b"RIFF" + b"\x00" * 100)  # Minimal WAV-like header

        try:
            result = remove_artwork(wav_path)
            assert not result.success
            assert "Unsupported format" in result.error
        finally:
            wav_path.unlink(missing_ok=True)

    def test_remove_artwork_nonexistent_file(self):
        """Test clearing artwork from non-existent file."""
        result = remove_artwork(Path("/nonexistent/file.mp3"))
        assert not result.success
        assert "File not found" in result.error


class TestMetadataRoundtrip:
    """Tests for metadata roundtrip (write then read back)."""

    def test_full_roundtrip_mp3(self, mp3_file):
        """Test full metadata roundtrip for MP3."""
        original = {
            "title": "Roundtrip Title",
            "artist": "Roundtrip Artist",
            "album": "Roundtrip Album",
            "album_artist": "Roundtrip Album Artist",
            "genre": "Ambient",
            "year": "2023",
            "track_number": "3",
            "disc_number": "1",
            "composer": "Test Composer",
            "comment": "Test comment",
        }

        result = write_metadata(mp3_file, original)
        assert result.success

        # Read back and verify
        audio = ID3(mp3_file)
        assert str(audio.get("TIT2")) == "Roundtrip Title"
        assert str(audio.get("TPE1")) == "Roundtrip Artist"
        assert str(audio.get("TALB")) == "Roundtrip Album"
        assert str(audio.get("TPE2")) == "Roundtrip Album Artist"
        assert str(audio.get("TCON")) == "Ambient"
        assert str(audio.get("TDRC")) == "2023"
        assert "3" in str(audio.get("TRCK"))
        assert "1" in str(audio.get("TPOS"))
        assert str(audio.get("TCOM")) == "Test Composer"
