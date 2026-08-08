"""Tests for silero-vad speech detection.

These exist because of a specific, silent failure. The ONNX model download URL tracks
`master`, silero-vad moved from v4 to v5, and the v5 model takes a single `state` input
where v4 took `h` and `c`. Every `session.run` raised, a per-window `except: continue`
swallowed all of them, and `detect_speech` returned `(0.0, 0.0)` — which the caller turned
into `instrumentalness=1.0, speechiness=0.0`.

That is a plausible-looking measurement, so nothing looked broken: **25,661 of 25,697
analysed tracks were recorded as fully instrumental with no speech.**

The tests below fake the ONNX session rather than loading a real model, so they run
anywhere and assert the two things that actually failed: that both signatures are driven
correctly, and that a total failure is raised rather than returned.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services import vocal_detection
from app.services.vocal_detection import VADError, detect_speech

SR = 16000
AUDIO = np.zeros(SR * 2, dtype=np.float32)  # 2s -> 62 windows of 512


class _FakeInput:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeSession:
    """Stands in for onnxruntime.InferenceSession.

    `input_names` decides which signature it advertises; `accepts` decides which it will
    actually run. Setting them differently is exactly the production bug.
    """

    def __init__(self, input_names: list[str], accepts: set[str] | None = None, prob: float = 0.8):
        self._inputs = [_FakeInput(n) for n in input_names]
        self._accepts = accepts if accepts is not None else set(input_names)
        self._prob = prob
        self.calls = 0

    def get_inputs(self) -> list[_FakeInput]:
        return self._inputs

    def run(self, _outputs, feed: dict) -> tuple:
        if set(feed) != self._accepts:
            raise RuntimeError(f"unexpected inputs {sorted(feed)}; wants {sorted(self._accepts)}")
        self.calls += 1
        out = np.array([[self._prob]], dtype=np.float32)
        if "state" in self._accepts:
            return out, feed["state"]
        return out, feed["h"], feed["c"]


@pytest.fixture(autouse=True)
def _no_real_model(monkeypatch):
    """Never touch the network or a real model file."""
    monkeypatch.setattr(vocal_detection, "_load_vad_model", lambda: None)


def _use(monkeypatch, session):
    monkeypatch.setattr(vocal_detection, "_load_vad_model", lambda: session)


def test_v5_signature_is_driven_with_state(monkeypatch):
    """The regression. A v5 model must be fed `state`, not `h`/`c`."""
    session = _FakeSession(["input", "state", "sr"], prob=0.8)
    _use(monkeypatch, session)

    mean_prob, speech_fraction = detect_speech(AUDIO, SR)

    assert session.calls > 0, "no window was ever run against the model"
    assert mean_prob == pytest.approx(0.8)
    assert speech_fraction == pytest.approx(1.0)


def test_v4_signature_still_works(monkeypatch):
    """Installs that already hold a v4 model must keep working."""
    session = _FakeSession(["input", "h", "c", "sr"], prob=0.9)
    _use(monkeypatch, session)

    mean_prob, _ = detect_speech(AUDIO, SR)

    assert session.calls > 0
    assert mean_prob == pytest.approx(0.9)


def test_total_failure_raises_instead_of_reporting_silence(monkeypatch):
    """The heart of it.

    A model that advertises v5 but rejects every call must not yield `(0.0, 0.0)` —
    that value is indistinguishable from a confident 'this track is pure instrumental'.
    """
    session = _FakeSession(["input", "state", "sr"], accepts={"input", "h", "c", "sr"})
    _use(monkeypatch, session)

    with pytest.raises(VADError):
        detect_speech(AUDIO, SR)


def test_unknown_signature_raises(monkeypatch):
    """A future v6 that renames the state input again should fail loudly on arrival."""
    session = _FakeSession(["input", "memory", "sr"])
    _use(monkeypatch, session)

    with pytest.raises(VADError):
        detect_speech(AUDIO, SR)


def test_missing_model_returns_none_not_error(monkeypatch):
    """'No model' is a legitimate state and keeps the spectral fallback available.

    This is the distinction VADError exists to draw: absent is not the same as broken.
    """
    _use(monkeypatch, None)
    assert detect_speech(AUDIO, SR) is None


def test_one_bad_window_does_not_lose_the_track(monkeypatch):
    """A single malformed window is tolerable; the result should still be computed."""
    session = _FakeSession(["input", "state", "sr"], prob=0.6)
    real_run = session.run
    state = {"n": 0}

    def flaky(outputs, feed):
        state["n"] += 1
        if state["n"] == 3:
            raise RuntimeError("bad window")
        return real_run(outputs, feed)

    session.run = flaky  # type: ignore[method-assign]
    _use(monkeypatch, session)

    mean_prob, _ = detect_speech(AUDIO, SR)
    assert mean_prob == pytest.approx(0.6)


def test_audio_shorter_than_one_window_returns_zero(monkeypatch):
    """Pre-existing behaviour, pinned so the VADError change does not alter it."""
    _use(monkeypatch, _FakeSession(["input", "state", "sr"]))
    assert detect_speech(np.zeros(100, dtype=np.float32), SR) == (0.0, 0.0)
