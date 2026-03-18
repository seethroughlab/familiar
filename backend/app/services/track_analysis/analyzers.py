"""Section analyzers for track analysis.

Contains all _analyze_* functions (harmonic, melodic, rhythmic, spectral,
structural, energy), plus supporting helpers (_bjorklund, _parse_chord_root,
_chord_to_roman, _detect_progressions, _precompute_shared,
_compute_interval_histogram, _find_segment_boundaries, _add_melodic_sketches).
"""

import io
import logging
from typing import Any, cast

import numpy as np

from app.services.track_analysis.constants import (
    _QUALITY_TO_ROMAN_SUFFIX,
    _ROMAN_MAJOR,
    _ROMAN_MINOR,
    CHORD_TEMPLATES,
    COMMON_PROGRESSIONS,
    EUCLIDEAN_RHYTHMS,
    INTERVAL_NAMES,
    MIDI_DATA_DIR,
    MODE_PROFILES,
    NOTE_NAMES,
)
from app.services.track_analysis.utils import (
    _duration_symbol,
    _midi_to_note,
)

logger = logging.getLogger(__name__)


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


# ─── Roman numeral analysis ──────────────────────────────────────────────

def _parse_chord_root(chord_name: str) -> tuple[int, str] | None:
    """Parse a chord name into (root_pitch_class, quality_suffix).

    Returns None for 'N' (no chord).
    """
    if chord_name == "N" or not chord_name:
        return None

    # Try two-char root first (e.g., C#, Bb)
    if len(chord_name) >= 2 and chord_name[1] in ("#", "b"):
        root_str = chord_name[:2]
        quality = chord_name[2:] or "maj"
    else:
        root_str = chord_name[0]
        quality = chord_name[1:] or "maj"

    # Handle flats by converting to sharps
    flat_to_sharp = {"Db": "C#", "Eb": "D#", "Fb": "E", "Gb": "F#", "Ab": "G#", "Bb": "A#", "Cb": "B"}
    root_str = flat_to_sharp.get(root_str, root_str)

    try:
        root_pc = NOTE_NAMES.index(root_str)
    except ValueError:
        return None

    return root_pc, quality


def _chord_to_roman(chord_name: str, key_root: int, is_minor: bool) -> str:
    """Convert an absolute chord name to a Roman numeral relative to key_root."""
    parsed = _parse_chord_root(chord_name)
    if parsed is None:
        return "N"

    root_pc, quality = parsed
    degree = (root_pc - key_root) % 12

    roman_table = _ROMAN_MINOR if is_minor else _ROMAN_MAJOR
    numeral = roman_table[degree]

    # Determine case: minor/dim chords get lowercase, major/aug get uppercase
    if quality in ("min", "min7"):
        numeral = numeral.lower()
    elif quality in ("maj", "maj7", "7", "aug"):
        numeral = numeral.upper() if numeral[0].isalpha() else numeral[0] + numeral[1:].upper()

    suffix = _QUALITY_TO_ROMAN_SUFFIX.get(quality, quality)
    return f"{numeral}{suffix}"


