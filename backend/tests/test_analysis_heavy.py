"""Heavy tests for audio analysis that use real PyTorch and CLAP.

These tests download the CLAP model (~1.5GB) and run actual inference.
Skipped by default — set FAMILIAR_HEAVY_TESTS=1 to enable.

    FAMILIAR_HEAVY_TESTS=1 uv run pytest tests/test_analysis_heavy.py -v
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("FAMILIAR_HEAVY_TESTS") != "1",
    reason="Heavy tests require FAMILIAR_HEAVY_TESTS=1 (downloads 1.5GB CLAP model)",
)

pytest.importorskip("torch")
pytest.importorskip("librosa")

from app.services.analysis import (  # noqa: E402
    extract_embedding,
    extract_text_embedding,
    get_device,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


def _mock_clap_enabled():
    """Context manager that makes app_settings report CLAP as enabled."""
    mock_settings = MagicMock()
    mock_settings.is_clap_embeddings_enabled.return_value = (True, None)
    return patch(
        "app.services.app_settings.get_app_settings_service",
        return_value=mock_settings,
    )


class TestGetDeviceReal:
    """Test device detection with real torch (no mocks)."""

    def test_returns_valid_device(self):
        device = get_device()
        assert device in ("cpu", "cuda", "mps")

    def test_cpu_in_subprocess(self):
        """Subprocess workers should always get CPU (MPS is unreliable in forks)."""
        os.environ["FORKED_BY_MULTIPROCESSING"] = "1"
        try:
            device = get_device()
            assert device == "cpu"
        finally:
            del os.environ["FORKED_BY_MULTIPROCESSING"]


class TestExtractEmbeddingReal:
    """Test CLAP audio embedding extraction with real model."""

    def test_produces_512_dim_vector(self):
        audio_file = FIXTURES_DIR / "electronic_short.mp3"
        if not audio_file.exists():
            pytest.skip("Audio fixture not available")

        with _mock_clap_enabled():
            embedding = extract_embedding(audio_file)

        assert embedding is not None, "Expected embedding, got None"
        assert len(embedding) == 512, f"Expected 512-dim, got {len(embedding)}"
        assert all(isinstance(v, float) for v in embedding)

    def test_different_files_produce_different_embeddings(self):
        file1 = FIXTURES_DIR / "electronic_short.mp3"
        file2 = FIXTURES_DIR / "artist1" / "album1" / "ambient_loop.mp3"

        if not file1.exists() or not file2.exists():
            pytest.skip("Audio fixtures not available")

        with _mock_clap_enabled():
            emb1 = extract_embedding(file1)
            emb2 = extract_embedding(file2)

        assert emb1 is not None and emb2 is not None
        assert emb1 != emb2, "Different audio files should produce different embeddings"


class TestExtractTextEmbeddingReal:
    """Test CLAP text embedding extraction with real model."""

    def test_produces_512_dim_vector(self):
        with _mock_clap_enabled():
            embedding = extract_text_embedding("electronic ambient music")

        assert embedding is not None, "Expected embedding, got None"
        assert len(embedding) == 512, f"Expected 512-dim, got {len(embedding)}"
        assert all(isinstance(v, float) for v in embedding)


class TestEmbeddingCrossModal:
    """Test that audio and text embeddings live in the same space."""

    def test_same_dimensionality(self):
        audio_file = FIXTURES_DIR / "electronic_short.mp3"
        if not audio_file.exists():
            pytest.skip("Audio fixture not available")

        with _mock_clap_enabled():
            audio_emb = extract_embedding(audio_file)
            text_emb = extract_text_embedding("electronic music with a beat")

        assert audio_emb is not None and text_emb is not None
        assert len(audio_emb) == len(text_emb) == 512
