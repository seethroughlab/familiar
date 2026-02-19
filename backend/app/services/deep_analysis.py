"""Deep musical analysis service.

Computes rich harmonic, melodic, rhythmic, timbral, and structural analysis
for tracks, designed for export as markdown reports and LLM consumption.

This runs as a top-level picklable function in a ProcessPoolExecutor, following
the same pattern as run_track_features in tasks.py.
"""

import base64
import io
import logging
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np

logger = logging.getLogger(__name__)

# Independent version from ANALYSIS_VERSION (which covers CLAP/librosa features)
DEEP_ANALYSIS_VERSION = 3

# Minimum track duration for deep analysis (seconds)
MIN_DURATION_SECONDS = 30

# MIDI data directory
MIDI_DATA_DIR = Path("data/analysis")

# ─── Note/chord name tables ───────────────────────────────────────────────

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

CHORD_QUALITIES = {
    "maj": [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0],
    "min": [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0],
    "dim": [1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0],
    "aug": [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
    "7":   [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0],
    "maj7": [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1],
    "min7": [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0],
}

# Pre-compute all 84 chord templates (12 roots x 7 qualities)
CHORD_TEMPLATES: list[tuple[str, np.ndarray]] = []
for root_idx, root_name in enumerate(NOTE_NAMES):
    for quality_name, template in CHORD_QUALITIES.items():
        rotated = np.roll(template, root_idx).astype(np.float64)
        rotated /= np.linalg.norm(rotated) + 1e-10
        label = f"{root_name}{quality_name}" if quality_name != "maj" else root_name
        CHORD_TEMPLATES.append((label, rotated))

# Mode profiles (scale degrees as chroma weights)
MODE_PROFILES = {
    "Ionian (Major)": [1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1],
    "Dorian":         [1, 0, 1, 1, 0, 1, 0, 1, 0, 1, 1, 0],
    "Phrygian":       [1, 1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 0],
    "Lydian":         [1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1],
    "Mixolydian":     [1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0],
    "Aeolian (Minor)": [1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0],
    "Locrian":        [1, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0],
}

# Euclidean rhythm lookup: (pulses, steps) -> name
EUCLIDEAN_RHYTHMS = {
    (2, 5): "Khafif-e-ramal",
    (3, 7): "Ruchenitza",
    (3, 8): "Tresillo",
    (4, 7): "Aksak (4,7)",
    (4, 9): "Aksak (4,9)",
    (5, 8): "Cinquillo",
    (5, 9): "Agsag-Samai",
    (5, 11): "Moussorgsky",
    (5, 12): "Venda",
    (5, 16): "Bossa nova",
    (7, 8): "Tuareg",
    (7, 12): "West African bell",
    (7, 16): "Samba",
    (9, 16): "Rumba",
    (11, 16): "Anga",
    (13, 16): "Kpanlogo",
}

INTERVAL_NAMES = {
    -12: "Octave down", -11: "M7 down", -10: "m7 down", -9: "M6 down",
    -8: "m6 down", -7: "P5 down", -6: "Tritone down", -5: "P4 down",
    -4: "M3 down", -3: "m3 down", -2: "M2 down", -1: "m2 down",
    0: "Unison", 1: "m2 up", 2: "M2 up", 3: "m3 up",
    4: "M3 up", 5: "P4 up", 6: "Tritone up", 7: "P5 up",
    8: "m6 up", 9: "M6 up", 10: "m7 up", 11: "M7 up", 12: "Octave up",
}


# ─── Bjorklund's algorithm ────────────────────────────────────────────────

def _bjorklund(pulses: int, steps: int) -> list[int]:
    """Generate a Euclidean rhythm pattern using Bjorklund's algorithm."""
    if pulses >= steps:
        return [1] * steps
    if pulses == 0:
        return [0] * steps

    groups: list[list[int]] = [[1]] * pulses + [[0]] * (steps - pulses)
    while True:
        remainder = len(groups) - pulses
        if remainder <= 1:
            break
        new_groups = []
        for i in range(min(pulses, remainder)):
            new_groups.append(groups[i] + groups[pulses + i])
        leftover = groups[min(pulses, remainder):pulses] + groups[pulses + min(pulses, remainder):]
        groups = new_groups + leftover
        pulses = len(new_groups)

    pattern = []
    for g in groups:
        pattern.extend(g)
    return pattern


# ─── Entry point (top-level picklable for ProcessPoolExecutor) ─────────────

def run_deep_analysis(track_id: str) -> dict[str, Any]:
    """Run deep analysis for a single track.

    Creates its own sync DB session (same pattern as run_track_features).
    Returns a summary dict with status.
    """
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)

    from sqlalchemy import select

    from app.db.models import Track, TrackDeepAnalysis
    from app.db.session import sync_session_maker

    start_time = time.time()

    try:
        with sync_session_maker() as db:
            # Load track
            result = db.execute(select(Track).where(Track.id == UUID(track_id)))
            track = result.scalar_one_or_none()

            if not track:
                return {"status": "error", "error": f"Track not found: {track_id}"}

            file_path = Path(track.file_path)
            if not file_path.exists():
                return {"status": "error", "error": f"File not found: {file_path}"}

            # Check duration
            if track.duration_seconds and track.duration_seconds < MIN_DURATION_SECONDS:
                return {"status": "skipped", "reason": "Track too short for deep analysis"}

            # Check for cached analysis at current version
            cached = db.execute(
                select(TrackDeepAnalysis).where(
                    TrackDeepAnalysis.track_id == UUID(track_id),
                    TrackDeepAnalysis.version == DEEP_ANALYSIS_VERSION,
                )
            ).scalar_one_or_none()

            if cached:
                return {"status": "cached", "track_id": track_id}

            # Load audio
            import librosa
            y, sr = librosa.load(str(file_path), sr=22050, mono=True)

            # Check for near-silence
            rms_all = librosa.feature.rms(y=y)[0]
            if np.mean(rms_all) < 1e-6:
                return {"status": "skipped", "reason": "Track is near-silence"}

            # Pre-compute shared representations
            shared = _precompute_shared(y, sr)

            # Run each section analyzer with per-section try/except
            results: dict[str, Any] = {}
            section_errors: list[dict[str, str]] = []

            for section_name, analyzer in [
                ("harmonic", _analyze_harmonic),
                ("melodic", _analyze_melodic),
                ("rhythmic", _analyze_rhythmic),
                ("spectral", _analyze_spectral),
                ("structural", _analyze_structural),
                ("energy", _analyze_energy),
            ]:
                try:
                    results[section_name] = analyzer(y, sr, shared, str(file_path), track_id)
                except Exception as e:
                    logger.error(f"Deep analysis section '{section_name}' failed for {track_id}: {e}")
                    section_errors.append({"section": section_name, "error": str(e)})
                    results[section_name] = {"error": str(e)}

            elapsed = time.time() - start_time

            # Get MIDI path if melodic analysis produced one
            midi_path = results.get("melodic", {}).get("midi_path")

            # Sanitize numpy types for JSON serialization
            results = _sanitize_for_json(results)
            section_errors = _sanitize_for_json(section_errors)

            # Save to database
            from uuid import uuid4
            deep = TrackDeepAnalysis(
                id=uuid4(),
                track_id=UUID(track_id),
                version=DEEP_ANALYSIS_VERSION,
                results=results,
                midi_path=midi_path,
                section_errors=section_errors,
                analysis_duration_seconds=elapsed,
            )
            db.add(deep)
            db.commit()

            logger.info(
                f"Deep analysis complete for {track.artist} - {track.title} "
                f"({elapsed:.1f}s, {len(section_errors)} section errors)"
            )

            return {
                "status": "success",
                "track_id": track_id,
                "duration_seconds": elapsed,
                "section_errors": section_errors,
            }

    except Exception as e:
        logger.error(f"Deep analysis failed for {track_id}: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


# ─── Shared pre-computation ───────────────────────────────────────────────

def _precompute_shared(y: np.ndarray, sr: int) -> dict[str, Any]:
    """Pre-compute representations shared across section analyzers."""
    import librosa

    # STFT
    n_fft = 2048
    spec = np.abs(librosa.stft(y, n_fft=n_fft))
    power_spec = spec ** 2

    # Chroma via manual filter bank (avoids chroma_cqt SIGSEGV on macOS Accelerate)
    chroma_fb = librosa.filters.chroma(sr=sr, n_fft=n_fft)
    raw_chroma = np.dot(chroma_fb, power_spec)
    chroma = librosa.util.normalize(raw_chroma, norm=np.inf, axis=0)

    # Onset envelope + tempo (using tempo() not beat_track() — avoids SIGSEGV)
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

    # Log power spectrogram and MFCCs (shared for spectral + structural)
    log_S = librosa.power_to_db(power_spec, ref=np.max)
    mfcc = librosa.feature.mfcc(S=log_S, sr=sr, n_mfcc=13)

    # Hop length for time conversion
    hop_length = 512

    return {
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
    }


# ─── Section analyzers ────────────────────────────────────────────────────

def _analyze_harmonic(
    y: np.ndarray, sr: int, shared: dict, file_path: str, track_id: str
) -> dict[str, Any]:
    """Harmonic analysis: chords, key stability, modal character."""
    import librosa

    chroma = shared["chroma"]
    beat_frames = shared["beat_frames"]
    beat_times = shared["beat_times"]

    # Check if there's meaningful harmonic content
    chroma_variance = float(np.var(chroma))
    if chroma_variance < 0.001:
        return {"harmonic_content": False, "note": "Low chroma variance — likely percussion-only"}

    # Beat-synchronize chroma
    if len(beat_frames) > 2:
        beat_chroma = librosa.util.sync(chroma, beat_frames, aggregate=np.median)
    else:
        # No clear beats — use fixed-size windows
        window = max(1, chroma.shape[1] // 50)
        indices = np.arange(0, chroma.shape[1], window)
        beat_chroma = librosa.util.sync(chroma, indices, aggregate=np.median)

    # Chord estimation via template matching
    chords = []
    for i in range(beat_chroma.shape[1]):
        frame = beat_chroma[:, i]
        frame_norm = frame / (np.linalg.norm(frame) + 1e-10)

        best_corr = -1.0
        best_label = "N"
        for label, template in CHORD_TEMPLATES:
            corr = float(np.dot(frame_norm, template))
            if corr > best_corr:
                best_corr = corr
                best_label = label

        if best_corr < 0.4:
            best_label = "N"  # No chord

        t = float(beat_times[min(i, len(beat_times) - 1)]) if len(beat_times) > 0 else i * 0.5
        chords.append({"time": round(t, 2), "chord": best_label, "confidence": round(best_corr, 3)})

    # Smooth: merge adjacent identical chords (RLE dedup)
    smoothed: list[dict] = []
    for c in chords:
        if smoothed and smoothed[-1]["chord"] == c["chord"]:
            continue
        smoothed.append(c)

    # Short-chord merge: absorb brief chords flanked by the same chord
    if len(beat_times) > 1:
        median_beat_dur = float(np.median(np.diff(beat_times)))
    else:
        median_beat_dur = 0.5
    min_chord_dur = median_beat_dur * 1.1
    merged: list[dict] = []
    for i, c in enumerate(smoothed):
        if 0 < i < len(smoothed) - 1:
            dur = smoothed[i + 1]["time"] - c["time"]
            if dur <= min_chord_dur and merged and merged[-1]["chord"] == smoothed[i + 1]["chord"]:
                continue  # absorb short chord flanked by same chord
        merged.append(c)
    smoothed = merged

    # Most common chords (duration-weighted)
    duration = shared["duration"]
    chord_durations: dict[str, float] = {}
    for i, c in enumerate(smoothed):
        if c["chord"] == "N":
            continue
        if i + 1 < len(smoothed):
            dur = smoothed[i + 1]["time"] - c["time"]
        else:
            dur = duration - c["time"]
        chord_durations[str(c["chord"])] = chord_durations.get(str(c["chord"]), 0) + dur
    total_dur = sum(chord_durations.values()) or 1
    most_common = [
        {"chord": ch, "percentage": round(dur / total_dur * 100, 1)}
        for ch, dur in sorted(chord_durations.items(), key=lambda x: -x[1])[:8]
    ]

    # Harmonic rhythm (chord changes per bar)
    bpm = shared["bpm"]
    n_bars = duration / (4 * 60 / bpm) if bpm > 0 else 1
    harmonic_rhythm = round(len(smoothed) / max(n_bars, 1), 2)

    # Key stability: windowed key estimation
    window_size = max(1, chroma.shape[1] // 8)
    key_windows = []
    for start in range(0, chroma.shape[1] - window_size + 1, window_size):
        window_chroma = np.mean(chroma[:, start:start + window_size], axis=1)
        key_idx = int(np.argmax(window_chroma))
        key_windows.append(NOTE_NAMES[key_idx])

    unique_keys = len(set(key_windows))
    key_stability = "stable" if unique_keys <= 2 else "drifting" if unique_keys <= 4 else "modulating"

    # Modal character
    avg_chroma = np.mean(chroma, axis=1)
    best_mode = "Unknown"
    best_mode_corr = -1.0
    for root_idx in range(12):
        for mode_name, profile in MODE_PROFILES.items():
            rotated = np.roll(profile, root_idx).astype(np.float64)
            rotated /= np.linalg.norm(rotated) + 1e-10
            avg_norm = avg_chroma / (np.linalg.norm(avg_chroma) + 1e-10)
            corr = float(np.dot(avg_norm, rotated))
            if corr > best_mode_corr:
                best_mode_corr = corr
                best_mode = f"{NOTE_NAMES[root_idx]} {mode_name}"

    # Key/mode confidence over time (windowed full mode matching)
    hop_length = shared["hop_length"]
    duration = shared["duration"]
    beat_frames_h = shared["beat_frames"]
    # Determine window in chroma frames: 8 bars worth, slide by 4 bars
    if len(beat_frames_h) >= 16 and bpm > 0:
        frames_per_beat = sr / (bpm / 60.0) / hop_length
        frames_per_bar = frames_per_beat * 4
        win_frames = int(frames_per_bar * 8)
        slide_frames = int(frames_per_bar * 4)
    else:
        # Fallback: 8 equal windows
        win_frames = max(1, chroma.shape[1] // 8)
        slide_frames = max(1, win_frames // 2)

    # Pre-compute all 84 mode templates (12 roots x 7 modes)
    mode_templates = []
    for root_idx in range(12):
        for mode_name, profile in MODE_PROFILES.items():
            rotated = np.roll(profile, root_idx).astype(np.float64)
            rotated /= np.linalg.norm(rotated) + 1e-10
            mode_templates.append((f"{NOTE_NAMES[root_idx]} {mode_name}", rotated))

    key_mode_timeline: list[dict[str, Any]] = []
    for start in range(0, chroma.shape[1] - win_frames + 1, slide_frames):
        end = start + win_frames
        win_chroma = np.mean(chroma[:, start:end], axis=1)
        win_norm = win_chroma / (np.linalg.norm(win_chroma) + 1e-10)

        best_label = "Unknown"
        best_conf = -1.0
        for label, tmpl in mode_templates:
            corr = float(np.dot(win_norm, tmpl))
            if corr > best_conf:
                best_conf = corr
                best_label = label

        t_start = round(start * hop_length / sr, 2)
        t_end = round(min(end * hop_length / sr, duration), 2)
        key_mode_timeline.append({
            "start": t_start,
            "end": t_end,
            "key_mode": best_label,
            "confidence": round(best_conf, 3),
        })

    return {
        "harmonic_content": True,
        "chords": smoothed,
        "most_common_chords": most_common,
        "harmonic_rhythm": harmonic_rhythm,
        "key_stability": key_stability,
        "key_windows": key_windows,
        "modal_character": best_mode,
        "modal_confidence": round(best_mode_corr, 3),
        "key_mode_timeline": key_mode_timeline,
    }


def _compute_interval_histogram(
    notes: list[dict],
) -> tuple[dict[str, float], list[int], str, float]:
    """Compute interval histogram, character, and avg size from a sorted note list.

    Returns (histogram, raw_intervals, character, avg_size).
    """
    from collections import Counter

    intervals = []
    for i in range(1, len(notes)):
        interval = notes[i]["pitch"] - notes[i - 1]["pitch"]
        if -12 <= interval <= 12:
            intervals.append(interval)

    interval_counts = Counter(intervals)
    total_intervals = sum(interval_counts.values()) or 1
    histogram = {
        str(iv): round(cnt / total_intervals * 100, 1)
        for iv, cnt in sorted(interval_counts.items())
    }

    abs_intervals = [abs(iv) for iv in intervals]
    avg_size = float(np.mean(abs_intervals)) if abs_intervals else 0.0
    if avg_size < 2.5:
        character = "stepwise-dominant"
    elif avg_size > 4.0:
        character = "leap-heavy"
    else:
        character = "mixed"

    return histogram, intervals, character, round(avg_size, 2)


def _analyze_melodic(
    y: np.ndarray, sr: int, shared: dict, file_path: str, track_id: str
) -> dict[str, Any]:
    """Melodic analysis using basic-pitch for MIDI transcription."""
    try:
        from basic_pitch.inference import predict
    except ImportError:
        return {
            "degraded": True,
            "error": "basic-pitch not installed. Install with: pip install 'basic-pitch[onnx]'",
        }

    # Run basic-pitch prediction
    _model_output, midi_data, note_events = predict(file_path)

    if not note_events or len(note_events) == 0:
        return {"degraded": True, "error": "No notes detected by basic-pitch"}

    # Save MIDI file
    midi_path = None
    try:
        MIDI_DATA_DIR.mkdir(parents=True, exist_ok=True)
        midi_file = MIDI_DATA_DIR / f"{track_id}.mid"
        midi_data.write(str(midi_file))
        midi_path = str(midi_file)
    except Exception as e:
        logger.warning(f"Failed to save MIDI file: {e}")

    # Extract note data: note_events is list of (start_time, end_time, pitch_midi, velocity, ...)
    notes = []
    for ev in note_events:
        notes.append({
            "start": float(ev[0]),
            "end": float(ev[1]),
            "pitch": int(ev[2]),
            "velocity": float(ev[3]) if len(ev) > 3 else 0.5,
        })

    # Sort by start time
    notes.sort(key=lambda n: n["start"])

    # Pitch range
    pitches = [n["pitch"] for n in notes]
    pitch_range = {
        "low": int(min(pitches)),
        "high": int(max(pitches)),
        "low_note": _midi_to_note(int(min(pitches))),
        "high_note": _midi_to_note(int(max(pitches))),
    }

    # 10th-90th percentile range
    p10, p90 = int(np.percentile(pitches, 10)), int(np.percentile(pitches, 90))
    pitch_range["primary_low"] = _midi_to_note(p10)
    pitch_range["primary_high"] = _midi_to_note(p90)

    # Interval histogram (between consecutive notes)
    interval_histogram, intervals, interval_character, avg_interval = (
        _compute_interval_histogram(notes)
    )

    from collections import Counter

    # Voice separation by register
    register_bounds = {"bass": (0, 48), "mid": (48, 72), "lead": (72, 128)}
    register_intervals: dict[str, Any] = {}
    for reg_name, (lo, hi) in register_bounds.items():
        reg_notes = [n for n in notes if lo <= n["pitch"] < hi]
        entry: dict[str, Any] = {"note_count": len(reg_notes)}
        if len(reg_notes) >= 10:
            hist, _ivs, char, avg = _compute_interval_histogram(reg_notes)
            entry["interval_histogram"] = hist
            entry["interval_character"] = char
            entry["avg_interval_size"] = avg
        register_intervals[reg_name] = entry

    # Interval transition matrix
    interval_transitions_common: list[dict[str, Any]] = []
    interval_transitions_unexpected: list[dict[str, Any]] = []
    if len(intervals) >= 3:
        pair_counts: dict[tuple[int, int], int] = Counter(
            (intervals[i], intervals[i + 1]) for i in range(len(intervals) - 1)
        )
        total_pairs = sum(pair_counts.values())

        # Top 10 most common
        for (a, b), cnt in sorted(pair_counts.items(), key=lambda x: -x[1])[:10]:
            interval_transitions_common.append({
                "from": INTERVAL_NAMES.get(a, f"{a:+d}"),
                "to": INTERVAL_NAMES.get(b, f"{b:+d}"),
                "from_semitones": a,
                "to_semitones": b,
                "count": cnt,
                "percentage": round(cnt / total_pairs * 100, 1),
            })

        # Independence model for unexpected transitions
        from_counts: dict[int, int] = Counter(intervals[:-1])
        to_counts: dict[int, int] = Counter(intervals[1:])
        total_from = sum(from_counts.values()) or 1
        total_to = sum(to_counts.values()) or 1

        surprises: list[tuple[float, int, int, int]] = []
        for (a, b), observed in pair_counts.items():
            p_from = from_counts[a] / total_from
            p_to = to_counts[b] / total_to
            expected = p_from * p_to * total_pairs
            if expected > 0.5:  # only consider pairs with meaningful expectation
                ratio = observed / expected
                surprises.append((ratio, a, b, observed))

        for ratio, a, b, cnt in sorted(surprises, key=lambda x: -x[0])[:5]:
            interval_transitions_unexpected.append({
                "from": INTERVAL_NAMES.get(a, f"{a:+d}"),
                "to": INTERVAL_NAMES.get(b, f"{b:+d}"),
                "from_semitones": a,
                "to_semitones": b,
                "count": cnt,
                "observed_expected_ratio": round(ratio, 2),
            })

    # Phrase detection: segment by onset gaps > 0.3s
    phrases = []
    current_phrase: list[dict] = [notes[0]] if notes else []
    for i in range(1, len(notes)):
        gap = notes[i]["start"] - notes[i - 1]["end"]
        if gap > 0.3:
            if current_phrase:
                phrases.append(current_phrase)
            current_phrase = [notes[i]]
        else:
            current_phrase.append(notes[i])
    if current_phrase:
        phrases.append(current_phrase)

    # Contour: per-phrase classification using intervals (octave-jump resistant)
    contours = []
    for phrase in phrases[:50]:  # Limit
        if len(phrase) < 3:
            contours.append("flat")
            continue
        phrase_pitches = [n["pitch"] for n in phrase]
        # Compute intervals, skipping octave jumps (>6 semitones)
        intervals_p = []
        for j in range(1, len(phrase_pitches)):
            iv = phrase_pitches[j] - phrase_pitches[j - 1]
            if abs(iv) > 6:
                continue  # skip octave jumps
            intervals_p.append(iv)

        if len(intervals_p) < 2:
            contours.append("flat")
            continue

        mid = len(intervals_p) // 2
        first_half_net = sum(intervals_p[:mid])
        second_half_net = sum(intervals_p[mid:])
        up_count = sum(1 for iv in intervals_p if iv > 0)
        down_count = sum(1 for iv in intervals_p if iv < 0)
        total_moves = up_count + down_count or 1

        if first_half_net > 1 and second_half_net < -1:
            contours.append("arch")
        elif first_half_net < -1 and second_half_net > 1:
            contours.append("valley")
        elif up_count / total_moves > 0.6:
            contours.append("ascending")
        elif down_count / total_moves > 0.6:
            contours.append("descending")
        else:
            contours.append("flat")

    contour_counts = Counter(contours)
    dominant_contour = contour_counts.most_common(1)[0][0] if contour_counts else "unknown"

    # Pitch class distribution
    pc_counts = Counter(p % 12 for p in pitches)
    total_pc = sum(pc_counts.values()) or 1
    pitch_class_dist = {
        NOTE_NAMES[int(pc)]: round(cnt / total_pc * 100, 1)
        for pc, cnt in sorted(pc_counts.items())
    }

    # Note density (notes per beat)
    duration = shared["duration"]
    bpm = shared["bpm"]
    beats_total = (duration / 60.0) * bpm
    note_density = round(len(notes) / max(beats_total, 1), 2)

    # Contour distribution as percentages
    total_contours = sum(contour_counts.values()) or 1
    contour_summary = {k: round(v / total_contours * 100, 1) for k, v in contour_counts.items()}

    # Register movement: linear trend of mean pitch per phrase
    if len(phrases) >= 2:
        phrase_means = [float(np.mean([n["pitch"] for n in p])) for p in phrases]
        x = np.arange(len(phrase_means))
        slope = float(np.polyfit(x, phrase_means, 1)[0])
        if slope > 0.3:
            register_trend = "rising"
        elif slope < -0.3:
            register_trend = "falling"
        else:
            register_trend = "stable"
        register_slope = round(slope, 3)
    else:
        register_trend = "insufficient data"
        register_slope = 0.0

    # Phrase lengths
    phrase_lengths = [
        round(phrase[-1]["end"] - phrase[0]["start"], 2) for phrase in phrases if phrase
    ]
    avg_phrase_length = round(float(np.mean(phrase_lengths)), 2) if phrase_lengths else 0

    return {
        "degraded": False,
        "midi_path": midi_path,
        "note_count": len(notes),
        "pitch_range": pitch_range,
        "interval_histogram": interval_histogram,
        "interval_character": interval_character,
        "avg_interval_size": round(avg_interval, 2),
        "phrase_count": len(phrases),
        "avg_phrase_length_seconds": avg_phrase_length,
        "contour_summary": contour_summary,
        "dominant_contour": dominant_contour,
        "register_trend": register_trend,
        "register_slope": register_slope,
        "pitch_class_distribution": pitch_class_dist,
        "note_density_per_beat": note_density,
        "register_intervals": register_intervals,
        "interval_transitions_common": interval_transitions_common,
        "interval_transitions_unexpected": interval_transitions_unexpected,
    }


def _analyze_rhythmic(
    y: np.ndarray, sr: int, shared: dict, file_path: str, track_id: str
) -> dict[str, Any]:
    """Rhythmic analysis: swing, syncopation, Euclidean patterns, tempo stability."""
    import librosa

    onset_env = shared["onset_env"]
    beat_times = shared["beat_times"]
    bpm = shared["bpm"]

    # Check for clear beat
    if np.max(onset_env) < 0.05:
        return {"has_clear_beat": False, "bpm": bpm}

    # Onset times
    onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
    onset_times = librosa.frames_to_time(onset_frames, sr=sr)

    if len(beat_times) < 4:
        return {"has_clear_beat": False, "bpm": bpm}

    # Swing ratio: compare even vs odd eighth-note positions
    ibis = np.diff(beat_times)  # Inter-beat intervals
    swing_ratios = []
    for i in range(len(beat_times) - 1):
        beat_start = beat_times[i]
        beat_end = beat_times[i + 1]
        beat_dur = beat_end - beat_start
        if beat_dur < 0.1:
            continue
        # Find onsets within this beat
        mask = (onset_times >= beat_start) & (onset_times < beat_end)
        beat_onsets = onset_times[mask]
        if len(beat_onsets) >= 2:
            # Position of second onset relative to beat
            rel_pos = (beat_onsets[1] - beat_start) / beat_dur
            if 0.3 < rel_pos < 0.8:
                swing_ratios.append(rel_pos)

    swing_ratio = round(float(np.mean(swing_ratios) * 100), 1) if swing_ratios else 50.0

    # Syncopation index (LHL measure — simplified)
    # Compare onset positions to a straight grid
    syncopation_scores = []
    for i in range(len(beat_times) - 1):
        beat_start = beat_times[i]
        beat_end = beat_times[i + 1]
        beat_dur = beat_end - beat_start
        if beat_dur < 0.05:
            continue
        mask = (onset_times >= beat_start) & (onset_times < beat_end)
        beat_onsets = onset_times[mask]
        for onset in beat_onsets:
            rel = (onset - beat_start) / beat_dur
            # Distance from nearest grid position (0, 0.25, 0.5, 0.75)
            grid = [0, 0.25, 0.5, 0.75]
            min_dist = min(abs(rel - g) for g in grid)
            syncopation_scores.append(min_dist)

    syncopation_index = round(float(np.mean(syncopation_scores) * 4), 3) if syncopation_scores else 0.0

    # Tempo stability
    if len(ibis) > 4:
        tempo_cv = float(np.std(ibis) / (np.mean(ibis) + 1e-10))
        if tempo_cv < 0.05:
            tempo_stability = "grid-locked"
        elif tempo_cv < 0.15:
            tempo_stability = "slight drift"
        else:
            tempo_stability = "breathing"
    else:
        tempo_stability = "insufficient data"
        tempo_cv = 0.0

    # Euclidean pattern detection
    # Quantize onsets to 16-step grid per measure
    euclidean_patterns = []
    if len(beat_times) >= 8:
        measures = []
        beats_per_measure = 4
        for i in range(0, len(beat_times) - beats_per_measure, beats_per_measure):
            measure_start = beat_times[i]
            measure_end = beat_times[min(i + beats_per_measure, len(beat_times) - 1)]
            measures.append((measure_start, measure_end))

        # Average quantized pattern across measures
        pattern_accumulator = np.zeros(16)
        measure_count = 0
        for m_start, m_end in measures[:16]:  # Limit
            m_dur = m_end - m_start
            if m_dur < 0.1:
                continue
            mask = (onset_times >= m_start) & (onset_times < m_end)
            m_onsets = onset_times[mask]
            for onset in m_onsets:
                step = int((onset - m_start) / m_dur * 16) % 16
                pattern_accumulator[step] += 1
            measure_count += 1

        if measure_count > 0:
            pattern_accumulator /= measure_count
            # Threshold to binary
            threshold = np.mean(pattern_accumulator)
            binary_pattern = (pattern_accumulator > threshold).astype(int)

            # Compare against known Euclidean rhythms
            for (k, n), name in EUCLIDEAN_RHYTHMS.items():
                if n != 16:
                    continue
                e_pattern = _bjorklund(k, n)
                # Try all rotations
                best_hamming = n
                for rotation in range(n):
                    rotated = e_pattern[rotation:] + e_pattern[:rotation]
                    hamming = sum(a != b for a, b in zip(binary_pattern, rotated))
                    best_hamming = min(best_hamming, hamming)

                if best_hamming <= 2:
                    euclidean_patterns.append({
                        "pattern": f"E({k},{n})",
                        "name": name,
                        "hamming_distance": best_hamming,
                    })

    return {
        "has_clear_beat": True,
        "bpm": round(bpm, 1),
        "swing_ratio": swing_ratio,
        "syncopation_index": syncopation_index,
        "tempo_stability": tempo_stability,
        "tempo_cv": round(tempo_cv, 4),
        "euclidean_patterns": euclidean_patterns,
        "onset_count": len(onset_times),
    }


def _analyze_spectral(
    y: np.ndarray, sr: int, shared: dict, file_path: str, track_id: str
) -> dict[str, Any]:
    """Spectral/timbral analysis: brightness, band energy, MFCCs, contrast."""
    import librosa

    # Spectral centroid (brightness curve)
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    centroid_mean = float(np.mean(centroid))
    centroid_normalized = centroid_mean / (sr / 2)

    if centroid_normalized < 0.1:
        brightness = "dark"
    elif centroid_normalized < 0.25:
        brightness = "neutral"
    else:
        brightness = "bright"

    # Brightness trajectory
    n_segments = 8
    seg_len = max(1, len(centroid) // n_segments)
    brightness_curve = [
        round(float(np.mean(centroid[i * seg_len:(i + 1) * seg_len])), 1)
        for i in range(n_segments)
    ]

    # Band energy distribution (6 bands)
    spec = shared["spec"]
    freqs = np.linspace(0, sr / 2, spec.shape[0])

    bands = {
        "sub_bass": (20, 60),
        "bass": (60, 250),
        "low_mid": (250, 1000),
        "mid": (1000, 4000),
        "high_mid": (4000, 8000),
        "high": (8000, min(16000, sr / 2)),
    }

    band_energy = {}
    total_energy = float(np.sum(spec ** 2)) + 1e-10
    for band_name, (lo, hi) in bands.items():
        mask = (freqs >= lo) & (freqs < hi)
        energy = float(np.sum(spec[mask] ** 2))
        band_energy[band_name] = round(energy / total_energy * 100, 1)

    # MFCCs (13 coefficients, averaged) — use shared pre-computed MFCCs
    mfcc = shared["mfcc"]
    mfcc_mean = [round(float(m), 3) for m in np.mean(mfcc, axis=1)]

    # Spectral contrast
    contrast = librosa.feature.spectral_contrast(y=y, sr=sr)
    contrast_mean = [round(float(c), 3) for c in np.mean(contrast, axis=1)]

    # Spectral rolloff
    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]
    rolloff_mean = round(float(np.mean(rolloff)), 1)

    # Spectral flatness (noise vs tonal)
    flatness = librosa.feature.spectral_flatness(y=y)[0]
    flatness_mean = round(float(np.mean(flatness)), 4)

    return {
        "brightness": brightness,
        "brightness_curve": brightness_curve,
        "centroid_hz": round(centroid_mean, 1),
        "band_energy": band_energy,
        "mfcc_mean": mfcc_mean,
        "spectral_contrast": contrast_mean,
        "rolloff_hz": rolloff_mean,
        "flatness": flatness_mean,
    }


def _find_segment_boundaries(
    sim_matrix: np.ndarray,
    threshold_factor: float = 0.25,
    rms: np.ndarray | None = None,
) -> np.ndarray:
    """Find segment boundaries using Foote novelty with optional RMS supplementation."""
    import librosa
    from scipy.signal import find_peaks

    try:
        novelty = librosa.segment.novelty(sim_matrix, kernel_size=16)
        threshold = np.mean(novelty) + np.std(novelty) * threshold_factor
        peaks, _ = find_peaks(novelty, height=threshold, distance=5)
    except Exception:
        peaks = np.array([])

    # Supplement with energy-based boundaries from RMS envelope
    if rms is not None and len(rms) > 0:
        try:
            n_frames = sim_matrix.shape[0]
            rms_ds = np.interp(
                np.linspace(0, len(rms) - 1, n_frames),
                np.arange(len(rms)),
                rms,
            )
            rms_diff = np.abs(np.diff(rms_ds))
            rms_threshold = np.mean(rms_diff) + np.std(rms_diff) * 1.5
            rms_peaks, _ = find_peaks(rms_diff, height=rms_threshold, distance=5)

            # Merge RMS peaks with novelty peaks if not within 3 frames of existing
            for rp in rms_peaks:
                if len(peaks) == 0 or np.min(np.abs(peaks - rp)) > 3:
                    peaks = np.append(peaks, rp)
            peaks = np.sort(peaks)
        except Exception:
            pass

    return peaks


def _analyze_structural(
    y: np.ndarray, sr: int, shared: dict, file_path: str, track_id: str
) -> dict[str, Any]:
    """Structural analysis: self-similarity, segmentation, form labeling."""

    chroma = shared["chroma"]
    mfcc = shared["mfcc"]
    duration = shared["duration"]

    # Combined chroma+MFCC feature matrix for self-similarity
    target_frames = min(200, chroma.shape[1])
    hop = max(1, chroma.shape[1] // target_frames)
    chroma_ds = chroma[:, ::hop]
    mfcc_ds = mfcc[:, ::hop]

    # Normalize each feature set globally before stacking
    chroma_norm = chroma_ds / (np.linalg.norm(chroma_ds) + 1e-10)
    mfcc_norm = mfcc_ds / (np.linalg.norm(mfcc_ds) + 1e-10)
    features = np.vstack([chroma_norm, mfcc_norm])  # 25-row matrix

    # Compute cosine similarity on combined features
    norms = np.linalg.norm(features, axis=0, keepdims=True) + 1e-10
    features_normed = features / norms
    sim_matrix = np.dot(features_normed.T, features_normed)

    # Render self-similarity matrix as PNG
    ssm_png_b64 = None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(4, 4), dpi=100)
        ax.imshow(sim_matrix, origin="lower", cmap="magma", aspect="equal")
        ax.set_xlabel("Time")
        ax.set_ylabel("Time")
        ax.set_title("Self-Similarity")
        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        ssm_png_b64 = base64.b64encode(buf.read()).decode("ascii")
    except Exception as e:
        logger.warning(f"Failed to render self-similarity matrix: {e}")

    # Segmentation using Foote novelty + RMS supplementation
    rms = shared["rms"]
    peaks = _find_segment_boundaries(sim_matrix, threshold_factor=0.25, rms=rms)

    # Convert peak frames to times
    frames_to_time_factor = duration / max(sim_matrix.shape[0], 1)
    boundary_times = [0.0] + [round(float(p * frames_to_time_factor), 2) for p in peaks] + [round(duration, 2)]

    # Build segments
    segments = []
    for i in range(len(boundary_times) - 1):
        segments.append({
            "start": boundary_times[i],
            "end": boundary_times[i + 1],
            "duration": round(boundary_times[i + 1] - boundary_times[i], 2),
        })

    # Single-section retry: if only 1 segment for track > 60s, retry with lower threshold
    if len(segments) <= 1 and duration > 60:
        peaks = _find_segment_boundaries(sim_matrix, threshold_factor=0.0, rms=rms)
        if len(peaks) > 0:
            boundary_times = [0.0] + [round(float(p * frames_to_time_factor), 2) for p in peaks] + [round(duration, 2)]
            segments = []
            for i in range(len(boundary_times) - 1):
                segments.append({
                    "start": boundary_times[i],
                    "end": boundary_times[i + 1],
                    "duration": round(boundary_times[i + 1] - boundary_times[i], 2),
                })

    # Section labeling by chroma similarity
    section_labels = []
    label_map: dict[int, str] = {}
    current_label_idx = 0
    label_chars = "ABCDEFGHIJKLMNOP"

    for i, seg in enumerate(segments):
        # Get average chroma for this segment
        start_frame = int(seg["start"] / duration * chroma.shape[1]) if duration > 0 else 0
        end_frame = int(seg["end"] / duration * chroma.shape[1]) if duration > 0 else chroma.shape[1]
        end_frame = max(start_frame + 1, min(end_frame, chroma.shape[1]))
        seg_chroma = np.mean(chroma[:, start_frame:end_frame], axis=1)
        seg_chroma_norm = seg_chroma / (np.linalg.norm(seg_chroma) + 1e-10)

        # Compare to previous sections
        matched = False
        for prev_idx, prev_label in label_map.items():
            prev_seg = segments[prev_idx]
            ps_frame = int(prev_seg["start"] / duration * chroma.shape[1]) if duration > 0 else 0
            pe_frame = int(prev_seg["end"] / duration * chroma.shape[1]) if duration > 0 else chroma.shape[1]
            pe_frame = max(ps_frame + 1, min(pe_frame, chroma.shape[1]))
            prev_chroma = np.mean(chroma[:, ps_frame:pe_frame], axis=1)
            prev_norm = prev_chroma / (np.linalg.norm(prev_chroma) + 1e-10)

            similarity = float(np.dot(seg_chroma_norm, prev_norm))
            if similarity > 0.85:
                section_labels.append(prev_label)
                matched = True
                break

        if not matched:
            label = label_chars[current_label_idx % len(label_chars)]
            section_labels.append(label)
            label_map[i] = label
            current_label_idx += 1

    # Annotate segments with labels
    for i, seg in enumerate(segments):
        seg["label"] = section_labels[i] if i < len(section_labels) else "?"

    form = "".join(section_labels)

    return {
        "segments": segments,
        "form": form,
        "section_count": len(segments),
        "avg_section_length": round(float(np.mean([s["duration"] for s in segments])), 2) if segments else 0,
        "self_similarity_png": ssm_png_b64,
    }


def _analyze_energy(
    y: np.ndarray, sr: int, shared: dict, file_path: str, track_id: str
) -> dict[str, Any]:
    """Energy and dynamics analysis."""
    rms = shared["rms"]
    duration = shared["duration"]

    # RMS in dB
    rms_db = 20 * np.log10(rms + 1e-10)

    # Dynamic range (5th to 95th percentile)
    p5 = float(np.percentile(rms_db, 5))
    p95 = float(np.percentile(rms_db, 95))
    dynamic_range_db = round(p95 - p5, 1)

    # RMS curve (normalized, downsampled to ~32 points)
    n_points = 32
    seg_len = max(1, len(rms) // n_points)
    rms_max = float(np.max(rms)) + 1e-10
    rms_curve = [
        round(float(np.mean(rms[i * seg_len:(i + 1) * seg_len]) / rms_max), 3)
        for i in range(min(n_points, len(rms) // seg_len))
    ]

    # Energy shape classification
    if len(rms_curve) >= 4:
        first_quarter = np.mean(rms_curve[:len(rms_curve) // 4])
        last_quarter = np.mean(rms_curve[-len(rms_curve) // 4:])
        mid = np.mean(rms_curve[len(rms_curve) // 4:-len(rms_curve) // 4])

        if last_quarter > first_quarter * 1.3 and mid < last_quarter:
            energy_shape = "gradual build"
        elif first_quarter > last_quarter * 1.3:
            energy_shape = "fade out"
        elif mid > first_quarter * 1.3 and mid > last_quarter * 1.3:
            energy_shape = "peak in middle"
        elif np.std(rms_curve) < 0.1:
            energy_shape = "consistent"
        else:
            energy_shape = "dynamic"
    else:
        energy_shape = "insufficient data"

    # Build/drop detection
    builds = []
    window = max(1, len(rms) // 16)
    for i in range(0, len(rms) - window * 2, window):
        seg1 = float(np.mean(rms[i:i + window]))
        seg2 = float(np.mean(rms[i + window:i + window * 2]))
        ratio = seg2 / (seg1 + 1e-10)
        t = round(i / len(rms) * duration, 2)
        if ratio > 2.0:
            builds.append({"time": t, "type": "build", "ratio": round(ratio, 2)})
        elif ratio < 0.4:
            builds.append({"time": t, "type": "drop", "ratio": round(ratio, 2)})

    return {
        "rms_curve": rms_curve,
        "dynamic_range_db": dynamic_range_db,
        "energy_shape": energy_shape,
        "builds": builds[:20],  # Limit
        "rms_mean_db": round(float(np.mean(rms_db)), 1),
        "rms_peak_db": round(float(np.max(rms_db)), 1),
    }


# ─── Helper functions ──────────────────────────────────────────────────────

def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert numpy types to native Python types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def _midi_to_note(midi_num: int) -> str:
    """Convert MIDI number to note name (e.g., 60 -> 'C4')."""
    octave = (midi_num // 12) - 1
    note = NOTE_NAMES[midi_num % 12]
    return f"{note}{octave}"


def _format_time(seconds: float) -> str:
    """Format seconds to M:SS."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


# ─── Report generation ─────────────────────────────────────────────────────

def generate_report(results: dict[str, Any], track_metadata: dict[str, Any]) -> str:
    """Generate a single-track markdown report from cached analysis JSON."""
    lines = []

    artist = track_metadata.get("artist", "Unknown Artist")
    title = track_metadata.get("title", "Unknown Title")
    album = track_metadata.get("album", "")
    duration = track_metadata.get("duration_seconds", 0)

    lines.append(f"# Track Analysis: {artist} - {title}")
    lines.append("")

    meta_parts = []
    if album:
        meta_parts.append(f"**Album:** {album}")
    if duration:
        meta_parts.append(f"**Duration:** {_format_time(duration)}")
    if meta_parts:
        lines.append(" | ".join(meta_parts))
        lines.append("")

    lines.append("---")
    lines.append("")

    # Overview
    harmonic = results.get("harmonic", {})
    rhythmic = results.get("rhythmic", {})
    energy = results.get("energy", {})

    lines.append("## Overview")
    bpm = rhythmic.get("bpm", "?")
    stability = rhythmic.get("tempo_stability", "?")
    lines.append(f"- **Tempo:** {bpm} BPM ({stability})")

    modal = harmonic.get("modal_character", "?")
    modal_conf = harmonic.get("modal_confidence", 0)
    lines.append(f"- **Key/Mode:** {modal} (confidence: {round(modal_conf * 100)}%)")

    shape = energy.get("energy_shape", "?")
    lines.append(f"- **Energy shape:** {shape}")

    dyn = energy.get("dynamic_range_db", "?")
    lines.append(f"- **Dynamic range:** {dyn} dB")
    lines.append("")

    # Harmonic Character
    lines.append("## Harmonic Character")
    if not harmonic.get("harmonic_content", True):
        lines.append(f"- {harmonic.get('note', 'No significant harmonic content detected')}")
    else:
        hr = harmonic.get("harmonic_rhythm", "?")
        lines.append(f"- **Chord change frequency:** {hr} changes/bar")

        ks = harmonic.get("key_stability", "?")
        lines.append(f"- **Key stability:** {ks}")

        lines.append(f"- **Modal quality:** {modal}")

        mc = harmonic.get("most_common_chords", [])
        if mc:
            chord_str = ", ".join(f"{c['chord']} ({c['percentage']}%)" for c in mc[:6])
            lines.append(f"- **Most common chords:** {chord_str}")

        kmt = harmonic.get("key_mode_timeline", [])
        if kmt:
            lines.append("- **Key/mode over time:**")
            for entry in kmt:
                lines.append(
                    f"  - {_format_time(entry['start'])}–{_format_time(entry['end'])}: "
                    f"{entry['key_mode']} ({round(entry['confidence'] * 100)}%)"
                )
    lines.append("")

    # Melodic Character
    melodic = results.get("melodic", {})
    lines.append("## Melodic Character")
    if melodic.get("degraded"):
        lines.append(f"> *{melodic.get('error', 'Melodic analysis unavailable')}*")
    else:
        pr = melodic.get("pitch_range", {})
        if pr:
            lines.append(
                f"- **Pitch range:** {pr.get('low_note', '?')} to {pr.get('high_note', '?')} "
                f"(primary: {pr.get('primary_low', '?')} to {pr.get('primary_high', '?')})"
            )

        ic = melodic.get("interval_character", "?")
        avg_iv = melodic.get("avg_interval_size", "?")
        lines.append(f"- **Interval character:** {ic} (avg {avg_iv} semitones)")

        pc = melodic.get("phrase_count", 0)
        apl = melodic.get("avg_phrase_length_seconds", 0)
        lines.append(f"- **Phrases:** {pc} phrases, avg {apl}s")

        dc = melodic.get("dominant_contour", "?")
        cs = melodic.get("contour_summary", {})
        if cs:
            dist_parts = [f"{k} {v}%" for k, v in sorted(cs.items(), key=lambda x: -x[1])]
            lines.append(f"- **Contour tendency:** {dc} ({', '.join(dist_parts)})")
        else:
            lines.append(f"- **Contour tendency:** {dc}")

        rt = melodic.get("register_trend")
        if rt:
            lines.append(f"- **Register movement:** {rt}")

        nd = melodic.get("note_density_per_beat", "?")
        lines.append(f"- **Note density:** {nd} notes/beat")

        # Voice register summary
        ri = melodic.get("register_intervals", {})
        if ri:
            reg_parts = []
            for reg_name in ("bass", "mid", "lead"):
                reg = ri.get(reg_name, {})
                nc = reg.get("note_count", 0)
                if nc > 0:
                    char = reg.get("interval_character", "")
                    avg = reg.get("avg_interval_size", "")
                    detail = f", {char}, avg {avg}st" if char else ""
                    reg_parts.append(f"{reg_name}: {nc} notes{detail}")
            if reg_parts:
                lines.append(f"- **Register breakdown:** {' | '.join(reg_parts)}")

        # Interval transitions
        itc = melodic.get("interval_transitions_common", [])
        if itc:
            top5 = itc[:5]
            parts = [f"{t['from']}\u2192{t['to']} ({t['percentage']}%)" for t in top5]
            lines.append(f"- **Common transitions:** {', '.join(parts)}")

        itu = melodic.get("interval_transitions_unexpected", [])
        if itu:
            top3 = itu[:3]
            parts = [
                f"{t['from']}\u2192{t['to']} ({t['observed_expected_ratio']}x expected)"
                for t in top3
            ]
            lines.append(f"- **Unexpected transitions:** {', '.join(parts)}")
    lines.append("")

    # Rhythmic Character
    lines.append("## Rhythmic Character")
    if not rhythmic.get("has_clear_beat", True):
        lines.append("- No clear beat detected (ambient/drone)")
    else:
        sw = rhythmic.get("swing_ratio", 50)
        swing_desc = "straight" if abs(sw - 50) < 5 else "light swing" if sw < 60 else "triplet swing"
        lines.append(f"- **Swing:** {sw}% ({swing_desc})")

        si = rhythmic.get("syncopation_index", 0)
        lines.append(f"- **Syncopation:** {si}")

        ts = rhythmic.get("tempo_stability", "?")
        lines.append(f"- **Tempo stability:** {ts}")

        ep = rhythmic.get("euclidean_patterns", [])
        if ep:
            for p in ep:
                lines.append(f"- **Euclidean pattern:** {p['pattern']} — {p['name']} (distance: {p['hamming_distance']})")
    lines.append("")

    # Timbral Character
    spectral = results.get("spectral", {})
    lines.append("## Timbral Character")
    br = spectral.get("brightness", "?")
    lines.append(f"- **Brightness:** {br} (centroid: {spectral.get('centroid_hz', '?')} Hz)")

    be = spectral.get("band_energy", {})
    if be:
        parts = [f"{k.replace('_', ' ')}: {v}%" for k, v in be.items()]
        lines.append(f"- **Band energy:** {' / '.join(parts)}")

    fl = spectral.get("flatness", 0)
    tonal_desc = "tonal" if fl < 0.01 else "mixed" if fl < 0.1 else "noisy/textural"
    lines.append(f"- **Spectral character:** {tonal_desc} (flatness: {fl})")
    lines.append("")

    # Structure
    structural = results.get("structural", {})
    lines.append("## Structure")
    sc = structural.get("section_count", 0)
    form = structural.get("form", "?")
    lines.append(f"- **Sections:** {sc} detected")
    lines.append(f"- **Form:** {form}")
    asl = structural.get("avg_section_length", 0)
    lines.append(f"- **Average section length:** {asl}s")

    segs = structural.get("segments", [])
    if segs:
        lines.append("- **Section map:**")
        for seg in segs:
            lines.append(
                f"  - {_format_time(seg['start'])}–{_format_time(seg['end'])} — "
                f"Section {seg.get('label', '?')} ({seg['duration']}s)"
            )

    ssm_png = structural.get("self_similarity_png")
    if ssm_png:
        lines.append("")
        lines.append("<details>")
        lines.append("<summary>Self-Similarity Matrix</summary>")
        lines.append("")
        lines.append(f"![Self-Similarity Matrix](data:image/png;base64,{ssm_png})")
        lines.append("")
        lines.append("</details>")
    lines.append("")

    # Energy
    lines.append("## Energy & Dynamics")
    lines.append(f"- **Dynamic range:** {dyn} dB")
    lines.append(f"- **Energy shape:** {shape}")
    lines.append(f"- **Mean RMS:** {energy.get('rms_mean_db', '?')} dB")
    lines.append(f"- **Peak RMS:** {energy.get('rms_peak_db', '?')} dB")

    builds = energy.get("builds", [])
    if builds:
        for b in builds[:5]:
            lines.append(f"- **{b['type'].title()}** at {_format_time(b['time'])} (ratio: {b['ratio']})")
    lines.append("")

    # Raw data reference (collapsible)
    lines.append("## Raw Data Reference")
    lines.append("")

    # Chord sequence
    chord_seq = harmonic.get("chords", [])
    if chord_seq:
        lines.append("<details>")
        lines.append("<summary>Chord sequence (click to expand)</summary>")
        lines.append("")
        lines.append("| Time | Chord | Confidence |")
        lines.append("|------|-------|------------|")
        display_limit = 200
        total = len(chord_seq)
        for c in chord_seq[:display_limit]:
            lines.append(f"| {_format_time(c['time'])} | {c['chord']} | {c['confidence']} |")
        if total > display_limit:
            lines.append(f"\n*Showing first {display_limit} of {total} total chord changes.*")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # Interval histogram
    ih = melodic.get("interval_histogram", {})
    if ih:
        lines.append("<details>")
        lines.append("<summary>Interval histogram</summary>")
        lines.append("")
        lines.append("| Interval (semitones) | Name | Frequency |")
        lines.append("|---------------------|------|-----------|")
        for iv_str, pct in sorted(ih.items(), key=lambda x: -x[1]):
            iv = int(iv_str)
            name = INTERVAL_NAMES.get(iv, f"{iv:+d}")
            lines.append(f"| {iv:+d} | {name} | {pct}% |")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # Per-register interval histograms
    ri = melodic.get("register_intervals", {})
    has_register_data = any(
        ri.get(r, {}).get("interval_histogram") for r in ("bass", "mid", "lead")
    )
    if has_register_data:
        lines.append("<details>")
        lines.append("<summary>Per-register interval histograms</summary>")
        lines.append("")
        for reg_name in ("bass", "mid", "lead"):
            reg = ri.get(reg_name, {})
            reg_hist = reg.get("interval_histogram", {})
            if not reg_hist:
                continue
            lines.append(f"**{reg_name.title()}** ({reg.get('note_count', 0)} notes, "
                         f"{reg.get('interval_character', '?')}, avg {reg.get('avg_interval_size', '?')}st)")
            lines.append("")
            lines.append("| Interval | Name | Frequency |")
            lines.append("|----------|------|-----------|")
            for iv_str, pct in sorted(reg_hist.items(), key=lambda x: -x[1]):
                iv = int(iv_str)
                name = INTERVAL_NAMES.get(iv, f"{iv:+d}")
                lines.append(f"| {iv:+d} | {name} | {pct}% |")
            lines.append("")
        lines.append("</details>")
        lines.append("")

    # Interval transition matrix
    itc = melodic.get("interval_transitions_common", [])
    if itc:
        lines.append("<details>")
        lines.append("<summary>Interval transitions</summary>")
        lines.append("")
        lines.append("**Most common transitions (top 10):**")
        lines.append("")
        lines.append("| From | To | Count | Percentage |")
        lines.append("|------|----|-------|------------|")
        for t in itc:
            lines.append(f"| {t['from']} | {t['to']} | {t['count']} | {t['percentage']}% |")
        lines.append("")
        itu = melodic.get("interval_transitions_unexpected", [])
        if itu:
            lines.append("**Most unexpected transitions (top 5):**")
            lines.append("")
            lines.append("| From | To | Count | Observed/Expected |")
            lines.append("|------|----|-------|-------------------|")
            for t in itu:
                lines.append(f"| {t['from']} | {t['to']} | {t['count']} | {t['observed_expected_ratio']}x |")
            lines.append("")
        lines.append("</details>")
        lines.append("")

    # Key/mode timeline table
    kmt = harmonic.get("key_mode_timeline", [])
    if kmt:
        lines.append("<details>")
        lines.append("<summary>Key/mode timeline</summary>")
        lines.append("")
        lines.append("| Time Range | Key/Mode | Confidence |")
        lines.append("|------------|----------|------------|")
        for entry in kmt:
            lines.append(
                f"| {_format_time(entry['start'])}–{_format_time(entry['end'])} "
                f"| {entry['key_mode']} | {round(entry['confidence'] * 100)}% |"
            )
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # MFCCs
    mfcc = spectral.get("mfcc_mean", [])
    if mfcc:
        lines.append("<details>")
        lines.append("<summary>MFCC coefficients</summary>")
        lines.append("")
        lines.append("| Coefficient | Value |")
        lines.append("|------------|-------|")
        for i, v in enumerate(mfcc):
            lines.append(f"| MFCC-{i} | {v} |")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines)


def generate_comparative_report(
    analyses: list[dict[str, Any]],
    tracks: list[dict[str, Any]],
) -> str:
    """Generate a multi-track comparative report.

    Works from already-cached analysis data — no audio re-processing.
    """
    if not analyses or not tracks:
        return "# Comparative Analysis\n\nNo tracks to compare."

    lines = []

    # Individual reports first
    for analysis, track_meta in zip(analyses, tracks):
        lines.append(generate_report(analysis, track_meta))
        lines.append("")
        lines.append("---")
        lines.append("")

    # Comparative section
    lines.append("# Comparative Analysis")
    lines.append("")

    # Collect metrics for comparison
    metrics: dict[str, list[tuple[str, float]]] = {
        "tempo": [],
        "swing": [],
        "syncopation": [],
        "brightness": [],
        "dynamic_range": [],
        "note_density": [],
    }

    for analysis, track_meta in zip(analyses, tracks):
        label = f"{track_meta.get('artist', '?')} - {track_meta.get('title', '?')}"

        rhythmic = analysis.get("rhythmic", {})
        spectral = analysis.get("spectral", {})
        energy = analysis.get("energy", {})
        melodic = analysis.get("melodic", {})

        if rhythmic.get("bpm"):
            metrics["tempo"].append((label, rhythmic["bpm"]))
        if rhythmic.get("swing_ratio"):
            metrics["swing"].append((label, rhythmic["swing_ratio"]))
        if rhythmic.get("syncopation_index"):
            metrics["syncopation"].append((label, rhythmic["syncopation_index"]))
        if spectral.get("centroid_hz"):
            metrics["brightness"].append((label, spectral["centroid_hz"]))
        if energy.get("dynamic_range_db"):
            metrics["dynamic_range"].append((label, energy["dynamic_range_db"]))
        if melodic.get("note_density_per_beat"):
            metrics["note_density"].append((label, melodic["note_density_per_beat"]))

    # Shared qualities
    lines.append("## Shared Qualities")
    shared_qualities = _find_shared_qualities(analyses, tracks)
    if shared_qualities:
        for q in shared_qualities:
            lines.append(f"- {q}")
    else:
        lines.append("- No strong shared qualities detected across all tracks")
    lines.append("")

    # Key differences
    lines.append("## Key Differences")
    differences = _find_key_differences(analyses, tracks)
    if differences:
        for d in differences:
            lines.append(f"- {d}")
    else:
        lines.append("- Tracks are relatively similar across measured dimensions")
    lines.append("")

    # Rankings table
    lines.append("## Rankings")
    lines.append("")
    lines.append("| Metric | Ranking (high to low) |")
    lines.append("|--------|----------------------|")

    for metric_name, values in metrics.items():
        if len(values) >= 2:
            sorted_vals = sorted(values, key=lambda x: -x[1])
            ranking = " > ".join(
                f"{label.split(' - ')[-1]} ({v:.1f})" for label, v in sorted_vals
            )
            lines.append(f"| {metric_name.replace('_', ' ').title()} | {ranking} |")

    lines.append("")

    # Per-artist DNA
    from collections import defaultdict
    artist_tracks: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for analysis, track_meta in zip(analyses, tracks):
        artist = track_meta.get("artist", "Unknown")
        artist_tracks[artist].append((analysis, track_meta))

    if len(artist_tracks) > 1:
        lines.append("## Musical DNA by Artist")
        lines.append("")

        for artist, items in artist_tracks.items():
            lines.append(f"### {artist}")

            # Aggregate metrics across this artist's tracks
            tempos = [
                a.get("rhythmic", {}).get("bpm", 0)
                for a, _ in items if a.get("rhythmic", {}).get("bpm")
            ]
            modes = [
                a.get("harmonic", {}).get("modal_character", "")
                for a, _ in items if a.get("harmonic", {}).get("modal_character")
            ]
            shapes = [
                a.get("energy", {}).get("energy_shape", "")
                for a, _ in items if a.get("energy", {}).get("energy_shape")
            ]

            if tempos:
                lines.append(f"- **Tempo range:** {min(tempos):.0f}–{max(tempos):.0f} BPM")
            if modes:
                lines.append(f"- **Key/Mode tendency:** {', '.join(set(modes))}")
            if shapes:
                lines.append(f"- **Energy profile:** {', '.join(set(shapes))}")
            lines.append("")

    return "\n".join(lines)


def _find_shared_qualities(
    analyses: list[dict[str, Any]],
    tracks: list[dict[str, Any]],
) -> list[str]:
    """Find qualities shared across all analyzed tracks."""
    shared = []

    # Check modal tendencies
    modes = [
        a.get("harmonic", {}).get("modal_character", "")
        for a in analyses if a.get("harmonic", {}).get("modal_character")
    ]
    if modes and len(set(modes)) == 1:
        shared.append(f"All tracks share the same modal character: {modes[0]}")

    # Check energy shape
    shapes = [
        a.get("energy", {}).get("energy_shape", "")
        for a in analyses if a.get("energy", {}).get("energy_shape")
    ]
    if shapes and len(set(shapes)) == 1:
        shared.append(f"All tracks share the same energy shape: {shapes[0]}")

    # Check brightness
    brightness_vals = [
        a.get("spectral", {}).get("brightness", "")
        for a in analyses if a.get("spectral", {}).get("brightness")
    ]
    if brightness_vals and len(set(brightness_vals)) == 1:
        shared.append(f"All tracks share a {brightness_vals[0]} timbral character")

    # Check syncopation range
    syncs = [
        a.get("rhythmic", {}).get("syncopation_index", 0)
        for a in analyses if a.get("rhythmic", {}).get("syncopation_index") is not None
    ]
    if syncs and all(s > 0.5 for s in syncs):
        shared.append(f"High syncopation across all tracks (>{min(syncs):.2f})")
    elif syncs and all(s < 0.2 for s in syncs):
        shared.append("Low syncopation across all tracks — straight rhythmic feel")

    return shared


def _find_key_differences(
    analyses: list[dict[str, Any]],
    tracks: list[dict[str, Any]],
) -> list[str]:
    """Find key differences between analyzed tracks."""
    differences = []

    # Tempo spread
    tempos = [
        (t.get("artist", "?"), a.get("rhythmic", {}).get("bpm", 0))
        for a, t in zip(analyses, tracks) if a.get("rhythmic", {}).get("bpm")
    ]
    if len(tempos) >= 2:
        temps = [t[1] for t in tempos]
        spread = max(temps) - min(temps)
        if spread > 30:
            fastest = max(tempos, key=lambda x: x[1])
            slowest = min(tempos, key=lambda x: x[1])
            differences.append(
                f"Wide tempo range: {fastest[0]} ({fastest[1]:.0f} BPM) vs "
                f"{slowest[0]} ({slowest[1]:.0f} BPM)"
            )

    # Brightness spread
    centroids = [
        (t.get("artist", "?"), a.get("spectral", {}).get("centroid_hz", 0))
        for a, t in zip(analyses, tracks) if a.get("spectral", {}).get("centroid_hz")
    ]
    if len(centroids) >= 2:
        vals = [c[1] for c in centroids]
        ratio = max(vals) / (min(vals) + 1)
        if ratio > 1.5:
            brightest = max(centroids, key=lambda x: x[1])
            darkest = min(centroids, key=lambda x: x[1])
            differences.append(
                f"Significant brightness difference: {brightest[0]} (bright, {brightest[1]:.0f} Hz) vs "
                f"{darkest[0]} (dark, {darkest[1]:.0f} Hz)"
            )

    # Note density (if melodic available)
    densities = [
        (t.get("artist", "?"), a.get("melodic", {}).get("note_density_per_beat", 0))
        for a, t in zip(analyses, tracks)
        if a.get("melodic", {}).get("note_density_per_beat") and not a.get("melodic", {}).get("degraded")
    ]
    if len(densities) >= 2:
        vals = [d[1] for d in densities]
        if max(vals) > min(vals) * 2:
            densest = max(densities, key=lambda x: x[1])
            sparsest = min(densities, key=lambda x: x[1])
            differences.append(
                f"Melodic density varies: {densest[0]} ({densest[1]:.1f} notes/beat) vs "
                f"{sparsest[0]} ({sparsest[1]:.1f} notes/beat)"
            )

    return differences
