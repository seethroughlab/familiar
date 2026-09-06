"""Audio analysis service using CLAP embeddings and librosa features."""

import importlib.util
import logging
import os
from pathlib import Path

import acoustid
import numpy as np

# Cheap at import time: vocal_detection imports onnxruntime lazily, inside its functions.
from app.services.vocal_detection import VADError

# CLAP now runs through `clapback-embed` (ADR-0105), which is ONNX-based and pulls
# in neither torch nor transformers. Checked without importing, as before: the
# package loads onnxruntime lazily, but the import still costs real time.
#
# `_torch_available` kept its name for one release because callers outside this
# module tested it; it is now the embedder check and nothing here imports torch.
_embedder_available = importlib.util.find_spec("clapback_embed") is not None
_torch_available = _embedder_available  # deprecated alias, see above
_torch_import_error: str | None = (
    None if _embedder_available else "clapback-embed package not installed"
)

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

# `get_device()` and `load_clap_model()` are gone with ADR-0105. Device selection
# is now the embedder's, via CLAPBACK_PROVIDERS, and the model is an ONNX artifact
# rather than a torch module — so there is nothing here to cache or move.


def embedder_providers() -> list[str]:
    """Execution providers the embedder will actually use.

    Surfaced for the health view: ONNX Runtime **silently falls back to CPU** when a
    requested provider fails to load, so "CUDA was requested" and "CUDA is running"
    are different facts and only the second one matters.
    """
    if not _embedder_available:
        return []
    from clapback_embed.artifacts import providers

    return providers()


def embedder_active_providers() -> list[str]:
    """Providers actually bound to the loaded session, not the ones asked for."""
    if not _embedder_available:
        return []
    try:
        from clapback_embed.artifacts import audio_session

        return list(audio_session().get_providers())
    except Exception as exc:  # missing artifacts, unusable GPU, anything
        logger.debug(f"Could not resolve active embedder providers: {exc}")
        return []


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

    embeddings_enabled = clap_status["enabled"] and _embedder_available
    embeddings_disabled_reason = None

    if not clap_status["enabled"]:
        embeddings_disabled_reason = clap_status["reason"]
    elif not _embedder_available:
        embeddings_disabled_reason = f"Embedder unavailable: {_torch_import_error or 'import failed'}"

    return {
        "embeddings_enabled": embeddings_enabled,
        "embeddings_disabled_reason": embeddings_disabled_reason,
        "features_enabled": True,  # librosa is always available
        "clap_status": clap_status,
        # Requested vs actually bound. ONNX Runtime falls back to CPU *silently*
        # when a provider fails to load, so a GPU that is configured but not
        # working looks identical to one that is — except here.
        "embedder_providers_requested": embedder_providers(),
        "embedder_providers_active": embedder_active_providers(),
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
            "Install the embedder to enable: uv sync --extra analysis"
        )
    else:
        logger.info("Analysis capabilities: features=enabled, embeddings=enabled")


def extract_embedding(file_path: Path, target_sr: int = 48000) -> list[float] | None:
    """Extract a CLAP audio embedding representing the whole track.

    The windowing, mel front-end, pooling and precision all live in
    `clapback-embed` now (ADR-0105). That is not a refactor for tidiness: the
    community cache can only tell "two contributors disagree about the audio" from
    "two contributors ran different code" if there is exactly one implementation,
    and Familiar running its own copy defeated that by construction.

    Behaviour is unchanged from ADR-0104 — consecutive 480,000-sample windows,
    mean-pooled raw encoder outputs, L2-normalised — and the vectors match the
    previous torch path to 1.2e-07, against the 6.0e-08 that `float4` storage
    already costs. `EMBEDDING_VERSION` therefore does not bump.

    Args:
        file_path: Path to audio file
        target_sr: Ignored; the sample rate is part of the pinned contract and
            changing it would change every vector. Kept so existing callers and
            tests do not break.

    Returns:
        512-dimensional embedding as list of floats, or None if CLAP is disabled
    """
    if not _embedder_available:
        logger.debug("CLAP embeddings disabled (clapback-embed not installed)")
        return None

    from app.services.app_settings import get_app_settings_service
    clap_enabled, reason = get_app_settings_service().is_clap_embeddings_enabled()
    if not clap_enabled:
        logger.debug(f"CLAP embeddings disabled: {reason}")
        return None

    try:
        from clapback_embed import embed_file

        return embed_file(file_path)
    except Exception as e:
        logger.error(f"Error extracting embedding from {file_path}: {e}")
        raise AnalysisError(f"Embedding extraction failed: {e}") from e


