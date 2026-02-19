"""Audio analysis service using CLAP embeddings and librosa features."""

import importlib.util
import logging
import os
from functools import lru_cache
from pathlib import Path

import acoustid
import numpy as np

# Check torch availability without importing it (~0 memory cost)
# The actual torch import happens lazily inside functions that need it
_torch_available = importlib.util.find_spec("torch") is not None
_torch_import_error: str | None = "torch package not installed" if not _torch_available else None

logger = logging.getLogger(__name__)


class AnalysisError(Exception):
    """Raised when audio analysis fails."""
    pass


def get_acoustid_api_key() -> str:
    """Get AcoustID API key from environment or app settings."""
    # First check environment variable
    key = os.environ.get("ACOUSTID_API_KEY", "")
    if key:
        return key

    # Then check app settings
    try:
        from app.services.app_settings import get_app_settings_service
        settings = get_app_settings_service().get()
        return settings.acoustid_api_key or ""
    except Exception:
        return ""

# Lazy load the CLAP model to avoid loading on import
_clap_model = None
_clap_processor = None


def get_device() -> str:
    """Get the best available device for inference.

    Note: MPS (Apple Silicon) doesn't work well with subprocess workers,
    so we use CPU for background analysis tasks.
    """
    if not _torch_available:
        return "cpu"

    # Check if we're in a subprocess worker
    # MPS doesn't work reliably in subprocesses, so use CPU
    if os.environ.get("FORKED_BY_MULTIPROCESSING"):
        return "cpu"

    import torch

    if torch.cuda.is_available():
        return "cuda"
    elif torch.backends.mps.is_available():
        return "mps"
    return "cpu"


@lru_cache(maxsize=1)
def load_clap_model() -> tuple:  # Returns (model, processor)
    """Load the CLAP model (cached)."""
    global _clap_model, _clap_processor

    if _clap_model is None:
        from transformers import ClapModel, ClapProcessor

        model_name = "laion/clap-htsat-unfused"
        logger.info(f"Loading CLAP model: {model_name}")

        device = get_device()
        logger.info(f"Using device: {device}")

        _clap_processor = ClapProcessor.from_pretrained(model_name)
        _clap_model = ClapModel.from_pretrained(model_name)
        _clap_model = _clap_model.to(device)
        _clap_model.eval()

        logger.info("CLAP model loaded successfully")

    return _clap_model, _clap_processor


def get_analysis_capabilities() -> dict:
    """Get current analysis capabilities and any issues.

    Returns dict with:
        - embeddings_enabled: bool - whether CLAP embeddings can be generated
        - embeddings_disabled_reason: str | None - why embeddings are disabled
        - features_enabled: bool - whether audio features can be extracted
        - clap_status: dict - detailed CLAP status for UI
    """
    from app.services.app_settings import get_app_settings_service

    clap_status = get_app_settings_service().get_clap_status()

    embeddings_enabled = clap_status["enabled"] and _torch_available
    embeddings_disabled_reason = None

    if not clap_status["enabled"]:
        embeddings_disabled_reason = clap_status["reason"]
    elif not _torch_available:
        embeddings_disabled_reason = f"PyTorch not available: {_torch_import_error or 'import failed'}"

    return {
        "embeddings_enabled": embeddings_enabled,
        "embeddings_disabled_reason": embeddings_disabled_reason,
        "features_enabled": True,  # librosa is always available
        "clap_status": clap_status,
    }


def check_analysis_capabilities() -> None:
    """Check and log analysis capabilities at startup.

    Logs a warning if embeddings cannot be generated.
    """
    caps = get_analysis_capabilities()
    if not caps["embeddings_enabled"]:
        logger.warning(
            f"CLAP embeddings DISABLED: {caps['embeddings_disabled_reason']}. "
            "Audio similarity features (Music Map) will not work. "
            "Install PyTorch to enable: uv add torch --optional analysis"
        )
    else:
        logger.info("Analysis capabilities: features=enabled, embeddings=enabled")


