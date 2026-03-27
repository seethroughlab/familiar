/**
 * Drone target + motif recipe builders for ambient transitions.
 *
 * computeDroneTarget() extracts root + fifth from a snippet's key.
 * buildMotifRecipe() picks motif notes and timing based on density.
 */

import type { AmbientSnippet, DroneTarget, MotifRecipe, TransitionDensity } from './types';
import { keyToMidiNote, getScaleNotes } from './compatibilityScoring';

/**
 * Compute the drone root + second note (perfect fifth) from a snippet's key.
 */
export function computeDroneTarget(snippet: AmbientSnippet): DroneTarget {
  const key = snippet.descriptor.key;
  const root = keyToMidiNote(key, 2); // Low octave for drone
  const secondNote = root + 7; // Perfect fifth
  return { rootNote: root, secondNote };
}

/**
 * Build a motif recipe for the intermission before the next snippet.
 * Picks notes from the target key's scale with timing based on density.
 */
export function buildMotifRecipe(
  nextSnippet: AmbientSnippet,
  density: TransitionDensity,
): MotifRecipe {
  const targetKey = nextSnippet.descriptor.key;
  const scaleNotes = getScaleNotes(targetKey, 4); // Higher octave for motif

  let motifNotes: number[];
  let motifTimingsMs: number[];
  let motifNoteDurationMs: number;

  switch (density) {
    case 'sparse':
      motifNotes = pickMotifNotes(scaleNotes, 2);
      motifTimingsMs = [0, 3000];
      motifNoteDurationMs = 4500;
      break;

    case 'lush':
      motifNotes = pickMotifNotes(scaleNotes, 5);
      motifTimingsMs = [0, 1200, 2400, 4000, 5600];
      motifNoteDurationMs = 2200;
      break;

    case 'moderate':
    default:
      motifNotes = pickMotifNotes(scaleNotes, 3);
      motifTimingsMs = [0, 1800, 4200];
      motifNoteDurationMs = 3000;
      break;
  }

  return { motifNotes, motifTimingsMs, motifNoteDurationMs };
}

/**
 * Pick n notes from a scale, preferring root, fifth, and third.
 */
function pickMotifNotes(scaleNotes: number[], count: number): number[] {
  if (scaleNotes.length <= count) return scaleNotes.slice(0, count);

  // Prefer root (index 0), fifth (index 4), third (index 2)
  const preferred = [0, 4, 2, 5, 6, 1, 3];
  const picked: number[] = [];

  for (const idx of preferred) {
    if (picked.length >= count) break;
    if (idx < scaleNotes.length) {
      picked.push(scaleNotes[idx]);
    }
  }

  return picked;
}
