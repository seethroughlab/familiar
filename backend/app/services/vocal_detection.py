"""Voice activity detection using silero-vad ONNX model.

Provides speech probability estimation for instrumentalness and speechiness
feature computation. Falls back gracefully if the model is unavailable.
"""

import logging
from functools import lru_cache
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Default model location
_MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "models"
_MODEL_PATH = _MODEL_DIR / "silero_vad.onnx"

# silero-vad expects 16kHz audio
_TARGET_SR = 16000
# Window size in samples (512 samples = 32ms at 16kHz)
_WINDOW_SIZE = 512


@lru_cache(maxsize=1)
def _load_vad_model() -> "onnxruntime.InferenceSession | None":
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

    import librosa

    # Resample to 16kHz if needed
    if sr != _TARGET_SR:
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

    # silero-vad state: h and c tensors (2, 1, 64)
    h = np.zeros((2, 1, 64), dtype=np.float32)
    c = np.zeros((2, 1, 64), dtype=np.float32)
    sr_tensor = np.array([_TARGET_SR], dtype=np.int64)

    speech_probs = []

    for i in range(num_windows):
        chunk = y[i * _WINDOW_SIZE : (i + 1) * _WINDOW_SIZE]
        if len(chunk) < _WINDOW_SIZE:
            break

        input_data = chunk.reshape(1, -1)

        try:
            ort_inputs = {
                "input": input_data,
                "h": h,
                "c": c,
                "sr": sr_tensor,
            }
            output, h, c = session.run(None, ort_inputs)
            prob = float(output[0][0])
            speech_probs.append(prob)
        except Exception:
            # Skip bad windows
            continue

    if not speech_probs:
        return (0.0, 0.0)

    mean_prob = float(np.mean(speech_probs))
    speech_fraction = float(np.mean([1.0 if p > 0.5 else 0.0 for p in speech_probs]))

    return (mean_prob, speech_fraction)


def is_available() -> bool:
    """Check if VAD model is available (or can be downloaded)."""
    return _load_vad_model() is not None