def extract_embedding(file_path: Path, target_sr: int = 48000) -> list[float] | None:
    """Extract CLAP audio embedding from file.

    Args:
        file_path: Path to audio file
        target_sr: Target sample rate for CLAP (48kHz recommended)

    Returns:
        512-dimensional embedding as list of floats, or None on error
    """
    # Skip CLAP if torch isn't available
    if not _torch_available:
        logger.debug("CLAP embeddings disabled (torch not available)")
        return None

    # Skip CLAP if disabled via settings or env var
    from app.services.app_settings import get_app_settings_service
    clap_enabled, reason = get_app_settings_service().is_clap_embeddings_enabled()
    if not clap_enabled:
        logger.debug(f"CLAP embeddings disabled: {reason}")
        return None

    try:
        import librosa
        import torch

        # Load audio file
        audio, sr = librosa.load(file_path, sr=target_sr, mono=True)

        # Limit to 10 seconds for embedding (CLAP works best with short clips)
        max_samples = target_sr * 10
        if len(audio) > max_samples:
            # Take middle section
            start = (len(audio) - max_samples) // 2
            audio = audio[start:start + max_samples]

        # Load model
        model, processor = load_clap_model()
        device = get_device()

        # Process audio
        inputs = processor(
            audio=audio,
            sampling_rate=target_sr,
            return_tensors="pt",
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}

        # Get embedding
        with torch.no_grad():
            audio_embed = model.get_audio_features(**inputs)

        # Convert to list
        embedding = audio_embed.cpu().numpy().flatten().tolist()

        return embedding

    except Exception as e:
        logger.error(f"Error extracting embedding from {file_path}: {e}")
        raise AnalysisError(f"Embedding extraction failed: {e}") from e


def extract_text_embedding(text: str) -> list[float] | None:
    """Extract CLAP text embedding from a text description.

    CLAP embeds text and audio into the same 512-dimensional space,
    enabling text-to-audio semantic search.

    Args:
        text: Natural language description (e.g., "gloomy with Eastern influences")

    Returns:
        512-dimensional embedding as list of floats, or None if CLAP is disabled
    """
    if not _torch_available:
        logger.debug("CLAP text embeddings disabled (torch not available)")
        return None

    from app.services.app_settings import get_app_settings_service
    clap_enabled, reason = get_app_settings_service().is_clap_embeddings_enabled()
    if not clap_enabled:
        logger.debug(f"CLAP text embeddings disabled: {reason}")
        return None

    try:
        import torch

        model, processor = load_clap_model()
        device = get_device()

        # Process text input
        inputs = processor(
            text=[text],  # CLAP expects a list of texts
            return_tensors="pt",
            padding=True,
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}

        # Get text embedding
        with torch.no_grad():
            text_embed = model.get_text_features(**inputs)

        # Convert to list
        embedding = text_embed.cpu().numpy().flatten().tolist()
        return embedding

    except Exception as e:
        logger.error(f"Error extracting text embedding for '{text}': {e}")
        return None


def read_replaygain_tags(file_path: Path) -> dict[str, float | None]:
    """Read existing ReplayGain tags from audio file metadata.

    Checks ID3 (MP3) and Vorbis Comment (FLAC/OGG) formats.

    Returns:
        Dict with loudness_lufs, track_peak, replaygain_track_gain if found.
    """
    import mutagen

    result: dict[str, float | None] = {
        "loudness_lufs": None,
        "track_peak": None,
        "replaygain_track_gain": None,
    }

    try:
        audio = mutagen.File(file_path)
        if audio is None:
            return result

        gain_value: str | None = None
        peak_value: str | None = None

        # ID3 tags (MP3)
        if hasattr(audio, "tags") and audio.tags:
            tags = audio.tags
            # TXXX:replaygain_track_gain
            for key in ["TXXX:replaygain_track_gain", "TXXX:REPLAYGAIN_TRACK_GAIN"]:
                if key in tags:
                    gain_value = str(tags[key])
                    break
            for key in ["TXXX:replaygain_track_peak", "TXXX:REPLAYGAIN_TRACK_PEAK"]:
                if key in tags:
                    peak_value = str(tags[key])
                    break

            # Vorbis comments (FLAC, OGG)
            for key in ["replaygain_track_gain", "REPLAYGAIN_TRACK_GAIN"]:
                if key in tags:
                    val = tags[key]
                    gain_value = val[0] if isinstance(val, list) else str(val)
                    break
            for key in ["replaygain_track_peak", "REPLAYGAIN_TRACK_PEAK"]:
                if key in tags:
                    val = tags[key]
                    peak_value = val[0] if isinstance(val, list) else str(val)
                    break

        if gain_value:
            # Parse "X.XX dB" format
            gain_str = gain_value.replace("dB", "").replace("db", "").strip()
            try:
                gain_db = float(gain_str)
                result["replaygain_track_gain"] = gain_db
                # ReplayGain reference level is -18 LUFS
                # gain_db = -18 - loudness_lufs => loudness_lufs = -18 - gain_db
                result["loudness_lufs"] = -18.0 - gain_db
            except ValueError:
                pass

        if peak_value:
            try:
                result["track_peak"] = float(peak_value.strip())
            except ValueError:
                pass

    except Exception as e:
        logger.debug(f"Could not read ReplayGain tags from {file_path}: {e}")

    return result


