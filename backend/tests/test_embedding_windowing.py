"""ADR-0104: an embedding represents the whole track, not its middle ten seconds.

**Deliberately free of `librosa` and `torch`.** `tests/test_analysis.py` opens with
`pytest.importorskip("librosa")` and CI runs `uv sync --extra dev`, which installs
neither — so every test in that file is skipped in CI, including the only two that
mention `extract_embedding`. A regression in the windowing would reach production
with a green build.

These fake the two modules `extract_embedding` imports lazily, so the real function
runs under CI and what is asserted is the code that ships. They cover the arithmetic
and the window boundaries, not CLAP: the model's actual output is measured in
`ADR-0104` and cannot be reproduced without a 1.1 GB checkpoint.
"""

from __future__ import annotations

import contextlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.services.analysis import AnalysisError, extract_embedding

#: Stated here as literals rather than imported from the module under test. CLAP's
#: encoder accepts exactly 1001 mel frames at 48 kHz — ten seconds — so these are
#: properties of the checkpoint, and a test that imported them would follow a wrong
#: value instead of catching it.
SR = 48000
WINDOW = 480_000


def test_the_window_constant_matches_what_clap_accepts():
    """A guard on the number every other test here takes as given."""
    from app.services.analysis import EMBEDDING_WINDOW_SECONDS

    assert EMBEDDING_WINDOW_SECONDS == 10
    assert SR * EMBEDDING_WINDOW_SECONDS == WINDOW


class _FakeTensor:
    """Stands in for a torch tensor: it only ever has `.to(device)` called on it."""

    def __init__(self, value):
        self.value = value

    def to(self, _device):
        return self


class _FakeEmbedding:
    """Stands in for the model output: `.cpu().numpy().flatten()`."""

    def __init__(self, vector: np.ndarray):
        self._vector = np.asarray(vector, dtype=np.float64)

    def cpu(self):
        return self

    def numpy(self):
        return self._vector


@contextlib.contextmanager
def clap_stub(audio: np.ndarray, vectors: list[np.ndarray] | None = None):
    """Run `extract_embedding` against a fake CLAP, capturing every window handed over.

    Yields the list of audio chunks the processor received, so a test can assert
    both how many windows were produced and exactly which samples each covered.
    """
    seen: list[np.ndarray] = []

    fake_librosa = types.ModuleType("librosa")
    fake_librosa.load = lambda _path, sr=None, mono=True: (audio, sr or SR)  # type: ignore[attr-defined]

    fake_torch = types.ModuleType("torch")
    fake_torch.no_grad = contextlib.nullcontext  # type: ignore[attr-defined]

    def processor(audio=None, sampling_rate=None, return_tensors=None):
        seen.append(np.asarray(audio))
        return {"input_features": _FakeTensor(audio)}

    model = MagicMock()

    def get_audio_features(**_kwargs):
        if vectors is not None:
            return _FakeEmbedding(vectors[len(seen) - 1])
        # Distinct per window, so a mean cannot be mistaken for any single vector.
        return _FakeEmbedding(np.full(512, float(len(seen)), dtype=np.float64))

    model.get_audio_features.side_effect = get_audio_features

    settings = MagicMock()
    settings.is_clap_embeddings_enabled.return_value = (True, "")

    with patch.dict(sys.modules, {"librosa": fake_librosa, "torch": fake_torch}):
        with patch("app.services.analysis._torch_available", True):
            with patch(
                "app.services.app_settings.get_app_settings_service",
                return_value=settings,
            ):
                with patch(
                    "app.services.analysis.load_clap_model",
                    return_value=(model, processor),
                ):
                    with patch("app.services.analysis.get_device", return_value="cpu"):
                        yield seen


def _tone(n_samples: int, freq: float = 440.0) -> np.ndarray:
    """Deterministic non-silent audio of an exact length."""
    t = np.arange(n_samples, dtype=np.float64) / SR
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


# ---------------------------------------------------------------------------
# Window boundaries — the defect this file exists to catch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "seconds,expected_windows",
    [
        (6.66, 1),      # shorter than one window (`electronic_short.mp3`)
        (10.0, 1),      # exactly one
        (24.88, 2),     # `comedy_intro.mp3` — 4.88s dropped
        (28.55, 2),     # `orchestral_short.mp3`
        (37.36, 3),     # `ambient_loop.mp3`
        (143.02, 14),   # `celebration.mp3`
        (170.42, 17),   # `epic_boss_battle.mp3`
        (323.0, 32),    # the track ADR-0104's measurements were taken on
    ],
)
def test_window_count_matches_track_length(seconds, expected_windows):
    """A track is covered by floor(duration / 10) windows, and at least one.

    This is the assertion that fails if the middle-ten-seconds slice ever comes
    back: it would produce exactly one window for every input.
    """
    audio = _tone(int(seconds * SR))
    with clap_stub(audio) as seen:
        extract_embedding(Path("track.mp3"))
    assert len(seen) == expected_windows


