"""Utility helpers for track analysis.

JSON sanitization, MIDI-to-note conversion, time formatting, rhythm symbols.
"""

from typing import Any

import numpy as np

from app.services.track_analysis.constants import NOTE_NAMES


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


# Rhythm notation for melodic sketches
_RHYTHM_SYMBOLS = {
    (0, 0.25): "\u266c",     # sixteenth
    (0.25, 0.5): "\u266a",   # eighth
    (0.5, 1.0): "\u2669",    # quarter
    (1.0, 2.0): "\U0001d15e",   # half
    (2.0, 99): "\U0001d15d",     # whole
}


def _duration_symbol(dur_beats: float) -> str:
    """Convert duration in beats to a rhythm symbol."""
    for (lo, hi), symbol in _RHYTHM_SYMBOLS.items():
        if lo <= dur_beats < hi:
            return symbol
    return "\u2669"