def embedding_pipeline_version() -> str | None:
    """The identity of the pipeline `extract_embedding` runs, or None if there is none.

    `PIPELINE_VERSION` is composed by `clapback-embed` from every component that can
    move a vector — the checkpoint, the mel front-end, the ONNX artifacts, the pooling
    and the precision. Two vectors are comparable exactly when it matches, which is
    what clapback's `ADR-0006` makes the corpus key.

    **Read from the installed library rather than written down here.** A constant in
    `config.py` would be a second copy of a fact, maintained by hand, drifting from the
    code that actually computes the vectors — which is exactly the failure
    `EMBEDDING_VERSION` already has and the reason `ADR-0006` was written. This cannot
    drift: it is the value the encoder that just ran reports about itself.

    Returns None when the embedder is not installed, which is the same case in which
    this installation computes no embeddings and so has nothing to declare.
    """
    if not _embedder_available:
        return None
    try:
        from clapback_embed import PIPELINE_VERSION

        return PIPELINE_VERSION
    except Exception as e:  # noqa: BLE001 - a missing attribute must not break analysis
        # An older `clapback-embed` without the attribute. Declaring nothing is
        # correct here: clapback's server treats absent as "unknown", which is
        # true, and a guessed string would be worse than silence.
        logger.debug(f"clapback-embed reports no PIPELINE_VERSION: {e}")
        return None


def extract_text_embedding(text: str) -> list[float] | None:
    """Extract CLAP text embedding from a text description.

    CLAP embeds text and audio into the same 512-dimensional space, which is what
    makes "gloomy with Eastern influences" a query rather than a keyword search.

    Runs on HuggingFace `tokenizers` alone — no `transformers`. That was the open
    question when ADR-0105 was written, since a tokenizer is not obviously
    separable from the library that ships it; measured at cosine 1.0000000000
    against `transformers` + `torch`.

    Args:
        text: Natural language description (e.g., "gloomy with Eastern influences")

    Returns:
        512-dimensional embedding as list of floats, or None if CLAP is disabled
    """
    if not _embedder_available:
        logger.debug("CLAP text embeddings disabled (clapback-embed not installed)")
        return None

    from app.services.app_settings import get_app_settings_service
    clap_enabled, reason = get_app_settings_service().is_clap_embeddings_enabled()
    if not clap_enabled:
        logger.debug(f"CLAP text embeddings disabled: {reason}")
        return None

    try:
        from clapback_embed import embed_text

        return embed_text(text)
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


# ── Krumhansl-Kessler key profiles ────────────────────────────────────────────
# Empirically derived pitch-class profiles for major and minor keys.
# Each 12-element array represents the "ideal" chroma distribution.
_KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

_KEY_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def _detect_key_kk(chroma: np.ndarray) -> tuple[str, float]:
    """Detect key using Krumhansl-Kessler profile correlation.

    Correlates mean chroma against all 24 key profiles (12 roots × major + minor).

    Returns:
        (key_string, confidence) where key_string includes mode suffix
        (e.g., "C", "Am", "F#m") and confidence is the correlation score (0-1).
    """
    mean_chroma = np.mean(chroma, axis=1)
    if np.sum(mean_chroma) < 1e-8:
        return ("C", 0.0)

    best_corr = -1.0
    best_key = "C"

    for root in range(12):
        # Rotate chroma so root is at index 0
        rotated = np.roll(mean_chroma, -root)

        # Major correlation
        corr_major = float(np.corrcoef(rotated, _KK_MAJOR)[0, 1])
        if corr_major > best_corr:
            best_corr = corr_major
            best_key = _KEY_NAMES[root]

        # Minor correlation
        corr_minor = float(np.corrcoef(rotated, _KK_MINOR)[0, 1])
        if corr_minor > best_corr:
            best_corr = corr_minor
            best_key = _KEY_NAMES[root] + "m"

    # Normalize confidence to 0-1 (correlation ranges from -1 to 1)
    confidence = float(np.clip((best_corr + 1) / 2, 0, 1))
    return (best_key, confidence)


