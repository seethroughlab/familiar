/**
 * What the native app is playing, pushed into the Discover surface (ADR-0090).
 *
 * **The second consumer of the app → page direction `ADR-0033` opened**, and deliberately the same
 * shape as `visualizerSink`: a global the native side calls, state held outside React, and
 * subscribers notified only when something changes that a render would care about.
 *
 * The frame is two fields. `ADR-0090` point 1 is explicit that this is not the visualizer's frame
 * with the analysis removed — Discover draws no spectrum and needs no playhead, so sending either
 * would be a capability with no caller. A row list needs an id and a boolean.
 *
 * **Advisory, per point 5.** A surface that is never called shows no indicator and behaves exactly
 * as it did before this existed. That is what makes the channel safe to depend on from a page that
 * may be running inside an older app: `getNowPlaying()` answers "nothing is playing" and every
 * caller renders correctly.
 */

/** The frame the native side sends. */
export interface NowPlayingFrame {
  /** The track the native player is on, or null when it is on nothing. */
  trackId: string | null;
  playing: boolean;
}

export interface NowPlaying {
  trackId: string | null;
  playing: boolean;
}

/**
 * The function name the native side calls.
 *
 * Kept in step with `NowPlayingFrame.sinkName` in Swift; the two are a contract and nothing checks
 * it at compile time, because one half is TypeScript. The same caveat `EmbedIntent.handlerName`
 * carries, for the same reason.
 */
const SINK_NAME = '__familiarNowPlaying';

let state: NowPlaying = { trackId: null, playing: false };
const listeners = new Set<() => void>();

function receive(frame: NowPlayingFrame): void {
  const trackId = typeof frame?.trackId === 'string' ? frame.trackId : null;
  const playing = frame?.playing === true;

  // Only publish real changes. The native side sends on its own schedule and may repeat itself;
  // notifying regardless would re-render the Discover tree at the channel's rate for no reason.
  if (state.trackId === trackId && state.playing === playing) return;

  state = { trackId, playing };
  listeners.forEach((listener) => listener());
}

/**
 * Install the sink. Called at module load from the embed entry point, **before React renders**, so
 * a frame that arrives during startup is not dropped.
 */
export function installNowPlayingSink(): void {
  (window as unknown as Record<string, unknown>)[SINK_NAME] = receive;
}

/** Whether a native host is actually driving this. Nothing depends on it; it is for diagnostics. */
export function isNowPlayingSinkInstalled(): boolean {
  return typeof (window as unknown as Record<string, unknown>)[SINK_NAME] === 'function';
}

export function subscribeToNowPlaying(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function getNowPlaying(): NowPlaying {
  return state;
}

/** Test seam: drop the state and the subscribers between cases. */
export function resetNowPlayingForTests(): void {
  state = { trackId: null, playing: false };
  listeners.clear();
}