def _detect_progressions(
    chord_sequence: list[dict],
    key_root: int,
    duration: float,
) -> list[dict[str, Any]]:
    """Detect common chord progressions in the sequence.

    Returns list of detected progressions with name and count.
    """
    # Build degree sequence (skip N chords)
    degrees = []
    for c in chord_sequence:
        parsed = _parse_chord_root(c["chord"])
        if parsed is None:
            continue
        root_pc, _quality = parsed
        degree = (root_pc - key_root) % 12
        degrees.append(degree)

    if len(degrees) < 3:
        return []

    detected = []
    for prog_name, prog_degrees in COMMON_PROGRESSIONS.items():
        prog_len = len(prog_degrees)
        if prog_len > len(degrees):
            continue

        count = 0
        for i in range(len(degrees) - prog_len + 1):
            window = tuple(degrees[i:i + prog_len])
            if window == prog_degrees:
                count += 1

        if count > 0:
            detected.append({"name": prog_name, "occurrences": count})

    # Sort by frequency
    detected.sort(key=lambda x: -cast(int, x["occurrences"]))
    return detected[:5]


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

    # Run-length-encode: merge consecutive entries with the same key_mode
    merged_timeline: list[dict[str, Any]] = []
    for entry in key_mode_timeline:
        if merged_timeline and merged_timeline[-1]["key_mode"] == entry["key_mode"]:
            merged_timeline[-1]["end"] = entry["end"]
            merged_timeline[-1]["conf_min"] = min(merged_timeline[-1]["conf_min"], entry["confidence"])
            merged_timeline[-1]["conf_max"] = max(merged_timeline[-1]["conf_max"], entry["confidence"])
            # Keep average confidence for backward compat
            merged_timeline[-1]["_conf_sum"] += entry["confidence"]
            merged_timeline[-1]["_conf_count"] += 1
            merged_timeline[-1]["confidence"] = round(
                merged_timeline[-1]["_conf_sum"] / merged_timeline[-1]["_conf_count"], 3
            )
        else:
            merged_timeline.append({
                "start": entry["start"],
                "end": entry["end"],
                "key_mode": entry["key_mode"],
                "confidence": entry["confidence"],
                "conf_min": entry["confidence"],
                "conf_max": entry["confidence"],
                "_conf_sum": entry["confidence"],
                "_conf_count": 1,
            })
    # Strip internal accumulator fields
    for entry in merged_timeline:
        entry.pop("_conf_sum", None)
        entry.pop("_conf_count", None)
    key_mode_timeline = merged_timeline

    # Snap overlapping windows: set each entry's end to the next entry's start
    for i in range(len(key_mode_timeline) - 1):
        if key_mode_timeline[i]["end"] > key_mode_timeline[i + 1]["start"]:
            key_mode_timeline[i]["end"] = key_mode_timeline[i + 1]["start"]

    # Roman numeral analysis relative to detected key
    # Parse key root from best_mode (e.g., "D Ionian (Major)" -> D -> 2)
    key_root_name = best_mode.split()[0] if best_mode and best_mode != "Unknown" else None
    is_minor_key = any(m in best_mode.lower() for m in ("aeolian", "minor", "dorian", "phrygian", "locrian"))

    roman_chords: list[dict[str, Any]] = []
    detected_progressions: list[dict[str, Any]] = []

    if key_root_name and key_root_name in NOTE_NAMES:
        key_root = NOTE_NAMES.index(key_root_name)

        # Convert most common chords to Roman numerals
        for mc_entry in most_common:
            rn = _chord_to_roman(str(mc_entry["chord"]), key_root, is_minor_key)
            roman_chords.append({
                "chord": mc_entry["chord"],
                "roman": rn,
                "percentage": mc_entry["percentage"],
            })

        # Detect common progressions
        detected_progressions = _detect_progressions(smoothed, key_root, duration)

    return {
        "harmonic_content": True,
        "chords": smoothed,
        "most_common_chords": most_common,
        "roman_numeral_chords": roman_chords,
        "detected_progressions": detected_progressions,
        "harmonic_rhythm": harmonic_rhythm,
        "key_stability": key_stability,
        "key_windows": key_windows,
        "modal_character": best_mode,
        "modal_confidence": round(best_mode_corr, 3),
        "key_mode_timeline": key_mode_timeline,
    }


