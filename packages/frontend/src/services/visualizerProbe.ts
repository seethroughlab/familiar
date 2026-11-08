/**
 * The visualizer probe: a recording of what a document was sent and what it drew.
 *
 * **Why it exists.** Beat Tiles was tuned twice against renders in a headless browser driven by a
 * made-up beat, and the phone showed something else both times (1.7 builds 74–76). The harness ran
 * another engine, and its audio was the loudest the code allows, every frame. Neither is what a
 * listener sees. The probe records the real thing on the device:
 *
 * - every `familiar:audio` payload posted into the document, exactly as sent, so a harness can
 *   replay the same feed (`packages/visualizers/scripts/replay.mjs`);
 * - the document's `familiar:stats` (frame rate, plus what it reports with `setStat`);
 * - a frame of what it drew, every `CAPTURE_EVERY_MS`, via `familiar:capture` / `familiar:frame`;
 * - the track it was sent and the page's size.
 *
 * Off unless the native host puts `probe=1` on the URL, the same way it owns `debug=1`. The host
 * drains the buffer with `window.__familiarProbe.drain()` about once a second and writes it to a
 * file the developer copies off the device. Nothing leaves the device, and nothing is kept between
 * drains.
 */

export const CAPTURE_EVERY_MS = 5000;
/** A drain that never comes should not grow the page without bound: about two minutes at 60 Hz. */
const MAX_BUFFERED = 8000;

export type ProbeRecord = { t: number; kind: string } & Record<string, unknown>;

let buffer: ProbeRecord[] = [];
let dropped = 0;

export function probeEnabled(search: string = window.location.search): boolean {
  return new URLSearchParams(search).get('probe') === '1';
}

export function recordProbe(kind: string, fields: Record<string, unknown>): void {
  if (buffer.length >= MAX_BUFFERED) {
    dropped++;
    return;
  }
  buffer.push({ t: Math.round(performance.now()), kind, ...fields });
}

/** Everything recorded since the last drain, as JSON, and forget it. */
export function drainProbe(): string {
  const out = buffer;
  if (dropped > 0) out.push({ t: Math.round(performance.now()), kind: 'dropped', count: dropped });
  buffer = [];
  dropped = 0;
  return JSON.stringify(out);
}

/** Expose the drain to the native host. Idempotent. */
export function installProbe(): void {
  const w = window as unknown as { __familiarProbe?: { drain: () => string } };
  if (w.__familiarProbe) return;
  w.__familiarProbe = { drain: drainProbe };
  recordProbe('page', {
    width: window.innerWidth,
    height: window.innerHeight,
    devicePixelRatio: window.devicePixelRatio,
    userAgent: navigator.userAgent,
  });
}

/** For tests. */
export function _resetProbe(): void {
  buffer = [];
  dropped = 0;
  delete (window as unknown as { __familiarProbe?: unknown }).__familiarProbe;
}
