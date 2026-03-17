/**
 * Transition recipe builder — computes drone/motif parameters
 * for synth transitions between ambient snippets.
 */

import type { AmbientSnippet, TransitionRecipe, TransitionDensity } from './types';
import { keyToMidiNote, getScaleNotes, parseKey } from './compatibilityScoring';

/**
 * Build a transition recipe from current snippet to next snippet.
 *
 * Computes drone root/second notes from target key, motif notes
 * from scale degrees, timing based on density setting.
 */
export function buildTransitionRecipe(
  _currentSnippet: AmbientSnippet,
  nextSnippet: AmbientSnippet,
  density: TransitionDensity,
): TransitionRecipe {
  const targetKey = nextSnippet.descriptor.key;

  // Drone notes: root + fifth (or root + minor third for minor keys)
  const root = keyToMidiNote(targetKey, 2); // Low octave for drone
  const parsed = parseKey(targetKey);
  const secondInterval = parsed?.mode === 'minor' ? 7 : 7; // Perfect fifth for both
  const droneSecond = root + secondInterval;

  // Motif notes: pick from target key scale
  const scaleNotes = getScaleNotes(targetKey, 4); // Higher octave for motif

  // Density determines note count and timing
  let motifNotes: number[];
  let motifTimingsMs: number[];
  let motifNoteDuration: number;
  let droneAttack: number;
  let droneRelease: number;

  switch (density) {
    case 'sparse':
      motifNotes = pickMotifNotes(scaleNotes, 2);
      motifTimingsMs = [0, 3000];
      motifNoteDuration = 4500;
      droneAttack = 6000;
      droneRelease = 8000;
      break;

    case 'lush':
      motifNotes = pickMotifNotes(scaleNotes, 5);
      motifTimingsMs = [0, 1200, 2400, 4000, 5600];
      motifNoteDuration = 2200;
      droneAttack = 4000;
      droneRelease = 5000;
      break;

    case 'moderate':
    default:
      motifNotes = pickMotifNotes(scaleNotes, 3);
      motifTimingsMs = [0, 1800, 4200];
      motifNoteDuration = 3000;
      droneAttack = 5000;
      droneRelease = 7000;
      break;
  }

  return {
    droneRootNote: root,
    droneSecondNote: droneSecond,
    droneAttackMs: droneAttack,
    droneReleaseMs: droneRelease,
    motifNotes,
    motifTimingsMs,
    motifNoteDurationMs: motifNoteDuration,
  };
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
