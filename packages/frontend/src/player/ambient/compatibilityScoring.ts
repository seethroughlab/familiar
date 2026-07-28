/**
 * Key parsing for ambient transition synthesis.
 *
 * Used only by transitionRecipes.ts: `keyToMidiNote` gives the drone root and
 * `getScaleNotes` gives motif degrees. This is musical synthesis, not ranking.
 *
 * It previously also held `scoreCandidate` and `keyCompatibility` — a port of the
 * backend's `score_candidate` — which had no call sites at all. Ranking belongs on the
 * server (ADR-0005), and offline ranking is served by a precomputed manifest (ADR-0006),
 * so nothing on the client should score candidates again.
 */

// ============================================================================
// Key parsing
// ============================================================================

const NOTE_NAMES: Record<string, number> = {
  'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
  'E': 4, 'Fb': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7,
  'G#': 8, 'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11, 'Cb': 11,
};

type ParsedKey = { pitchClass: number; mode: 'major' | 'minor' };

export function parseKey(keyStr: string | null): ParsedKey | null {
  if (!keyStr) return null;
  const s = keyStr.trim();

  // Try "Xm" or "X minor" patterns for minor
  for (const [name, pc] of Object.entries(NOTE_NAMES)) {
    if (s === name + 'm' || s.toLowerCase() === name.toLowerCase() + ' minor') {
      return { pitchClass: pc, mode: 'minor' };
    }
  }
  // Try bare note name or "X major" for major
  for (const [name, pc] of Object.entries(NOTE_NAMES)) {
    if (s === name || s.toLowerCase() === name.toLowerCase() + ' major') {
      return { pitchClass: pc, mode: 'major' };
    }
  }
  return null;
}

/**
 * Get the MIDI note number for a key's root (C4 = 60 basis).
 */
export function keyToMidiNote(keyStr: string | null, octave = 3): number {
  const parsed = parseKey(keyStr);
  if (!parsed) return 48; // C3 default
  return parsed.pitchClass + (octave + 1) * 12;
}

/**
 * Get scale degrees for a key (for motif generation).
 */
export function getScaleNotes(keyStr: string | null, octave = 3): number[] {
  const parsed = parseKey(keyStr);
  if (!parsed) return [48, 50, 52, 53, 55]; // C major pentatonic

  const root = parsed.pitchClass + (octave + 1) * 12;
  const intervals = parsed.mode === 'minor'
    ? [0, 2, 3, 5, 7, 8, 10] // natural minor
    : [0, 2, 4, 5, 7, 9, 11]; // major

  return intervals.map(i => root + i);
}