def precompute_shared(file_path: Path) -> tuple:
    """Load audio and compute all shared librosa intermediates.

    Returns (y, sr, shared_dict) where shared_dict contains:
    spec, power_spec, chroma, onset_env, bpm, beat_frames, beat_times,
    rms, log_S, mfcc, n_fft, hop_length, duration, pulse
    """
    import librosa

    y, sr = librosa.load(str(file_path), sr=22050, mono=True)

    n_fft = 2048
    hop_length = 512
    spec = np.abs(librosa.stft(y, n_fft=n_fft))
    power_spec = spec ** 2

    # Chroma via manual filter bank (avoids chroma_cqt SIGSEGV on macOS Accelerate)
    chroma_fb = librosa.filters.chroma(sr=sr, n_fft=n_fft)
    raw_chroma = np.dot(chroma_fb, power_spec)
    chroma = librosa.util.normalize(raw_chroma, norm=np.inf, axis=0)

    # Onset envelope + tempo
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo = librosa.feature.tempo(onset_envelope=onset_env, sr=sr)
    bpm = float(tempo) if not isinstance(tempo, np.ndarray) else float(tempo[0])

    # Beat positions via PLP
    pulse = librosa.beat.plp(onset_envelope=onset_env, sr=sr)
    beats_plp = librosa.util.localmax(pulse)
    beat_frames = np.flatnonzero(beats_plp)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    # RMS energy
    rms = librosa.feature.rms(y=y)[0]

    # Log power spectrogram and MFCCs
    log_S = librosa.power_to_db(power_spec, ref=np.max)
    mfcc = librosa.feature.mfcc(S=log_S, sr=sr, n_mfcc=13)

    shared = {
        "spec": spec,
        "power_spec": power_spec,
        "chroma": chroma,
        "onset_env": onset_env,
        "bpm": bpm,
        "beat_frames": beat_frames,
        "beat_times": beat_times,
        "rms": rms,
        "log_S": log_S,
        "mfcc": mfcc,
        "n_fft": n_fft,
        "hop_length": hop_length,
        "duration": len(y) / sr,
        "pulse": pulse,
    }

    return y, sr, shared


