/**
 * Recorded host events (ADR-0125 point 4): the shapes the contract spec in `familiar-apple`
 * (`e2e/visualizer-document-contract.spec.ts`) posts into a document, and the shapes
 * `docs/VISUALIZER_API.md` promises for as long as `apiVersion` is 1. Every first-party visualizer
 * is exercised against these, so a change to what the host sends is a change here first.
 */

export const track = {
  type: 'familiar:track',
  apiVersion: 1,
  payload: { id: 'abc', title: 'A Song', artist: 'An Artist', duration: 100 },
} as const;

export const trackCleared = { type: 'familiar:track', apiVersion: 1, payload: null } as const;

export const state = {
  type: 'familiar:state',
  apiVersion: 1,
  payload: { isPlaying: true, currentTime: 3 },
} as const;

export const audio = {
  type: 'familiar:audio',
  apiVersion: 1,
  payload: {
    bass: 0.8,
    mid: 0.5,
    treble: 0.3,
    averageFrequency: 120,
    frequencyData: Array.from({ length: 64 }, (_, i) => 40 + ((i * 3) % 200)),
  },
} as const;

/** A newer host: beat and onset were added after the first plugins shipped. */
export const audioWithBeat = {
  ...audio,
  payload: { ...audio.payload, beat: 0.9, onset: true },
} as const;

/** An older host, from before `apiVersion` was on every message. */
export const audioWithoutVersion = { type: 'familiar:audio', payload: audio.payload } as const;

/** Things a bridge must survive. */
export const malformed = {
  notAnObject: 'familiar:audio',
  noType: { apiVersion: 1, payload: {} },
  audioWithoutPayload: { type: 'familiar:audio', apiVersion: 1 },
  audioWithGarbage: { type: 'familiar:audio', apiVersion: 1, payload: { bass: 'loud', frequencyData: 'nope' } },
  stateWithoutPayload: { type: 'familiar:state', apiVersion: 1 },
  trackWithScalarPayload: { type: 'familiar:track', apiVersion: 1, payload: 42 },
  unknownType: { type: 'familiar:teleport', apiVersion: 1, payload: {} },
  futureVersion: { type: 'familiar:audio', apiVersion: 2, payload: { bass: 1 } },
  someoneElses: { type: 'webpack:hmr', payload: {} },
} as const;