def _compute_acousticness(y: np.ndarray, sr: int, shared: dict) -> float:
    """Compute acousticness using MFCC + spectral heuristic.

    Weighted combination of:
    - MFCC1 mean (spectral shape, 30%)
    - Spectral flatness (tonal vs noisy, 30%)
    - Spectral rolloff (20%)
    - MFCC temporal variance (natural variation, 10%)
    - Crest factor (peak/RMS ratio, 10%)
    """
    import librosa

    mfcc = shared["mfcc"]
    rms = shared["rms"]

    # MFCC1 mean — acoustic instruments tend to have higher MFCC1
    mfcc1_mean = float(np.mean(mfcc[0]))
    # Normalize: typical range -200 to 200, map to 0-1
    mfcc1_score = float(np.clip((mfcc1_mean + 200) / 400, 0, 1))

    # Spectral flatness — lower = more tonal (acoustic), higher = more noisy (electronic)
    flatness = librosa.feature.spectral_flatness(y=y)[0]
    flatness_mean = float(np.mean(flatness))
    # Invert: low flatness = high acousticness
    flatness_score = float(np.clip(1.0 - flatness_mean * 10, 0, 1))

    # Spectral rolloff — acoustic tends to have lower rolloff
    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]
    rolloff_norm = float(np.mean(rolloff)) / (sr / 2)
    rolloff_score = float(np.clip(1.0 - rolloff_norm, 0, 1))

    # MFCC temporal variance — acoustic instruments have more natural variation
    mfcc_var = float(np.mean(np.var(mfcc, axis=1)))
    mfcc_var_score = float(np.clip(mfcc_var / 500, 0, 1))

    # Crest factor — acoustic tends to have higher crest factor
    rms_mean = float(np.mean(rms))
    peak = float(np.max(np.abs(y)))
    crest = peak / (rms_mean + 1e-10)
    crest_score = float(np.clip(crest / 20, 0, 1))

    acousticness = (
        mfcc1_score * 0.30 +
        flatness_score * 0.30 +
        rolloff_score * 0.20 +
        mfcc_var_score * 0.10 +
        crest_score * 0.10
    )

    return float(np.clip(acousticness, 0, 1))


def _compute_harmonic_tension(chroma: np.ndarray) -> float:
    """Compute harmonic tension from chroma co-occurrence.

    Measures the ratio of dissonant interval energy to consonant interval energy.
    Higher values = more tension/dissonance.

    Returns:
        Tension score (0-1), where 0 = purely consonant, 1 = highly dissonant.
    """
    # Consonant intervals (in semitones): unison(0), octave(12->0), fifth(7), fourth(5), major third(4), minor third(3)
    consonant_intervals = {0, 3, 4, 5, 7}
    # Dissonant intervals: minor second(1), major second(2), tritone(6)
    dissonant_intervals = {1, 2, 6}

    # Compute co-occurrence matrix from chroma
    mean_chroma = np.mean(chroma, axis=1)
    consonant_energy = 0.0
    dissonant_energy = 0.0

    for i in range(12):
        for j in range(i + 1, 12):
            interval = (j - i) % 12
            co_energy = mean_chroma[i] * mean_chroma[j]
            if interval in consonant_intervals:
                consonant_energy += co_energy
            elif interval in dissonant_intervals:
                dissonant_energy += co_energy

    total = consonant_energy + dissonant_energy
    if total < 1e-10:
        return 0.5

    tension = dissonant_energy / total
    return float(np.clip(tension, 0, 1))