def derive_features(
    y: np.ndarray, sr: int, shared: dict, file_path: Path
) -> dict[str, float | str | None]:
    """Derive classic scalar features from shared librosa intermediates.

    Returns a flat dict of typed values matching TrackAnalysis typed columns.
    """
    import librosa

    features: dict[str, float | str | None] = {}

    chroma = shared["chroma"]
    spec = shared["spec"]
    onset_env = shared["onset_env"]
    rms = shared["rms"]
    n_fft = shared["n_fft"]
    bpm = shared["bpm"]

    features["bpm"] = bpm

    # Key detection
    key_idx = np.argmax(np.mean(chroma, axis=1))
    key_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    features["key"] = key_names[key_idx]

    # Energy (RMS energy normalized to 0-1 using dB scale)
    rms_mean = float(np.mean(rms))
    rms_db = 20 * np.log10(rms_mean + 1e-10)
    features["energy"] = float(np.clip((rms_db + 60) / 54, 0, 1))

    # Spectral centroid
    spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]

    # Danceability
    pulse = shared["pulse"]
    features["danceability"] = float(np.mean(pulse))

    # Zero crossing rate
    zcr = librosa.feature.zero_crossing_rate(y)[0]

    # Acousticness
    centroid_norm = np.mean(spectral_centroid) / (sr / 2)
    features["acousticness"] = float(max(0, 1 - centroid_norm * 2))

    # Instrumentalness
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    vocal_mask = (freqs >= 300) & (freqs <= 3000)
    vocal_energy = np.mean(spec[vocal_mask, :])
    total_energy = np.mean(spec)
    vocal_ratio = vocal_energy / (total_energy + 1e-6)
    features["instrumentalness"] = float(max(0, 1 - vocal_ratio))

    # Valence
    chroma_rotated = np.roll(chroma, -key_idx, axis=0)
    major_thirds = chroma_rotated[[0, 4, 7], :]
    minor_thirds = chroma_rotated[[0, 3, 7], :]
    major_energy = np.mean(major_thirds)
    minor_energy = np.mean(minor_thirds)
    mode_indicator = (major_energy - minor_energy) / (major_energy + minor_energy + 1e-6)
    mode_score = (mode_indicator + 1) / 2

    centroid_norm = np.mean(spectral_centroid) / (sr / 2)
    brightness_score = np.clip(centroid_norm * 2, 0, 1)

    tempo_score = np.clip((bpm - 60) / 120, 0, 1) if bpm else 0.5

    contrast = librosa.feature.spectral_contrast(S=spec, sr=sr)
    contrast_mean = np.mean(contrast)
    contrast_score = np.clip(contrast_mean / 25, 0, 1)

    rms_std = np.std(rms)
    dynamics_score = np.clip(rms_std / 0.08, 0, 1)

    raw_valence = (
        mode_score * 0.30 +
        brightness_score * 0.25 +
        tempo_score * 0.20 +
        contrast_score * 0.15 +
        dynamics_score * 0.10
    )

    centered = raw_valence - 0.5
    spread = np.sign(centered) * (np.abs(centered) ** 0.6) * 1.8
    features["valence"] = float(np.clip(spread + 0.5, 0, 1))

    # Speechiness
    zcr_mean = np.mean(zcr)
    features["speechiness"] = float(min(1, zcr_mean * 2))

    # Loudness / ReplayGain
    rg_tags = read_replaygain_tags(file_path)
    if rg_tags["loudness_lufs"] is not None:
        features["loudness_lufs"] = rg_tags["loudness_lufs"]
        features["track_peak"] = rg_tags["track_peak"]
        features["replaygain_track_gain"] = rg_tags["replaygain_track_gain"]
    else:
        try:
            import pyloudnorm as pyln
            import soundfile as sf

            data, rate = sf.read(str(file_path))
            peak = float(np.max(np.abs(data)))

            meter = pyln.Meter(rate)
            loudness = meter.integrated_loudness(data)

            if np.isfinite(loudness):
                features["loudness_lufs"] = float(loudness)
                features["track_peak"] = peak
                features["replaygain_track_gain"] = float(-18.0 - loudness)
            else:
                features["loudness_lufs"] = None
                features["track_peak"] = peak
                features["replaygain_track_gain"] = None
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Loudness measurement failed: {e}")
            features["loudness_lufs"] = None
            features["track_peak"] = None
            features["replaygain_track_gain"] = None

    return features


def _extract_features_impl(file_path_str: str) -> dict[str, float | str | None]:
    """Internal implementation of feature extraction.

    This runs in a subprocess to isolate crashes (SIGSEGV) from the main worker.
    Calls precompute_shared() + derive_features() internally.
    """
    from pathlib import Path

    file_path = Path(file_path_str)
    y, sr, shared = precompute_shared(file_path)
    return derive_features(y, sr, shared, file_path)


def extract_features(file_path: Path) -> dict[str, float | str | None]:
    """Extract audio features using librosa.

    Analysis runs in a spawned subprocess via ProcessPoolExecutor to isolate
    potential crashes from the main API process.

    Args:
        file_path: Path to audio file

    Returns:
        Dict with extracted features
    """
    try:
        return _extract_features_impl(str(file_path))
    except Exception as e:
        logger.error(f"Error extracting features from {file_path}: {e}")
        raise AnalysisError(f"Feature extraction failed: {e}") from e


def generate_fingerprint(file_path: Path) -> tuple[int, str] | None:
    """Generate AcoustID fingerprint for an audio file.

    Requires chromaprint/fpcalc to be installed on the system.
    Install via: brew install chromaprint (macOS) or apt install libchromaprint-tools (Linux)

    Args:
        file_path: Path to audio file

    Returns:
        Tuple of (duration_seconds, fingerprint_string) or None on error
    """
    try:
        duration, fingerprint = acoustid.fingerprint_file(str(file_path))
        return (duration, fingerprint)
    except acoustid.FingerprintGenerationError as e:
        logger.error(f"Error generating fingerprint for {file_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error generating fingerprint for {file_path}: {e}")
        return None


