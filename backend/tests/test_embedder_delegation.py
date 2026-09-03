"""ADR-0105: Familiar delegates CLAP to `clapback-embed` and owns none of it.

**This file used to test the windowing itself.** Those tests moved with the code:
the rule (consecutive 480,000-sample windows, drop the tail, `repeatpad` below one
window, mean-pool raw outputs then normalise) is now the package's, and it is
tested there against the same boundary cases plus a conformance check against
`transformers` that Familiar's suite could never run.

What is left is the part that is still Familiar's problem — that it calls the
package rather than reimplementing it, that its guards still short-circuit, and
that a silent CPU fallback is visible rather than invisible.

Deliberately free of `librosa`, `torch` and the ONNX artifacts: CI runs
`uv sync --extra dev`, which installs none of them, so anything requiring them
would be skipped here and prove nothing.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import app.services.analysis as analysis


@pytest.fixture
def clap_enabled():
    settings = MagicMock()
    settings.is_clap_embeddings_enabled.return_value = (True, "")
    with patch("app.services.analysis._embedder_available", True), patch(
        "app.services.app_settings.get_app_settings_service", return_value=settings
    ):
        yield


def _fake_package(*, audio=None, text=None, providers=("CPUExecutionProvider",)):
    """A stand-in `clapback_embed`, so these tests need no ONNX artifacts."""
    mod = types.ModuleType("clapback_embed")
    mod.embed_file = MagicMock(return_value=list(audio or [0.1] * 512))
    mod.embed_text = MagicMock(return_value=list(text or [0.2] * 512))
    artifacts = types.ModuleType("clapback_embed.artifacts")
    artifacts.providers = MagicMock(return_value=list(providers))
    session = MagicMock()
    session.get_providers.return_value = list(providers)
    artifacts.audio_session = MagicMock(return_value=session)
    return {"clapback_embed": mod, "clapback_embed.artifacts": artifacts}


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------


def test_audio_embedding_is_the_packages_answer_unmodified(clap_enabled):
    """Familiar must not post-process the vector.

    Re-normalising, rounding or truncating here would make its contributions
    incomparable with every other client's while still looking correct.
    """
    expected = [0.5] * 512
    pkg = _fake_package(audio=expected)
    with patch.dict(sys.modules, pkg):
        got = analysis.extract_embedding(Path("track.mp3"))
    assert got == expected
    pkg["clapback_embed"].embed_file.assert_called_once()


def test_text_embedding_is_the_packages_answer_unmodified(clap_enabled):
    expected = [0.25] * 512
    pkg = _fake_package(text=expected)
    with patch.dict(sys.modules, pkg):
        got = analysis.extract_text_embedding("gloomy with Eastern influences")
    assert got == expected
    pkg["clapback_embed"].embed_text.assert_called_once_with(
        "gloomy with Eastern influences"
    )


def test_familiar_no_longer_implements_any_of_the_pipeline():
    """The guard on ADR-0105's actual decision.

    Reintroducing a local mel, window loop or model load here is exactly how two
    implementations start to drift, and the drift is invisible: both produce 512
    plausible floats.
    """
    source = Path(analysis.__file__).read_text()
    for banned in ("import torch", "from transformers", "def load_clap_model", "def get_device"):
        assert banned not in source, f"{banned!r} is back in analysis.py"


# ---------------------------------------------------------------------------
# Guards still short-circuit
# ---------------------------------------------------------------------------


def test_missing_package_returns_none_rather_than_raising():
    with patch("app.services.analysis._embedder_available", False):
        assert analysis.extract_embedding(Path("track.mp3")) is None
        assert analysis.extract_text_embedding("anything") is None


def test_disabled_clap_never_reaches_the_package():
    settings = MagicMock()
    settings.is_clap_embeddings_enabled.return_value = (False, "Disabled by user")
    pkg = _fake_package()
    with patch("app.services.analysis._embedder_available", True), patch(
        "app.services.app_settings.get_app_settings_service", return_value=settings
    ), patch.dict(sys.modules, pkg):
        assert analysis.extract_embedding(Path("track.mp3")) is None
    pkg["clapback_embed"].embed_file.assert_not_called()


def test_an_embedding_failure_is_raised_not_swallowed(clap_enabled):
    """A failed embedding must not look like a disabled one."""
    pkg = _fake_package()
    pkg["clapback_embed"].embed_file.side_effect = RuntimeError("artifacts missing")
    with patch.dict(sys.modules, pkg):
        with pytest.raises(analysis.AnalysisError, match="Embedding extraction failed"):
            analysis.extract_embedding(Path("track.mp3"))


# ---------------------------------------------------------------------------
# The silent-fallback trap
# ---------------------------------------------------------------------------


def test_requested_and_active_providers_are_reported_separately():
    """ONNX Runtime falls back to CPU *silently* when a provider fails to load.

    Four wrong CUDA stacks were tried while writing ADR-0105 and every one of them
    ran, returned correct vectors and reported success — on the CPU. "CUDA was
    requested" and "CUDA is running" are different facts, so the health surface
    reports both rather than the first.
    """
    pkg = _fake_package(providers=("CPUExecutionProvider",))
    pkg["clapback_embed.artifacts"].providers.return_value = [
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]
    with patch("app.services.analysis._embedder_available", True), patch.dict(
        sys.modules, pkg
    ):
        assert analysis.embedder_providers() == [
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]
        # ...but only CPU actually bound. That difference is the whole point.
        assert analysis.embedder_active_providers() == ["CPUExecutionProvider"]


def test_unusable_artifacts_report_no_active_providers_instead_of_raising():
    """Health reporting must survive a broken embedder."""
    pkg = _fake_package()
    pkg["clapback_embed.artifacts"].audio_session.side_effect = RuntimeError("no models")
    with patch("app.services.analysis._embedder_available", True), patch.dict(
        sys.modules, pkg
    ):
        assert analysis.embedder_active_providers() == []


def test_providers_are_empty_when_the_package_is_absent():
    with patch("app.services.analysis._embedder_available", False):
        assert analysis.embedder_providers() == []
        assert analysis.embedder_active_providers() == []
