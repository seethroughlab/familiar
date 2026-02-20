"""Constants for track analysis.

Note/chord tables, mode profiles, rhythm lookups, interval names,
Roman numeral mappings, and common chord progressions.
"""

from pathlib import Path

import numpy as np

# Minimum track duration for analysis (seconds)
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

# Roman numeral labels for major and minor keys
_ROMAN_MAJOR = ["I", "bII", "II", "bIII", "III", "IV", "#IV", "V", "bVI", "VI", "bVII", "VII"]
_ROMAN_MINOR = ["i", "bII", "ii", "bIII", "III", "iv", "#IV", "v", "bVI", "VI", "bVII", "VII"]

# Quality suffixes for Roman numerals
_QUALITY_TO_ROMAN_SUFFIX = {
    "maj": "", "min": "", "dim": "dim", "aug": "aug",
    "7": "7", "maj7": "maj7", "min7": "7",
}

# Common chord progressions to detect (as Roman numeral degree tuples)
# Each entry: (name, list of degree patterns as semitone intervals from root)
COMMON_PROGRESSIONS = {
    "I-V-vi-IV": (0, 7, 9, 5),
    "I-IV-V-IV": (0, 5, 7, 5),
    "I-IV-V": (0, 5, 7),
    "ii-V-I": (2, 7, 0),
    "I-vi-IV-V": (0, 9, 5, 7),
    "vi-IV-I-V": (9, 5, 0, 7),
    "I-bVII-IV": (0, 10, 5),
    "i-bVII-bVI-V": (0, 10, 8, 7),
    "i-iv-v": (0, 5, 7),
    "i-bVI-bIII-bVII": (0, 8, 3, 10),
    "12-bar blues": (0, 0, 0, 0, 5, 5, 0, 0, 7, 5, 0, 7),
}
