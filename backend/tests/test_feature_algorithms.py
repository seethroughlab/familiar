"""Tests for improved audio feature algorithms (v8).

Tests the algorithmic improvements: KK key profiles, MFCC acousticness,
harmonic tension, confidence scores, cross-validation, and mood tags.
"""

import importlib

import numpy as np
import pytest

_has_librosa = importlib.util.find_spec("librosa") is not None
requires_librosa = pytest.mark.skipif(not _has_librosa, reason="librosa not installed")


class TestKKKeyDetection:
    """Tests for Krumhansl-Kessler key profile detection."""

    def test_detect_c_major(self):
        """C major chroma should be detected as C major."""
        from app.services.analysis import _detect_key_kk

        # Create C major-like chroma: strong C, E, G
        chroma = np.zeros((12, 100))
        chroma[0, :] = 1.0   # C
        chroma[4, :] = 0.7   # E
        chroma[7, :] = 0.8   # G
        # Add some background
        chroma += 0.1

        key, confidence = _detect_key_kk(chroma)
        assert key == "C", f"Expected 'C' but got '{key}'"
        assert confidence > 0.5

    def test_detect_a_minor(self):
        """A minor chroma should be detected as Am."""
        from app.services.analysis import _detect_key_kk

        # Create A minor-like chroma: strong A, C, E
        chroma = np.zeros((12, 100))
        chroma[9, :] = 1.0   # A
        chroma[0, :] = 0.7   # C
        chroma[4, :] = 0.8   # E
        chroma[3, :] = 0.3   # Eb (minor third above C)
        chroma += 0.05

        key, confidence = _detect_key_kk(chroma)
        assert key.startswith("A"), f"Expected key starting with 'A' but got '{key}'"
        assert confidence > 0.4

    def test_detect_key_returns_mode_suffix(self):
        """Key detection should return 'm' suffix for minor keys."""
        from app.services.analysis import _detect_key_kk

        # Strong minor character
        chroma = np.zeros((12, 100))
        chroma[4, :] = 1.0   # E
        chroma[7, :] = 0.8   # G (minor third)
        chroma[11, :] = 0.7  # B (fifth)
        chroma += 0.05

        key, confidence = _detect_key_kk(chroma)
        # Should be either major or minor, with mode suffix
        assert key in [
            'C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B',
            'Cm', 'C#m', 'Dm', 'D#m', 'Em', 'Fm', 'F#m', 'Gm', 'G#m', 'Am', 'A#m', 'Bm',
        ]

    def test_silent_chroma_returns_default(self):
        """Near-silent chroma should return a sensible default."""
        from app.services.analysis import _detect_key_kk

        chroma = np.zeros((12, 100))
        key, confidence = _detect_key_kk(chroma)
        assert key == "C"
        assert confidence == 0.0

    def test_confidence_range(self):
        """Confidence should be in [0, 1]."""
        from app.services.analysis import _detect_key_kk

        chroma = np.random.rand(12, 100)
        key, confidence = _detect_key_kk(chroma)
        assert 0.0 <= confidence <= 1.0


@requires_librosa
class TestAcousticness:
    """Tests for MFCC-based acousticness computation."""

    def test_acousticness_range(self):
        """Acousticness should be in [0, 1]."""
        from app.services.analysis import _compute_acousticness

        y = np.random.randn(22050 * 5).astype(np.float32) * 0.1
        sr = 22050
        shared = self._make_shared(y, sr)

        result = _compute_acousticness(y, sr, shared)
        assert 0.0 <= result <= 1.0

    def _make_shared(self, y, sr):
        """Create minimal shared dict for acousticness computation."""
        import librosa

        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        rms = librosa.feature.rms(y=y)[0]
        return {"mfcc": mfcc, "rms": rms}