def _compute_interval_histogram(
    notes: list[dict],
) -> tuple[dict[str, float], list[int], str, float, float,
           dict[str, float], str, float]:
    """Compute interval histogram, character, and avg size from a sorted note list.

    Returns (histogram, raw_intervals, character, avg_size, unison_pct,
             histogram_no_unison, character_no_unison, avg_size_no_unison).
    """
    from collections import Counter

    intervals = []
    for i in range(1, len(notes)):
        interval = notes[i]["pitch"] - notes[i - 1]["pitch"]
        if -12 <= interval <= 12:
            intervals.append(interval)

    interval_counts = Counter(intervals)
    total_intervals = sum(interval_counts.values()) or 1

    # Count unisons separately
    unison_count = interval_counts.get(0, 0)
    unison_pct = round(unison_count / total_intervals * 100, 1)

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

    # No-unison variant
    non_unison = [iv for iv in intervals if iv != 0]
    if non_unison:
        nu_counts = Counter(non_unison)
        total_nu = sum(nu_counts.values()) or 1
        histogram_no_unison = {
            str(iv): round(cnt / total_nu * 100, 1)
            for iv, cnt in sorted(nu_counts.items())
        }
        abs_nu = [abs(iv) for iv in non_unison]
        avg_size_nu = float(np.mean(abs_nu))
        if avg_size_nu < 2.5:
            character_nu = "stepwise-dominant"
        elif avg_size_nu > 4.0:
            character_nu = "leap-heavy"
        else:
            character_nu = "mixed"
        avg_size_nu = round(avg_size_nu, 2)
    else:
        histogram_no_unison = {}
        character_nu = character
        avg_size_nu = round(avg_size, 2)

    return (histogram, intervals, character, round(avg_size, 2), unison_pct,
            histogram_no_unison, character_nu, avg_size_nu)