def derive_features(
    y: np.ndarray, sr: int, shared: dict, file_path: Path
) -> tuple[dict[str, float | str | None], dict[str, float]]:
    """Derive classic scalar features from shared librosa intermediates.

    Returns:
        (features, confidence) tuple where:
        - features: flat dict of typed values matching TrackAnalysis typed columns
        - confidence: per-feature confidence scores (0-1)
    """
    import librosa

    features: dict[str, float | str | None] = {}
    confidence: dict[str, float] = {}

    chroma = shared["chroma"]
    spec = shared["spec"]
    rms = shared["rms"]
    n_fft = shared["n_fft"]
    bpm = shared["bpm"]
    onset_env = shared["onset_env"]

    features["bpm"] = bpm

    # BPM confidence: onset envelope energy variance (high variance = strong beat)
    onset_var = float(np.var(onset_env))
    confidence["bpm"] = float(np.clip(onset_var / 0.5, 0.2, 1.0))

    # Key detection — Krumhansl-Kessler profiles
    key_str, key_conf = _detect_key_kk(chroma)
    features["key"] = key_str
    confidence["key"] = key_conf

    # Energy (RMS energy normalized to 0-1 using dB scale)
    rms_mean = float(np.mean(rms))
    rms_db = 20 * np.log10(rms_mean + 1e-10)
    features["energy"] = float(np.clip((rms_db + 60) / 54, 0, 1))
    confidence["energy"] = 0.95  # Direct measurement

    # Spectral centroid (used by multiple features)
    spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]

    # Danceability
    pulse = shared["pulse"]
    features["danceability"] = float(np.mean(pulse))
    # PLP pulse variance — consistent pulse = high confidence
    pulse_var = float(np.var(pulse))
    confidence["danceability"] = float(np.clip(1.0 - pulse_var * 5, 0.3, 0.95))

    # Acousticness — MFCC + spectral heuristic
    features["acousticness"] = _compute_acousticness(y, sr, shared)
    confidence["acousticness"] = 0.6  # Heuristic

    # Instrumentalness — silero-vad
    vad_result = None
    try:
        from app.services.vocal_detection import detect_speech
        vad_result = detect_speech(y, sr)
    except VADError as e:
        # The model is present and did not work. This was logged at debug and therefore
        # invisible, while the spectral fallback below wrote a saturated value that looked
        # like a measurement. Warn: every track taking this path has wrong
        # instrumentalness and speechiness.
        logger.warning(f"VAD unusable, falling back to spectral heuristic: {e}")
    except Exception as e:
        logger.debug(f"VAD detection unavailable, using spectral fallback: {e}")

    if vad_result is not None:
        mean_speech_prob, _speech_frac = vad_result
        features["instrumentalness"] = float(np.clip(1.0 - mean_speech_prob * 1.5, 0, 1))
        confidence["instrumentalness"] = float(np.clip(0.5 + mean_speech_prob * 0.4, 0.5, 0.9))
    else:
        # Spectral fallback
        freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
        vocal_mask = (freqs >= 300) & (freqs <= 3000)
        vocal_energy = np.mean(spec[vocal_mask, :])
        total_energy = np.mean(spec)
        vocal_ratio = vocal_energy / (total_energy + 1e-6)
        features["instrumentalness"] = float(max(0, 1 - vocal_ratio))
        confidence["instrumentalness"] = 0.3  # Spectral fallback is unreliable

    # Speechiness — VAD + periodicity
    if vad_result is not None:
        mean_speech_prob, _speech_frac = vad_result
        # Distinguish speech from singing via RMS envelope periodicity
        # Compute autocorrelation of RMS envelope
        rms_centered = rms - np.mean(rms)
        if np.std(rms_centered) > 1e-8:
            autocorr = np.correlate(rms_centered, rms_centered, mode='full')
            autocorr = autocorr[len(autocorr) // 2:]
            autocorr = autocorr / (autocorr[0] + 1e-10)
            # Look for periodicity in singing range (0.5-4 Hz ~ frames 5-50)
            if len(autocorr) > 50:
                periodicity = float(np.max(autocorr[5:50]))
            else:
                periodicity = float(np.max(autocorr[1:]))
            periodicity = float(np.clip(periodicity, 0, 1))
        else:
            periodicity = 0.0

        # High VAD + low periodicity = speech; high VAD + high periodicity = singing
        features["speechiness"] = float(np.clip(mean_speech_prob * (1.0 - periodicity), 0, 1))
        confidence["speechiness"] = confidence["instrumentalness"]
    else:
        # ZCR fallback
        zcr = librosa.feature.zero_crossing_rate(y)[0]
        zcr_mean = np.mean(zcr)
        features["speechiness"] = float(min(1, zcr_mean * 2))
        confidence["speechiness"] = 0.3

    # Valence — enhanced with harmonic tension + tonality
    # Extract key root for mode detection
    key_root_str = key_str.rstrip("m")
    key_idx = _KEY_NAMES.index(key_root_str) if key_root_str in _KEY_NAMES else 0

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

    # New valence components
    harmonic_tension = _compute_harmonic_tension(chroma)
    tension_score = 1.0 - harmonic_tension  # Low tension = higher valence

    flatness = librosa.feature.spectral_flatness(y=y)[0]
    tonality_score = float(np.clip(1.0 - np.mean(flatness) * 10, 0, 1))

    raw_valence = (
        mode_score * 0.25 +
        brightness_score * 0.20 +
        tempo_score * 0.18 +
        contrast_score * 0.10 +
        dynamics_score * 0.07 +
        tension_score * 0.12 +
        tonality_score * 0.08
    )

    centered = raw_valence - 0.5
    spread = np.sign(centered) * (np.abs(centered) ** 0.6) * 1.8
    features["valence"] = float(np.clip(spread + 0.5, 0, 1))
    confidence["valence"] = 0.4  # Inherently subjective heuristic

    # Loudness / ReplayGain
    rg_tags = read_replaygain_tags(file_path)
    if rg_tags["loudness_lufs"] is not None:
        features["loudness_lufs"] = rg_tags["loudness_lufs"]
        features["track_peak"] = rg_tags["track_peak"]
        features["replaygain_track_gain"] = rg_tags["replaygain_track_gain"]
    else:
        try:
            import pyloudnorm as pyln

            peak = float(np.max(np.abs(y)))

            meter = pyln.Meter(sr)
            loudness = meter.integrated_loudness(y.reshape(-1, 1))

            if np.isfinite(loudness):
                features["loudness_lufs"] = float(loudness)
                features["track_peak"] = peak
                features["replaygain_track_gain"] = float(-18.0 - loudness)
            else:
                features["loudness_lufs"] = None
                features["track_peak"] = peak
                features["replaygain_track_gain"] = None
        except Exception as e:
            logging.getLogger(__name__).warning(f"Loudness measurement failed: {e}")
            features["loudness_lufs"] = None
            features["track_peak"] = None
            features["replaygain_track_gain"] = None

    return features, confidence


def _extract_features_impl(file_path_str: str) -> dict[str, float | str | None]:
    """Internal implementation of feature extraction.

    This runs in a subprocess to isolate crashes (SIGSEGV) from the main worker.
    Calls precompute_shared() + derive_features() internally.
    """
    from pathlib import Path

    file_path = Path(file_path_str)
    y, sr, shared = precompute_shared(file_path)
    features, _confidence = derive_features(y, sr, shared, file_path)
    return features


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

    Runs chromaprint in an isolated subprocess to prevent C-level assertion
    failures (e.g. channel count mismatches) from killing the analysis worker.

    Args:
        file_path: Path to audio file

    Returns:
        Tuple of (duration_seconds, fingerprint_string) or None on error
    """
    import json
    import subprocess
    import sys

    try:
        result = subprocess.run(
            [
                sys.executable, "-c",
                "import acoustid, json, sys; "
                "d, f = acoustid.fingerprint_file(sys.argv[1]); "
                "print(json.dumps([d, f.decode() if isinstance(f, bytes) else f]))",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            duration, fingerprint = json.loads(result.stdout.strip())
            return (duration, fingerprint)
        else:
            stderr = result.stderr.strip()
            if stderr:
                logger.warning(f"Fingerprint subprocess failed for {file_path}: {stderr[:200]}")
            return None
    except subprocess.TimeoutExpired:
        logger.warning(f"Fingerprint generation timed out for {file_path}")
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