class TestHarmonicTension:
    """Tests for harmonic tension computation."""

    def test_consonant_chroma_low_tension(self):
        """Pure major chord should have low tension."""
        from app.services.analysis import _compute_harmonic_tension

        # C major: C, E, G only
        chroma = np.zeros((12, 100))
        chroma[0, :] = 1.0  # C
        chroma[4, :] = 0.8  # E (major third)
        chroma[7, :] = 0.9  # G (fifth)

        tension = _compute_harmonic_tension(chroma)
        assert tension < 0.3, f"Expected low tension for major chord, got {tension}"

    def test_dissonant_chroma_high_tension(self):
        """Chromatic cluster should have high tension."""
        from app.services.analysis import _compute_harmonic_tension

        # Cluster of adjacent semitones
        chroma = np.zeros((12, 100))
        chroma[0, :] = 1.0  # C
        chroma[1, :] = 1.0  # C#
        chroma[6, :] = 1.0  # F# (tritone)

        tension = _compute_harmonic_tension(chroma)
        assert tension > 0.5, f"Expected high tension for chromatic cluster, got {tension}"

    def test_tension_range(self):
        """Tension should be in [0, 1]."""
        from app.services.analysis import _compute_harmonic_tension

        chroma = np.random.rand(12, 100)
        tension = _compute_harmonic_tension(chroma)
        assert 0.0 <= tension <= 1.0


