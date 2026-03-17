/**
 * Snippet window picking — pure functions.
 *
 * Selects the time window within a track to play as an ambient snippet.
 */

import type { SnippetLength } from './types';

interface SnippetWindow {
  startTime: number;
  endTime: number;
}

/**
 * Select a snippet window within a track.
 *
 * Uses server-suggested start/end percentages as primary input,
 * clamps to snippet length, and applies guard bands.
 */
export function selectSnippetWindow(
  durationSeconds: number,
  snippetLength: SnippetLength,
  suggestedStartPct?: number,
  _suggestedEndPct?: number,
  _energyShape?: string | null,
): SnippetWindow {
  if (durationSeconds <= 0) {
    return { startTime: 0, endTime: snippetLength };
  }

  // If track is shorter than snippet, play the whole thing (with small guard bands)
  if (durationSeconds <= snippetLength + 15) {
    const start = Math.min(5, durationSeconds * 0.1);
    const end = Math.max(start + snippetLength, durationSeconds - 5);
    return { startTime: start, endTime: Math.min(end, durationSeconds) };
  }

  // Guard bands (absolute seconds)
  const startGuard = 10;
  const endGuard = 15;
  const maxEnd = durationSeconds - endGuard;
  const minStart = startGuard;

  // Use server suggestion as start point
  const startPct = suggestedStartPct ?? 0.25;

  // Calculate start from percentage
  let startTime = durationSeconds * startPct;
  let endTime = startTime + snippetLength;

  // Clamp to guard bands
  if (startTime < minStart) {
    startTime = minStart;
    endTime = startTime + snippetLength;
  }
  if (endTime > maxEnd) {
    endTime = maxEnd;
    startTime = Math.max(minStart, endTime - snippetLength);
  }

  // If still too tight, relax guard bands
  if (endTime - startTime < snippetLength * 0.8) {
    startTime = Math.max(0, durationSeconds * 0.3);
    endTime = Math.min(durationSeconds, startTime + snippetLength);
  }

  return {
    startTime: Math.round(startTime * 100) / 100,
    endTime: Math.round(endTime * 100) / 100,
  };
}
