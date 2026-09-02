"""Tests for the audio analysis service.

Tests cover feature extraction, embedding generation, and fingerprinting.
Uses the existing MP3 fixture for real audio analysis.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("librosa")

from app.services.analysis import (
    AnalysisError,
    extract_features,
    generate_fingerprint,
    get_analysis_capabilities,
)

# Path to test audio fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


class TestExtractFeatures:
    """Tests for audio feature extraction."""

    def test_extract_features_returns_expected_keys(self):
        """Verify all expected feature keys are present."""
        audio_file = FIXTURES_DIR / "electronic_short.mp3"
        if not audio_file.exists():
            pytest.skip("Audio fixture not available")

        features = extract_features(audio_file)

        expected_keys = {
            "bpm",
            "key",
            "energy",
            "danceability",
            "acousticness",
            "instrumentalness",
            "valence",
            "speechiness",
            "loudness_lufs",
            "track_peak",
            "replaygain_track_gain",
        }
        assert set(features.keys()) == expected_keys

    def test_extract_features_bpm_in_valid_range(self):
        """BPM should be within reasonable musical range."""
        audio_file = FIXTURES_DIR / "electronic_short.mp3"
        if not audio_file.exists():
            pytest.skip("Audio fixture not available")

        features = extract_features(audio_file)

        assert features["bpm"] is not None
        assert 40 <= features["bpm"] <= 220, f"BPM {features['bpm']} out of range"

    def test_extract_features_normalized_values(self):
        """Normalized features should be between 0 and 1."""
        audio_file = FIXTURES_DIR / "electronic_short.mp3"
        if not audio_file.exists():
            pytest.skip("Audio fixture not available")

        features = extract_features(audio_file)

        normalized_features = [
            "energy",
            "danceability",
            "acousticness",
            "instrumentalness",
            "valence",
            "speechiness",
        ]
        for feature in normalized_features:
            value = features[feature]
            assert value is not None, f"{feature} should not be None"
            assert 0 <= value <= 1, f"{feature}={value} not in [0,1]"

    def test_extract_features_key_is_valid(self):
        """Key should be a valid musical key."""
        audio_file = FIXTURES_DIR / "electronic_short.mp3"
        if not audio_file.exists():
            pytest.skip("Audio fixture not available")

        features = extract_features(audio_file)

        valid_keys = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        assert features["key"] in valid_keys, f"Invalid key: {features['key']}"

    def test_extract_features_consistency(self):
        """Same file should produce consistent results."""
        audio_file = FIXTURES_DIR / "electronic_short.mp3"
        if not audio_file.exists():
            pytest.skip("Audio fixture not available")

        features1 = extract_features(audio_file)
        features2 = extract_features(audio_file)

        # BPM and key should be exactly the same
        assert features1["bpm"] == features2["bpm"]
        assert features1["key"] == features2["key"]

        # Other features should be very close (floating point)
        for key in ["energy", "danceability", "valence"]:
            assert abs(features1[key] - features2[key]) < 0.01

    def test_extract_features_different_files_vary(self):
        """Different audio files should have different features."""
        file1 = FIXTURES_DIR / "electronic_short.mp3"
        file2 = FIXTURES_DIR / "artist1" / "album1" / "ambient_loop.mp3"

        if not file1.exists() or not file2.exists():
            pytest.skip("Audio fixtures not available")

        features1 = extract_features(file1)
        features2 = extract_features(file2)

        # At least some features should differ between different tracks
        differences = 0
        for key in ["bpm", "key", "energy", "danceability"]:
            if features1[key] != features2[key]:
                differences += 1

        assert differences >= 1, "Different tracks should have different features"

    def test_extract_features_nonexistent_file_raises(self):
        """Should raise AnalysisError for non-existent file."""
        with pytest.raises(AnalysisError):
            extract_features(Path("/nonexistent/file.mp3"))


class TestGenerateFingerprint:
    """Tests for AcoustID fingerprint generation."""

    def test_generate_fingerprint_returns_tuple(self):
        """Fingerprint should return (duration, fingerprint) tuple."""
        audio_file = FIXTURES_DIR / "electronic_short.mp3"
        if not audio_file.exists():
            pytest.skip("Audio fixture not available")

        result = generate_fingerprint(audio_file)

        # Result could be None if chromaprint not installed
        if result is not None:
            duration, fingerprint = result
            assert isinstance(duration, (int, float))
            assert duration > 0
            assert isinstance(fingerprint, str)
            assert len(fingerprint) > 0

    def test_generate_fingerprint_consistent(self):
        """Same file should produce same fingerprint."""
        audio_file = FIXTURES_DIR / "electronic_short.mp3"
        if not audio_file.exists():
            pytest.skip("Audio fixture not available")

        result1 = generate_fingerprint(audio_file)
        result2 = generate_fingerprint(audio_file)

        if result1 is not None and result2 is not None:
            assert result1[1] == result2[1], "Fingerprints should match"

    def test_generate_fingerprint_nonexistent_file(self):
        """Should return None for non-existent file."""
        result = generate_fingerprint(Path("/nonexistent/file.mp3"))
        assert result is None


class TestGetAnalysisCapabilities:
    """Tests for analysis capability detection."""

    def test_get_analysis_capabilities_returns_dict(self):
        """Should return dict with expected keys."""
        caps = get_analysis_capabilities()

        assert isinstance(caps, dict)
        assert "embeddings_enabled" in caps
        assert "embeddings_disabled_reason" in caps
        assert "features_enabled" in caps
        assert "clap_status" in caps

    def test_features_always_enabled(self):
        """Librosa features should always be enabled."""
        caps = get_analysis_capabilities()
        assert caps["features_enabled"] is True

    def test_embeddings_disabled_reason_when_disabled(self):
        """Should provide reason when embeddings are disabled."""
        caps = get_analysis_capabilities()

        if not caps["embeddings_enabled"]:
            assert caps["embeddings_disabled_reason"] is not None
            assert isinstance(caps["embeddings_disabled_reason"], str)


# `TestGetDevice` is gone with ADR-0105. Device selection is no longer Familiar's:
# `clapback-embed` picks execution providers from CLAPBACK_PROVIDERS, and what
# matters is not which was *requested* but which actually bound — asserted in
# tests/test_embedder_delegation.py, which unlike this file runs in CI.


class TestExtractEmbedding:
    """Tests for CLAP embedding extraction."""

    def test_extract_embedding_returns_none_without_torch(self):
        """Should return None when torch is unavailable."""
        from app.services.analysis import extract_embedding

        with patch("app.services.analysis._torch_available", False):
            audio_file = FIXTURES_DIR / "electronic_short.mp3"
            if not audio_file.exists():
                pytest.skip("Audio fixture not available")

            result = extract_embedding(audio_file)
            assert result is None

    def test_extract_embedding_returns_none_when_disabled(self):
        """Should return None when CLAP is disabled in settings."""
        from app.services.analysis import extract_embedding

        mock_settings_service = MagicMock()
        mock_settings_service.is_clap_embeddings_enabled.return_value = (False, "Disabled by user")

        with patch("app.services.analysis._torch_available", True):
            with patch(
                "app.services.app_settings.get_app_settings_service",
                return_value=mock_settings_service,
            ):
                audio_file = FIXTURES_DIR / "electronic_short.mp3"
                if not audio_file.exists():
                    pytest.skip("Audio fixture not available")

                result = extract_embedding(audio_file)
                assert result is None


class TestFeatureValues:
    """Tests for specific feature value characteristics."""

    @pytest.fixture
    def electronic_features(self):
        """Extract features from electronic track."""
        audio_file = FIXTURES_DIR / "electronic_short.mp3"
        if not audio_file.exists():
            pytest.skip("Audio fixture not available")
        return extract_features(audio_file)

    def test_electronic_track_has_moderate_energy(self, electronic_features):
        """Electronic music typically has moderate to high energy."""
        # Electronic music usually has measurable energy
        assert electronic_features["energy"] > 0.1

    def test_electronic_track_has_danceability(self, electronic_features):
        """Electronic music typically has some danceability."""
        # Should have some rhythmic content
        assert electronic_features["danceability"] > 0

    def test_electronic_track_instrumentalness(self, electronic_features):
        """Electronic music is often instrumental."""
        # May or may not be instrumental, but should have a value
        assert electronic_features["instrumentalness"] is not None


class TestMultipleFiles:
    """Tests that work with multiple audio files."""

    def test_all_fixtures_can_be_analyzed(self):
        """All fixture files should be analyzable without errors."""
        mp3_files = list(FIXTURES_DIR.rglob("*.mp3"))
        if not mp3_files:
            pytest.skip("No audio fixtures available")

        analyzed = 0
        skipped = 0
        for mp3_file in mp3_files[:5]:  # Limit to 5 files for speed
            try:
                features = extract_features(mp3_file)
                assert features is not None
                assert features["bpm"] is not None
                analyzed += 1
            except AnalysisError:
                # Some CI environments lack audio codecs (libsndfile/ffmpeg)
                # needed to decode certain MP3 fixtures — skip gracefully
                skipped += 1

        assert analyzed > 0, f"Should have analyzed at least one file (skipped {skipped})"