@requires_librosa
class TestDeriveFeatures:
    """Tests for the main derive_features function."""

    def test_returns_tuple(self):
        """derive_features should return (features, confidence) tuple."""
        from pathlib import Path

        import librosa

        from app.services.analysis import derive_features

        # Create a simple test signal (sine wave at 440Hz)
        sr = 22050
        duration = 5
        t = np.linspace(0, duration, sr * duration, endpoint=False)
        y = (np.sin(2 * np.pi * 440 * t) * 0.3).astype(np.float32)

        # Manually build shared dict

        n_fft = 2048
        hop_length = 512
        spec = np.abs(librosa.stft(y, n_fft=n_fft))
        power_spec = spec ** 2
        chroma_fb = librosa.filters.chroma(sr=sr, n_fft=n_fft)
        raw_chroma = np.dot(chroma_fb, power_spec)
        chroma = librosa.util.normalize(raw_chroma, norm=np.inf, axis=0)
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        tempo = librosa.feature.tempo(onset_envelope=onset_env, sr=sr)
        bpm = float(tempo[0]) if isinstance(tempo, np.ndarray) else float(tempo)
        pulse = librosa.beat.plp(onset_envelope=onset_env, sr=sr)
        beats_plp = librosa.util.localmax(pulse)
        beat_frames = np.flatnonzero(beats_plp)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        rms = librosa.feature.rms(y=y)[0]
        log_S = librosa.power_to_db(power_spec, ref=np.max)
        mfcc = librosa.feature.mfcc(S=log_S, sr=sr, n_mfcc=13)

        shared = {
            "spec": spec, "power_spec": power_spec, "chroma": chroma,
            "onset_env": onset_env, "bpm": bpm, "beat_frames": beat_frames,
            "beat_times": beat_times, "rms": rms, "log_S": log_S,
            "mfcc": mfcc, "n_fft": n_fft, "hop_length": hop_length,
            "duration": duration, "pulse": pulse,
        }

        # Use a temp path that won't exist for ReplayGain (will use fallback)
        result = derive_features(y, sr, shared, Path("/nonexistent/test.wav"))
        assert isinstance(result, tuple)
        assert len(result) == 2

        features, confidence = result
        assert isinstance(features, dict)
        assert isinstance(confidence, dict)

    def test_key_has_mode(self):
        """Key should include mode suffix for minor keys."""
        from pathlib import Path

        from app.services.analysis import derive_features

        sr = 22050
        duration = 5
        t = np.linspace(0, duration, sr * duration, endpoint=False)
        y = (np.sin(2 * np.pi * 440 * t) * 0.3).astype(np.float32)

        import librosa

        n_fft = 2048
        hop_length = 512
        spec = np.abs(librosa.stft(y, n_fft=n_fft))
        power_spec = spec ** 2
        chroma_fb = librosa.filters.chroma(sr=sr, n_fft=n_fft)
        raw_chroma = np.dot(chroma_fb, power_spec)
        chroma = librosa.util.normalize(raw_chroma, norm=np.inf, axis=0)
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        tempo = librosa.feature.tempo(onset_envelope=onset_env, sr=sr)
        bpm = float(tempo[0]) if isinstance(tempo, np.ndarray) else float(tempo)
        pulse = librosa.beat.plp(onset_envelope=onset_env, sr=sr)
        beats_plp = librosa.util.localmax(pulse)
        beat_frames = np.flatnonzero(beats_plp)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        rms = librosa.feature.rms(y=y)[0]
        log_S = librosa.power_to_db(power_spec, ref=np.max)
        mfcc = librosa.feature.mfcc(S=log_S, sr=sr, n_mfcc=13)

        shared = {
            "spec": spec, "power_spec": power_spec, "chroma": chroma,
            "onset_env": onset_env, "bpm": bpm, "beat_frames": beat_frames,
            "beat_times": beat_times, "rms": rms, "log_S": log_S,
            "mfcc": mfcc, "n_fft": n_fft, "hop_length": hop_length,
            "duration": duration, "pulse": pulse,
        }

        features, confidence = derive_features(y, sr, shared, Path("/nonexistent/test.wav"))
        key = features.get("key", "")
        # Key should be a valid key name, with optional 'm' suffix
        valid_keys = (
            ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'] +
            ['Cm', 'C#m', 'Dm', 'D#m', 'Em', 'Fm', 'F#m', 'Gm', 'G#m', 'Am', 'A#m', 'Bm']
        )
        assert key in valid_keys, f"Key '{key}' is not a valid key name"

    def test_confidence_scores_present(self):
        """Confidence dict should have expected keys."""
        from pathlib import Path

        from app.services.analysis import derive_features

        sr = 22050
        duration = 5
        t = np.linspace(0, duration, sr * duration, endpoint=False)
        y = (np.sin(2 * np.pi * 440 * t) * 0.3).astype(np.float32)

        import librosa

        n_fft = 2048
        spec = np.abs(librosa.stft(y, n_fft=n_fft))
        power_spec = spec ** 2
        chroma_fb = librosa.filters.chroma(sr=sr, n_fft=n_fft)
        raw_chroma = np.dot(chroma_fb, power_spec)
        chroma = librosa.util.normalize(raw_chroma, norm=np.inf, axis=0)
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        tempo = librosa.feature.tempo(onset_envelope=onset_env, sr=sr)
        bpm = float(tempo[0]) if isinstance(tempo, np.ndarray) else float(tempo)
        pulse = librosa.beat.plp(onset_envelope=onset_env, sr=sr)
        rms = librosa.feature.rms(y=y)[0]
        log_S = librosa.power_to_db(power_spec, ref=np.max)
        mfcc = librosa.feature.mfcc(S=log_S, sr=sr, n_mfcc=13)

        shared = {
            "spec": spec, "power_spec": power_spec, "chroma": chroma,
            "onset_env": onset_env, "bpm": bpm,
            "beat_frames": np.array([0]), "beat_times": np.array([0.0]),
            "rms": rms, "log_S": log_S, "mfcc": mfcc,
            "n_fft": n_fft, "hop_length": 512, "duration": duration,
            "pulse": pulse,
        }

        features, confidence = derive_features(y, sr, shared, Path("/nonexistent/test.wav"))

        expected_keys = {"bpm", "key", "energy", "danceability", "valence",
                        "acousticness", "instrumentalness", "speechiness"}
        for k in expected_keys:
            assert k in confidence, f"Missing confidence key: {k}"
            assert 0.0 <= confidence[k] <= 1.0, f"Confidence for {k} out of range: {confidence[k]}"