def _analyze_melodic(
    y: np.ndarray, sr: int, shared: dict, file_path: str, track_id: str,
    truncate_duration: float | None = None,
) -> dict[str, Any]:
    """Melodic analysis using basic-pitch for MIDI transcription.

    Args:
        truncate_duration: If set, write a temporary truncated WAV for basic-pitch
            (which re-reads from disk). Prevents OOM on long tracks.
    """
    import tempfile

    import soundfile as sf

    try:
        from basic_pitch.inference import predict
    except ImportError:
        return {
            "degraded": True,
            "error": "basic-pitch not installed. Install with: pip install 'basic-pitch[onnx]'",
        }

    # For long tracks, write truncated audio to a temp WAV so basic-pitch
    # doesn't load the full file into memory
    predict_path = file_path
    tmp_file = None
    if truncate_duration is not None:
        try:
            tmp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            sf.write(tmp_file.name, y, sr)
            predict_path = tmp_file.name
        except Exception as e:
            logger.warning(f"Failed to write truncated WAV, using original: {e}")
            predict_path = file_path
            tmp_file = None

    try:
        # Run basic-pitch prediction
        _model_output, midi_data, note_events = predict(predict_path)
    finally:
        # Clean up temp file
        if tmp_file is not None:
            import os
            try:
                os.unlink(tmp_file.name)
            except OSError:
                pass

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

    # Deduplicate consecutive same-pitch notes (basic-pitch transcription artifact)
    if notes:
        deduped = [notes[0]]
        for n in notes[1:]:
            prev = deduped[-1]
            gap = n["start"] - prev["end"]
            if n["pitch"] == prev["pitch"] and gap < 0.05:
                prev["end"] = max(prev["end"], n["end"])
                prev["velocity"] = max(prev["velocity"], n["velocity"])
            else:
                deduped.append(n)
        notes = deduped

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
    (interval_histogram, intervals, interval_character, avg_interval, unison_pct,
     interval_histogram_no_unison, interval_character_no_unison,
     avg_interval_no_unison) = _compute_interval_histogram(notes)

    from collections import Counter

    # Voice separation by register
    register_bounds = {"bass": (0, 48), "mid": (48, 72), "lead": (72, 128)}
    register_intervals: dict[str, Any] = {}
    for reg_name, (lo, hi) in register_bounds.items():
        reg_notes = [n for n in notes if lo <= n["pitch"] < hi]
        entry: dict[str, Any] = {"note_count": len(reg_notes)}
        if len(reg_notes) >= 10:
            (hist, _ivs, char, avg, _upct,
             hist_nu, char_nu, avg_nu) = _compute_interval_histogram(reg_notes)
            entry["interval_histogram"] = hist
            entry["interval_character"] = char
            entry["avg_interval_size"] = avg
            entry["interval_histogram_no_unison"] = hist_nu
            entry["interval_character_no_unison"] = char_nu
            entry["avg_interval_size_no_unison"] = avg_nu
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

    # Phrase detection: segment by onset gaps (tempo-relative threshold)
    bpm = shared.get("bpm", 120)
    beat_duration = 60.0 / bpm
    phrase_gap = max(beat_duration * 2, 1.0)  # At least 2 beats or 1 second

    phrases = []
    current_phrase: list[dict] = [notes[0]] if notes else []
    for i in range(1, len(notes)):
        gap = notes[i]["start"] - notes[i - 1]["end"]
        if gap > phrase_gap:
            if current_phrase:
                phrases.append(current_phrase)
            current_phrase = [notes[i]]
        else:
            current_phrase.append(notes[i])
    if current_phrase:
        phrases.append(current_phrase)

    phrase_detection_method = "gap"

    # Density-based fallback when gap detection yields too few phrases
    if len(phrases) < 4 and len(notes) >= 20:
        track_duration = notes[-1]["end"] - notes[0]["start"]
        if track_duration > 0:
            # Compute note onset density in 4-second sliding windows (0.5s hop)
            window_size = 4.0
            hop = 0.5
            onsets = np.array([n["start"] for n in notes])
            window_centers = np.arange(
                onsets[0] + window_size / 2,
                onsets[-1] - window_size / 2 + hop,
                hop,
            )
            density = np.array([
                float(np.sum((onsets >= t - window_size / 2) & (onsets < t + window_size / 2)))
                / window_size
                for t in window_centers
            ])

            if len(density) > 4:
                # Smooth with moving-average kernel (~5% of curve length)
                kernel_size = max(3, int(len(density) * 0.05)) | 1  # ensure odd
                kernel = np.ones(kernel_size) / kernel_size
                smoothed = np.convolve(density, kernel, mode="same")

                # Find local minima (no scipy)
                order = max(2, len(smoothed) // 20)
                minima = [
                    i for i in range(order, len(smoothed) - order)
                    if all(smoothed[i] <= smoothed[i - j] for j in range(1, order + 1))
                    and all(smoothed[i] <= smoothed[i + j] for j in range(1, order + 1))
                ]

                # If too many boundaries, keep only the deepest troughs
                max_phrases = max(20, int(track_duration / 10))
                if len(minima) > max_phrases:
                    # Sort by depth (ascending density) and keep deepest
                    minima.sort(key=lambda idx: smoothed[idx])
                    minima = sorted(minima[:max_phrases])

                if len(minima) >= 1:
                    # Convert minima indices to times
                    boundary_times = [float(window_centers[m]) for m in minima]

                    # Re-segment notes at boundary times
                    density_phrases: list[list[dict]] = []
                    current: list[dict] = []
                    b_idx = 0
                    for n in notes:
                        if b_idx < len(boundary_times) and n["start"] >= boundary_times[b_idx]:
                            if current:
                                density_phrases.append(current)
                            current = [n]
                            b_idx += 1
                        else:
                            current.append(n)
                    if current:
                        density_phrases.append(current)

                    if len(density_phrases) >= 4:
                        phrases = density_phrases
                        phrase_detection_method = "density-fallback"

    # Mark low confidence if still too few phrases
    if len(phrases) < 4 and len(notes) >= 20:
        phrase_detection_method = "low"

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

    # Register movement: linear trend of mean pitch in fixed 30s windows
    window_duration = 30.0
    track_duration = notes[-1]["end"] - notes[0]["start"] if notes else 0

    if track_duration >= 30 and len(notes) >= 20:
        window_starts = np.arange(notes[0]["start"], notes[-1]["end"], window_duration)
        window_means = []
        for ws in window_starts:
            window_notes = [n for n in notes if ws <= n["start"] < ws + window_duration]
            if len(window_notes) >= 5:
                window_means.append(float(np.mean([n["pitch"] for n in window_notes])))

        if len(window_means) >= 2:
            slope = float(np.polyfit(np.arange(len(window_means)), window_means, 1)[0])
            register_trend = "rising" if slope > 0.3 else "falling" if slope < -0.3 else "stable"
            register_slope = round(slope, 3)
        else:
            register_trend = "insufficient data"
            register_slope = 0.0
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
        "unison_pct": unison_pct,
        "interval_histogram_no_unison": interval_histogram_no_unison,
        "interval_character_no_unison": interval_character_no_unison,
        "avg_interval_size_no_unison": avg_interval_no_unison,
        "phrase_count": len(phrases),
        "phrase_detection_method": phrase_detection_method,
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

    # Rhythm pattern classification using the 16-step grid
    rhythm_pattern = "unclassified"
    if len(beat_times) >= 8:
        # Reuse pattern_accumulator from Euclidean analysis
        measures_p = []
        beats_per_measure = 4
        for i in range(0, len(beat_times) - beats_per_measure, beats_per_measure):
            m_start = beat_times[i]
            m_end = beat_times[min(i + beats_per_measure, len(beat_times) - 1)]
            measures_p.append((m_start, m_end))

        kick_pattern = np.zeros(16)
        snare_pattern = np.zeros(16)
        measure_count_p = 0

        for m_start, m_end in measures_p[:16]:
            m_dur = m_end - m_start
            if m_dur < 0.1:
                continue
            # Separate low-freq onsets (kick) from mid-freq (snare)
            # Use spectral centroid of each onset region
            mask = (onset_times >= m_start) & (onset_times < m_end)
            m_onsets = onset_times[mask]
            for onset_t in m_onsets:
                step = int((onset_t - m_start) / m_dur * 16) % 16
                # Approximate frequency separation: use onset position in spectrum
                onset_sample = int(onset_t * sr)
                window_size = min(1024, len(y) - onset_sample)
                if window_size > 256:
                    onset_spec = np.abs(np.fft.rfft(y[onset_sample:onset_sample + window_size]))
                    freqs = np.fft.rfftfreq(window_size, 1.0 / sr)
                    centroid_onset = float(np.sum(freqs * onset_spec) / (np.sum(onset_spec) + 1e-10))
                    if centroid_onset < 300:
                        kick_pattern[step] += 1
                    elif centroid_onset < 2000:
                        snare_pattern[step] += 1
            measure_count_p += 1

        if measure_count_p > 0:
            kick_pattern /= measure_count_p
            snare_pattern /= measure_count_p

            kick_thresh = np.mean(kick_pattern) * 0.8
            snare_thresh = np.mean(snare_pattern) * 0.8
            kick_binary = kick_pattern > kick_thresh
            snare_binary = snare_pattern > snare_thresh

            # Four-on-the-floor: kick on beats 1,5,9,13 (every quarter note)
            four_otf = all(kick_binary[i] for i in [0, 4, 8, 12])
            # Half-time: snare only on beat 3 (step 8), not on 2 (step 4)
            half_time = snare_binary[8] and not snare_binary[4]
            # Breakbeat: syncopated kick (hits on off-beats)
            offbeat_kicks = sum(kick_binary[i] for i in [1, 3, 5, 7, 9, 11, 13, 15])
            onbeat_kicks = sum(kick_binary[i] for i in [0, 4, 8, 12])

            if four_otf and not half_time:
                rhythm_pattern = "four-on-the-floor"
            elif half_time:
                rhythm_pattern = "half-time"
            elif offbeat_kicks > onbeat_kicks:
                rhythm_pattern = "breakbeat"
            elif abs(swing_ratio - 50) > 8:
                rhythm_pattern = "shuffle"
            elif onbeat_kicks >= 2:
                rhythm_pattern = "standard backbeat"
            else:
                rhythm_pattern = "unclassified"

    # Rhythmic density over time (8 equal segments)
    n_density_segments = 8
    density_timeline = []
    seg_duration = shared["duration"] / n_density_segments if shared["duration"] > 0 else 1
    for i in range(n_density_segments):
        seg_start = i * seg_duration
        seg_end = (i + 1) * seg_duration
        mask = (onset_times >= seg_start) & (onset_times < seg_end)
        onset_count_seg = int(np.sum(mask))
        # Normalize to onsets per second
        density = round(onset_count_seg / max(seg_duration, 0.1), 1)
        density_timeline.append(density)

    # Classify density trajectory
    if len(density_timeline) >= 4:
        first_q = np.mean(density_timeline[:2])
        last_q = np.mean(density_timeline[-2:])
        if last_q > first_q * 1.3:
            density_shape = "building"
        elif first_q > last_q * 1.3:
            density_shape = "thinning"
        elif np.std(density_timeline) < np.mean(density_timeline) * 0.15:
            density_shape = "consistent"
        else:
            density_shape = "varied"
    else:
        density_shape = "insufficient data"

    return {
        "has_clear_beat": True,
        "bpm": round(bpm, 1),
        "swing_ratio": swing_ratio,
        "syncopation_index": syncopation_index,
        "tempo_stability": tempo_stability,
        "tempo_cv": round(tempo_cv, 4),
        "euclidean_patterns": euclidean_patterns,
        "onset_count": len(onset_times),
        "rhythm_pattern": rhythm_pattern,
        "density_timeline": density_timeline,
        "density_shape": density_shape,
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
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Find segment boundaries using Foote novelty with optional RMS supplementation."""
    import librosa
    from scipy.signal import find_peaks

    try:
        novelty = librosa.segment.novelty(sim_matrix, kernel_size=16)
        threshold = np.mean(novelty) + np.std(novelty) * threshold_factor
        peaks, properties = find_peaks(novelty, height=threshold, distance=5)
    except Exception:
        peaks = np.array([])
        properties = {}
        novelty = np.array([])

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
            rms_peaks, rms_props = find_peaks(rms_diff, height=rms_threshold, distance=5)

            # Merge RMS peaks with novelty peaks if not within 3 frames of existing
            for rp in rms_peaks:
                if len(peaks) == 0 or np.min(np.abs(peaks - rp)) > 3:
                    peaks = np.append(peaks, rp)
                    # Append the corresponding peak height
                    rp_idx = np.where(rms_peaks == rp)[0]
                    if len(rp_idx) > 0 and "peak_heights" in rms_props:
                        properties.setdefault("peak_heights", np.array([]))
                        properties["peak_heights"] = np.append(
                            properties["peak_heights"],
                            rms_props["peak_heights"][rp_idx[0]],
                        )
            peaks = np.sort(peaks)
        except Exception:
            pass

    peak_heights = properties.get("peak_heights", np.array([]))
    return peaks, peak_heights, novelty


def _analyze_structural(
    y: np.ndarray, sr: int, shared: dict, file_path: str, track_id: str
) -> dict[str, Any]:
    """Structural analysis: self-similarity, segmentation, form labeling."""
    import librosa

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

    # Render self-similarity matrix as PNG and save to disk
    ssm_png_path = None
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
        png_data = buf.read()

        # Save to disk instead of storing base64 in JSON
        MIDI_DATA_DIR.mkdir(parents=True, exist_ok=True)
        ssm_file = MIDI_DATA_DIR / f"{track_id}_similarity.png"
        ssm_file.write_bytes(png_data)
        ssm_png_path = str(ssm_file)
    except Exception as e:
        logger.warning(f"Failed to render self-similarity matrix: {e}")

    # Segmentation using Foote novelty + RMS supplementation
    rms = shared["rms"]
    peaks, peak_heights, novelty = _find_segment_boundaries(sim_matrix, threshold_factor=0.25, rms=rms)

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
        peaks, peak_heights, novelty = _find_segment_boundaries(sim_matrix, threshold_factor=0.0, rms=rms)
        if len(peaks) > 0:
            boundary_times = [0.0] + [round(float(p * frames_to_time_factor), 2) for p in peaks] + [round(duration, 2)]
            segments = []
            for i in range(len(boundary_times) - 1):
                segments.append({
                    "start": boundary_times[i],
                    "end": boundary_times[i + 1],
                    "duration": round(boundary_times[i + 1] - boundary_times[i], 2),
                })

    # Section labeling by multi-feature similarity (chroma + energy + MFCC)
    section_labels = []
    label_map: dict[int, str] = {}
    # Cache per-section features to avoid recomputing for every comparison
    section_features: list[dict] = []
    current_label_idx = 0
    label_chars = "ABCDEFGHIJKLMNOP"

    hop_length = shared["hop_length"]
    rms = shared["rms"]

    for i, seg in enumerate(segments):
        # Compute chroma, energy, and MFCC features for this segment
        start_frame = int(seg["start"] / duration * chroma.shape[1]) if duration > 0 else 0
        end_frame = int(seg["end"] / duration * chroma.shape[1]) if duration > 0 else chroma.shape[1]
        end_frame = max(start_frame + 1, min(end_frame, chroma.shape[1]))
        seg_chroma = np.mean(chroma[:, start_frame:end_frame], axis=1)
        seg_chroma_norm = seg_chroma / (np.linalg.norm(seg_chroma) + 1e-10)

        # Mean RMS energy in dB
        rms_start = int(seg["start"] * sr) // hop_length
        rms_end = int(seg["end"] * sr) // hop_length
        seg_rms = rms[rms_start:rms_end]
        rms_db = float(20 * np.log10(np.mean(seg_rms) + 1e-10)) if len(seg_rms) > 0 else -60.0

        # Mean MFCC vector
        seg_mfcc = np.mean(mfcc[:, start_frame:end_frame], axis=1)
        seg_mfcc_norm = seg_mfcc / (np.linalg.norm(seg_mfcc) + 1e-10)

        section_features.append({
            "chroma_norm": seg_chroma_norm,
            "rms_db": rms_db,
            "mfcc_norm": seg_mfcc_norm,
        })

        # Compare to previous labeled sections using all three features
        matched = False
        for prev_idx, prev_label in label_map.items():
            pf = section_features[prev_idx]

            chroma_sim = float(np.dot(seg_chroma_norm, pf["chroma_norm"]))
            energy_diff = abs(rms_db - pf["rms_db"])
            mfcc_sim = float(np.dot(seg_mfcc_norm, pf["mfcc_norm"]))

            if chroma_sim > 0.97 and energy_diff < 3.0 and mfcc_sim > 0.95:
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

    # Section-aware energy/timbral profiles
    rms = shared["rms"]
    hop_length = shared["hop_length"]
    section_profiles = []
    for seg in segments:
        start_sample = int(seg["start"] * sr)
        end_sample = int(seg["end"] * sr)
        start_frame = start_sample // hop_length
        end_frame = end_sample // hop_length

        # RMS energy for this section
        seg_rms = rms[start_frame:end_frame]
        if len(seg_rms) > 0:
            rms_db = round(float(20 * np.log10(np.mean(seg_rms) + 1e-10)), 1)
        else:
            rms_db = -60.0

        # Spectral centroid (brightness) for this section
        seg_y = y[start_sample:end_sample]
        if len(seg_y) > sr // 4:  # At least 0.25s
            centroid = librosa.feature.spectral_centroid(y=seg_y, sr=sr)[0]
            centroid_mean = float(np.mean(centroid))
            centroid_norm = centroid_mean / (sr / 2)
            if centroid_norm < 0.1:
                brightness = "dark"
            elif centroid_norm < 0.25:
                brightness = "neutral"
            else:
                brightness = "bright"
        else:
            centroid_mean = 0.0
            brightness = "?"

        # Density estimate from chroma variance
        seg_start_cf = int(seg["start"] / duration * chroma.shape[1]) if duration > 0 else 0
        seg_end_cf = int(seg["end"] / duration * chroma.shape[1]) if duration > 0 else chroma.shape[1]
        seg_end_cf = max(seg_start_cf + 1, min(seg_end_cf, chroma.shape[1]))
        chroma_var = float(np.mean(np.var(chroma[:, seg_start_cf:seg_end_cf], axis=1)))
        if chroma_var < 0.01:
            density = "sparse"
        elif chroma_var < 0.04:
            density = "moderate"
        else:
            density = "dense"

        section_profiles.append({
            "label": seg.get("label", "?"),
            "start": seg["start"],
            "end": seg["end"],
            "rms_db": rms_db,
            "brightness": brightness,
            "density": density,
        })

    # Compute boundary confidence: how sharp/clear the novelty peaks are
    boundary_confidence = None
    if len(peak_heights) > 0 and len(novelty) > 0:
        novelty_std = float(np.std(novelty))
        if novelty_std > 0:
            raw = float(np.mean(peak_heights)) / novelty_std
            # Normalize to 0-1 with sigmoid-like scaling (raw ~2-5 is typical)
            boundary_confidence = round(min(raw / 5.0, 1.0), 3)

    return {
        "segments": segments,
        "form": form,
        "section_count": len(segments),
        "avg_section_length": round(float(np.mean([s["duration"] for s in segments])), 2) if segments else 0,
        "self_similarity_png_path": ssm_png_path,
        "section_profiles": section_profiles,
        "boundary_confidence": boundary_confidence,
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


# ─── Melodic sketches (post-processing) ──────────────────────────────────

def _add_melodic_sketches(results: dict[str, Any], shared: dict) -> None:
    """Add compact melodic sketches per structural section to results.

    Requires both melodic (with note data) and structural (with segments) results.
    Modifies results["melodic"] in place to add "section_sketches".
    """
    melodic = results.get("melodic", {})
    structural = results.get("structural", {})

    if melodic.get("degraded") or melodic.get("error"):
        return
    if not structural.get("segments"):
        return

    # We need the raw notes — reconstruct from the MIDI file or use the note_events
    # Since _analyze_melodic doesn't store raw notes in results, we use MIDI file
    midi_path = melodic.get("midi_path")
    if not midi_path:
        return

    try:
        import pretty_midi
        from basic_pitch.inference import predict as _  # noqa: F401
        midi = pretty_midi.PrettyMIDI(midi_path)
    except (ImportError, Exception):
        return

    # Collect all notes
    all_notes = []
    for instrument in midi.instruments:
        for note in instrument.notes:
            all_notes.append({
                "start": note.start,
                "end": note.end,
                "pitch": note.pitch,
                "velocity": note.velocity,
            })
    all_notes.sort(key=lambda n: n["start"])

    if not all_notes:
        return

    bpm = shared.get("bpm", 120)
    beat_duration = 60.0 / bpm

    segments = structural["segments"]
    sketches = []
    seen_labels = set()

    for seg in segments:
        label = seg.get("label", "?")
        if label in seen_labels:
            continue  # Only sketch first occurrence of each section type
        seen_labels.add(label)

        seg_start = seg["start"]
        seg_end = seg["end"]

        # Get notes in this section
        seg_notes = [n for n in all_notes if n["start"] >= seg_start and n["start"] < seg_end]
        if len(seg_notes) < 4:
            continue

        # Take top-register notes (likely melody): filter to notes above median pitch
        pitches = [n["pitch"] for n in seg_notes]
        median_pitch = float(np.median(pitches))
        melody_notes = [n for n in seg_notes if n["pitch"] >= median_pitch]

        if len(melody_notes) < 4:
            melody_notes = seg_notes

        # Take first 12 notes
        sketch_notes = melody_notes[:12]

        # Format as pitch names with rhythm
        parts = []
        for note in sketch_notes:
            note_name = _midi_to_note(note["pitch"])
            dur = (note["end"] - note["start"]) / beat_duration
            symbol = _duration_symbol(dur)
            parts.append(f"{note_name}({symbol})")

        sketch_str = " ".join(parts)
        sketches.append({
            "label": label,
            "sketch": sketch_str,
            "note_count": len(sketch_notes),
        })

    if sketches:
        melodic["section_sketches"] = sketches