def lookup_acoustid(file_path: Path) -> dict | None:
    """Look up track metadata from AcoustID database.

    Requires ACOUSTID_API_KEY environment variable or app setting to be set.
    Get a free key at https://acoustid.org/new-application

    Args:
        file_path: Path to audio file

    Returns:
        Dict with metadata (title, artist, album, musicbrainz_id) or None
    """
    api_key = get_acoustid_api_key()
    if not api_key:
        logger.warning("ACOUSTID_API_KEY not set, skipping AcoustID lookup")
        return None

    try:
        results = acoustid.match(
            api_key,
            str(file_path),
            meta="recordings releases",
        )

        for score, recording_id, title, artist in results:
            if score > 0.8:  # High confidence match
                return {
                    "acoustid_score": score,
                    "musicbrainz_recording_id": recording_id,
                    "title": title,
                    "artist": artist,
                }

        return None

    except acoustid.NoBackendError:
        logger.error("chromaprint/fpcalc not found. Install chromaprint.")
        return None
    except acoustid.FingerprintGenerationError as e:
        logger.error(f"Error generating fingerprint: {e}")
        return None
    except acoustid.WebServiceError as e:
        logger.error(f"AcoustID API error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in AcoustID lookup: {e}")
        return None


class AcoustIDError(Exception):
    """Raised when AcoustID lookup fails."""

    def __init__(self, message: str, error_type: str = "unknown"):
        super().__init__(message)
        self.error_type = error_type


def lookup_acoustid_candidates(
    file_path: Path,
    min_score: float = 0.5,
    limit: int = 5,
) -> list[dict]:
    """Look up all track candidates from AcoustID database.

    Returns all matches above min_score, sorted by score descending.
    This is used for the auto-populate feature where users choose from candidates.

    Args:
        file_path: Path to audio file
        min_score: Minimum confidence score (0.0-1.0) to include
        limit: Maximum number of candidates to return

    Returns:
        List of dicts with: acoustid_score, musicbrainz_recording_id, title, artist

    Raises:
        AcoustIDError: If fingerprinting or API lookup fails
    """
    api_key = get_acoustid_api_key()
    if not api_key:
        raise AcoustIDError(
            "AcoustID not configured. Add API key in Settings > API Keys",
            error_type="not_configured",
        )

    try:
        results = acoustid.match(
            api_key,
            str(file_path),
            meta="recordings releases",
        )

        candidates = []
        seen_recordings = set()  # Deduplicate by recording ID

        for score, recording_id, title, artist in results:
            if score < min_score:
                continue
            if recording_id in seen_recordings:
                continue

            seen_recordings.add(recording_id)
            candidates.append({
                "acoustid_score": float(score),
                "musicbrainz_recording_id": recording_id,
                "title": title,
                "artist": artist,
            })

            if len(candidates) >= limit:
                break

        # Sort by score descending
        candidates.sort(key=lambda x: x["acoustid_score"], reverse=True)
        return candidates

    except acoustid.NoBackendError:
        raise AcoustIDError(
            "Audio fingerprinting requires chromaprint. Install via: "
            "brew install chromaprint (macOS) or apt install libchromaprint-tools (Linux)",
            error_type="chromaprint_missing",
        )
    except acoustid.FingerprintGenerationError as e:
        raise AcoustIDError(
            f"Failed to generate audio fingerprint: {e}",
            error_type="fingerprint_error",
        )
    except acoustid.WebServiceError as e:
        raise AcoustIDError(
            f"AcoustID API error: {e}",
            error_type="api_error",
        )
    except Exception as e:
        logger.error(f"Unexpected error in AcoustID lookup: {e}")
        raise AcoustIDError(
            f"Unexpected error: {e}",
            error_type="unknown",
        )


def identify_track(file_path: Path) -> dict:
    """Full track identification using AcoustID.

    Generates fingerprint and looks up metadata.

    Args:
        file_path: Path to audio file

    Returns:
        Dict with fingerprint and any matched metadata
    """
    result = {
        "fingerprint": None,
        "duration": None,
        "metadata": None,
    }

    # Generate fingerprint
    fp_result = generate_fingerprint(file_path)
    if fp_result:
        result["duration"], result["fingerprint"] = fp_result

    # Look up metadata if we have an API key
    if get_acoustid_api_key():
        metadata = lookup_acoustid(file_path)
        if metadata:
            result["metadata"] = metadata

    return result