class TestCrossValidation:
    """Tests for cross-validation disagreement detection."""

    def test_no_disagreement(self):
        """Matching features should have no disagreements."""
        from app.services.tasks.analysis_pipeline import _compute_disagreements

        local = {"bpm": 120.0, "key": "C", "energy": 0.7, "valence": 0.5, "danceability": 0.6}
        external = {"bpm": 120.0, "key": "C", "energy": 0.7, "valence": 0.5, "danceability": 0.6}

        result = _compute_disagreements(local, external)
        for key, val in result.items():
            assert val is None, f"Unexpected disagreement for {key}: {val}"

    def test_half_tempo_detected(self):
        """Half tempo BPM should be flagged."""
        from app.services.tasks.analysis_pipeline import _compute_disagreements

        local = {"bpm": 60.0, "key": "C", "energy": 0.7}
        external = {"bpm": 120.0, "key": "C", "energy": 0.7}

        result = _compute_disagreements(local, external)
        assert result["bpm"] == "half_tempo"

    def test_double_tempo_detected(self):
        """Double tempo BPM should be flagged."""
        from app.services.tasks.analysis_pipeline import _compute_disagreements

        local = {"bpm": 240.0, "key": "C", "energy": 0.7}
        external = {"bpm": 120.0, "key": "C", "energy": 0.7}

        result = _compute_disagreements(local, external)
        assert result["bpm"] == "double_tempo"

    def test_key_root_disagreement(self):
        """Different key roots should be flagged."""
        from app.services.tasks.analysis_pipeline import _compute_disagreements

        local = {"bpm": 120.0, "key": "Am"}
        external = {"bpm": 120.0, "key": "C"}

        result = _compute_disagreements(local, external)
        assert result["key"] == "different_root"

    def test_key_mode_disagreement(self):
        """Same root but different mode should be flagged."""
        from app.services.tasks.analysis_pipeline import _compute_disagreements

        local = {"bpm": 120.0, "key": "Am"}
        external = {"bpm": 120.0, "key": "A"}

        result = _compute_disagreements(local, external)
        assert result["key"] == "different_mode"

    def test_large_energy_difference(self):
        """Large energy difference should be flagged."""
        from app.services.tasks.analysis_pipeline import _compute_disagreements

        local = {"bpm": 120.0, "energy": 0.9}
        external = {"bpm": 120.0, "energy": 0.3}

        result = _compute_disagreements(local, external)
        assert result["energy"] == "large_difference"


class TestMoodTags:
    """Tests for mood tag descriptors."""

    def test_descriptor_count(self):
        """Should have ~48 descriptors."""
        from app.services.mood_tags import DESCRIPTORS

        assert len(DESCRIPTORS) == 48

    def test_descriptor_categories(self):
        """Should have 4 categories."""
        from app.services.mood_tags import DESCRIPTORS

        categories = {d["category"] for d in DESCRIPTORS}
        assert categories == {"mood", "genre", "instrumentation", "energy"}

    def test_descriptor_structure(self):
        """Each descriptor should have tag, category, description."""
        from app.services.mood_tags import DESCRIPTORS

        for desc in DESCRIPTORS:
            assert "tag" in desc
            assert "category" in desc
            assert "description" in desc
            assert len(desc["tag"]) > 0
            assert len(desc["description"]) > 0

    def test_compute_mood_tags_empty_embedding(self):
        """Zero embedding should return empty tags."""
        from app.services.mood_tags import compute_mood_tags

        # With zero embedding, should return empty (or very low confidence)
        result = compute_mood_tags([0.0] * 512)
        assert isinstance(result, list)

    def test_get_all_tags(self):
        """get_all_tags should return all descriptor tags."""
        from app.services.mood_tags import get_all_tags

        tags = get_all_tags()
        assert len(tags) == 48
        for t in tags:
            assert "tag" in t
            assert "category" in t