def test_every_window_handed_to_clap_is_exactly_ten_seconds():
    """Reproducibility rests on this.

    `ClapFeatureExtractor` defaults to `truncation="rand_trunc"`, which takes a
    *random* crop of anything longer than one window. A chunk of the wrong length
    is not a rounding error — it makes the embedding irreproducible while still
    returning 512 plausible floats.
    """
    audio = _tone(int(143.02 * SR))
    with clap_stub(audio) as seen:
        extract_embedding(Path("track.mp3"))
    assert [len(chunk) for chunk in seen] == [WINDOW] * 14


def test_windows_are_consecutive_and_non_overlapping():
    audio = _tone(int(45.0 * SR))
    with clap_stub(audio) as seen:
        extract_embedding(Path("track.mp3"))
    assert len(seen) == 4
    for i, chunk in enumerate(seen):
        np.testing.assert_array_equal(chunk, audio[i * WINDOW:(i + 1) * WINDOW])


def test_trailing_partial_window_is_dropped_not_padded():
    """ADR-0104 point 3.

    Zero-padding the remainder would inject silence the track does not contain and
    pull the mean toward "quiet" in proportion to how short the remainder is. The
    tail is dropped instead, so nothing handed to CLAP is invented.
    """
    audio = _tone(int(24.88 * SR))
    with clap_stub(audio) as seen:
        extract_embedding(Path("track.mp3"))
    assert len(seen) == 2
    # Nothing beyond 20s was passed, and no zeros were appended to what was.
    np.testing.assert_array_equal(np.concatenate(seen), audio[: 2 * WINDOW])


def test_track_shorter_than_one_window_is_passed_through_whole():
    """Below one window there is nothing to drop.

    The short chunk goes to the extractor unchanged, so its own `repeatpad` applies
    rather than a second padding rule of ours.
    """
    audio = _tone(int(6.66 * SR))
    with clap_stub(audio) as seen:
        extract_embedding(Path("track.mp3"))
    assert len(seen) == 1
    np.testing.assert_array_equal(seen[0], audio)


# ---------------------------------------------------------------------------
# Pooling
# ---------------------------------------------------------------------------


def test_result_is_the_l2_normalised_mean_of_the_raw_window_vectors():
    """ADR-0104 point 2: mean of raw outputs, then normalise.

    Not a mean of already-normalised vectors. The two differ, and this is the one
    the ADR measured.
    """
    vectors = [
        np.concatenate([[3.0, 4.0], np.zeros(510)]),
        np.concatenate([[9.0, 12.0], np.zeros(510)]),
    ]
    audio = _tone(2 * WINDOW)
    with clap_stub(audio, vectors=vectors) as seen:
        result = extract_embedding(Path("track.mp3"))

    assert len(seen) == 2
    expected = np.mean(vectors, axis=0)
    expected = expected / np.linalg.norm(expected)
    np.testing.assert_allclose(result, expected, rtol=0, atol=1e-12)


def test_result_is_unit_length():
    audio = _tone(int(95.0 * SR))
    with clap_stub(audio) as _:
        result = extract_embedding(Path("track.mp3"))
    assert np.linalg.norm(result) == pytest.approx(1.0)


def test_result_has_512_dimensions():
    audio = _tone(int(30.0 * SR))
    with clap_stub(audio) as _:
        result = extract_embedding(Path("track.mp3"))
    assert len(result) == 512


def test_a_long_track_is_not_represented_by_its_middle_window():
    """The regression test for the behaviour ADR-0104 replaced.

    Under the old implementation a five-minute track was embedded from the middle
    ten seconds, so the result equalled that single window's vector. Here every
    window points in a different *direction* — magnitudes alone would not do, since
    vectors differing only in scale normalise to the same thing — and the result
    matches none of them.
    """
    n_windows = 30
    vectors = []
    for i in range(n_windows):
        v = np.zeros(512)
        v[i] = 1.0
        vectors.append(v)
    audio = _tone(n_windows * WINDOW)
    with clap_stub(audio, vectors=vectors) as seen:
        result = extract_embedding(Path("track.mp3"))

    assert len(seen) == n_windows
    middle = vectors[n_windows // 2]
    assert not np.allclose(result, middle / np.linalg.norm(middle))
    # It is the mean: every window has an equal say.
    expected = np.mean(vectors, axis=0)
    np.testing.assert_allclose(result, expected / np.linalg.norm(expected), atol=1e-12)


# ---------------------------------------------------------------------------
# Failure rather than a plausible-looking vector
# ---------------------------------------------------------------------------


def test_a_zero_magnitude_mean_is_an_error_not_a_stored_vector():
    """A vector with no direction has no similarity to anything.

    Storing it would place the track at an arbitrary point in the space rather than
    nowhere, and it would look exactly like a normal row.
    """
    vectors = [np.zeros(512), np.zeros(512)]
    audio = _tone(2 * WINDOW)
    with clap_stub(audio, vectors=vectors):
        with pytest.raises(AnalysisError, match="zero magnitude"):
            extract_embedding(Path("track.mp3"))


def test_disabled_clap_still_returns_none_before_any_decoding():
    """The early return predates this change and must survive it."""
    settings = MagicMock()
    settings.is_clap_embeddings_enabled.return_value = (False, "Disabled by user")
    with patch("app.services.analysis._torch_available", True):
        with patch(
            "app.services.app_settings.get_app_settings_service",
            return_value=settings,
        ):
            assert extract_embedding(Path("track.mp3")) is None
