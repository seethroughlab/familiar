/**
 * Key compatibility table + feature scoring utilities.
 *
 * Shared between offlineScoring.ts and transitionRecipes.ts.
 * Pure functions, no side effects.
 */

import type { AmbientDescriptor, AmbientIntensity } from './types';

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

// ============================================================================
// Key compatibility
// ============================================================================

export function keyCompatibility(keyA: string | null, keyB: string | null): number {
  const a = parseKey(keyA);
  const b = parseKey(keyB);
  if (!a || !b) return 0.5;

  // Same key
  if (a.pitchClass === b.pitchClass && a.mode === b.mode) return 1.0;

  // Relative major/minor
  if (a.mode === 'minor' && b.mode === 'major' && (a.pitchClass + 3) % 12 === b.pitchClass) return 0.9;
  if (a.mode === 'major' && b.mode === 'minor' && (b.pitchClass + 3) % 12 === a.pitchClass) return 0.9;

  // Perfect fifth (same mode)
  const interval = (b.pitchClass - a.pitchClass + 12) % 12;
  if (a.mode === b.mode && (interval === 5 || interval === 7)) return 0.8;

  // Parallel major/minor
  if (a.pitchClass === b.pitchClass && a.mode !== b.mode) return 0.7;

  // Second neighbor
  if (a.mode === b.mode && (interval === 2 || interval === 10)) return 0.5;

  return 0.2;
}

// ============================================================================
// Feature scoring
// ============================================================================

function safeNum(val: number | null | undefined, fallback = 0): number {
  return val != null && isFinite(val) ? val : fallback;
}

export function scoreCandidate(
  current: AmbientDescriptor,
  candidate: AmbientDescriptor,
  intensity: AmbientIntensity = 'balanced',
  embeddingSimilarity?: number,
  recentArtistNames?: string[],
): number {
  const keyScore = keyCompatibility(current.key, candidate.key);
  const energyScore = 1 - Math.abs(safeNum(current.energy) - safeNum(candidate.energy));
  const embeddingScore = embeddingSimilarity ?? 0.5;
  const vocalScore = safeNum(candidate.instrumentalness) * 0.7 + (1 - safeNum(candidate.speechiness)) * 0.3;
  const brightnessScore = 1 - Math.abs(safeNum(current.brightness) - safeNum(candidate.brightness));
  const valenceScore = 1 - Math.abs(safeNum(current.valence) - safeNum(candidate.valence));
  const drDiff = Math.abs(safeNum(current.dynamic_range_db) - safeNum(candidate.dynamic_range_db));
  const drScore = 1 - Math.min(drDiff / 20, 1);

  const w = {
    key: 0.30, energy: 0.20, embedding: 0.15,
    vocal: 0.10, brightness: 0.10, valence: 0.10, dr: 0.05,
  };

  if (intensity === 'quiet') { w.energy = 0.30; w.key = 0.20; }
  else if (intensity === 'immersive') { w.embedding = 0.25; w.key = 0.20; }

  let total =
    w.key * keyScore +
    w.energy * energyScore +
    w.embedding * embeddingScore +
    w.vocal * vocalScore +
    w.brightness * brightnessScore +
    w.valence * valenceScore +
    w.dr * drScore;

  // BPM penalty
  const curBpm = safeNum(current.bpm);
  const candBpm = safeNum(candidate.bpm);
  if (curBpm > 0 && candBpm > 0 && Math.abs(curBpm - candBpm) > 40) {
    total -= 0.15;
  }

  // Quiet bonus
  if (intensity === 'quiet' && safeNum(candidate.energy) < 0.35) {
    total += 0.10;
  }

  // Artist cooldown
  if (recentArtistNames && candidate.artist) {
    const lower = candidate.artist.toLowerCase();
    if (recentArtistNames.some(a => a.toLowerCase() === lower)) {
      total -= 0.25;
    }
  }

  return Math.max(0, Math.min(1, total));
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
