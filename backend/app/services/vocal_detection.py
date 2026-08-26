"""Voice activity detection using silero-vad ONNX model.

Provides speech probability estimation for instrumentalness and speechiness
feature computation. Falls back gracefully if the model is unavailable.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import onnxruntime

logger = logging.getLogger(__name__)


class VADError(RuntimeError):
    """Raised when the VAD model is present but cannot be used.

    Deliberately distinct from "model unavailable", which `detect_speech` reports by
    returning None so the caller can use its spectral fallback. This means *the model is
    here and it did not work*, which is never a legitimate measurement.
    """


def _model_input_names(session: onnxruntime.InferenceSession) -> set[str]:
    return {i.name for i in session.get_inputs()}

# Default model location
_MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "models"
_MODEL_PATH = _MODEL_DIR / "silero_vad.onnx"

# silero-vad expects 16kHz audio
_TARGET_SR = 16000
# Window size in samples (512 samples = 32ms at 16kHz)
_WINDOW_SIZE = 512


@lru_cache(maxsize=1)
def _load_vad_model() -> onnxruntime.InferenceSession | None:
    """Load silero-vad ONNX model, downloading if necessary."""
    model_path = _MODEL_PATH

    if not model_path.exists():
        # Try to download on first use
        try:
            _download_model(model_path)
        except Exception as e:
            logger.warning(f"Could not download silero-vad model: {e}")
            return None

    if not model_path.exists():
        logger.info("silero-vad model not found, using spectral fallback")
        return None

    try:
        import onnxruntime

        session = onnxruntime.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        logger.info("silero-vad ONNX model loaded successfully")
        return session
    except ImportError:
        logger.warning("onnxruntime not installed, using spectral fallback")
        return None
    except Exception as e:
        logger.warning(f"Failed to load silero-vad model: {e}")
        return None


def _download_model(dest: Path) -> None:
    """Download silero-vad ONNX model from GitHub releases."""
    import urllib.request

    # NOTE: this tracks `master`, which is how a v4-era integration silently acquired a v5
    # model. The signature check in `detect_speech` is what makes that loud rather than
    # silent now; pinning to a release tag would stop it happening at all, and is the better
    # fix whenever someone can verify a stable URL.
    url = (
        "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
    )

    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Downloading silero-vad model to {dest}...")
    urllib.request.urlretrieve(url, str(dest))
    logger.info("silero-vad model downloaded successfully")


def detect_speech(
    y: np.ndarray,
    sr: int,
    max_duration: float = 120.0,
) -> tuple[float, float] | None:
    """Detect speech in audio using silero-vad.

    Args:
        y: Audio samples (mono, float32)
        sr: Sample rate
        max_duration: Max audio duration to analyze in seconds (caps processing time)

    Returns:
        (mean_speech_probability, speech_fraction) or None if model unavailable.
        - mean_speech_prob: Average speech probability across windows (0-1)
        - speech_fraction: Fraction of windows with speech > 0.5 threshold
    """
    session = _load_vad_model()
    if session is None:
        return None

    # Resample to 16kHz if needed. librosa is imported here rather than at the top of the
    # function because it is only needed for resampling — it lives in the optional `analysis`
    # extra, and requiring it unconditionally made this module untestable wherever that extra
    # is not installed, which includes CI.
    if sr != _TARGET_SR:
        import librosa

        y = librosa.resample(y, orig_sr=sr, target_sr=_TARGET_SR)

    # Limit duration to cap processing time
    max_samples = int(max_duration * _TARGET_SR)
    if len(y) > max_samples:
        # Take middle section
        start = (len(y) - max_samples) // 2
        y = y[start : start + max_samples]

    # Ensure float32
    y = y.astype(np.float32)

    # Process in windows
    num_windows = len(y) // _WINDOW_SIZE
    if num_windows == 0:
        return (0.0, 0.0)

    names = _model_input_names(session)
    is_v5 = "state" in names
    if not is_v5 and "h" not in names:
        raise VADError(
            f"Unrecognised silero-vad signature: inputs are {sorted(names)}. "
            "Expected 'state' (v5) or 'h'/'c' (v4)."
        )

    # v5 carries one combined (2, 1, 128) state tensor; v4 carried separate (2, 1, 64) h and c.
    state = np.zeros((2, 1, 128), dtype=np.float32)
    h = np.zeros((2, 1, 64), dtype=np.float32)
    c = np.zeros((2, 1, 64), dtype=np.float32)
    sr_tensor = np.array([_TARGET_SR], dtype=np.int64)

    speech_probs = []
    first_error: Exception | None = None

    for i in range(num_windows):
        chunk = y[i * _WINDOW_SIZE : (i + 1) * _WINDOW_SIZE]
        if len(chunk) < _WINDOW_SIZE:
            break

        input_data = chunk.reshape(1, -1)

        try:
            if is_v5:
                output, state = session.run(
                    None, {"input": input_data, "state": state, "sr": sr_tensor}
                )
            else:
                output, h, c = session.run(
                    None, {"input": input_data, "h": h, "c": c, "sr": sr_tensor}
                )
            speech_probs.append(float(output[0][0]))
        except Exception as exc:  # noqa: BLE001 - one bad window is tolerable; all of them is not
            # Keep going: a single malformed window should not lose the track. The
            # all-windows-failed case is raised after the loop, where it cannot be mistaken
            # for a confident "no speech".
            if first_error is None:
                first_error = exc
            continue

    if first_error is not None:
        logger.warning(
            "silero-vad: %d of %d windows failed (first: %r)",
            num_windows - len(speech_probs),
            num_windows,
            first_error,
        )

    if not speech_probs:
        # Every window failed. Returning (0.0, 0.0) here is what silently produced
        # instrumentalness=1.0 and speechiness=0.0 for 25,661 of 25,697 analysed tracks:
        # a model-signature change made every session.run() raise, and the per-window
        # `continue` swallowed all of them. A total failure must not look like an answer.
        raise VADError(
            f"silero-vad produced no probabilities across {num_windows} windows. "
            f"Model inputs are {sorted(_model_input_names(session))}; "
            f"this build supports v5 ('state') and v4 ('h'/'c')."
        )

    mean_prob = float(np.mean(speech_probs))
    speech_fraction = float(np.mean([1.0 if p > 0.5 else 0.0 for p in speech_probs]))

    return (mean_prob, speech_fraction)


def is_available() -> bool:
    """Check if VAD model is available (or can be downloaded)."""
    return _load_vad_model() is not None
