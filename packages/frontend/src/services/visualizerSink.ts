import { setNativeAnalysisBuffers } from '../audio/nativeAnalysisBuffers';
import { recordAnalysisFrame } from '../components/Visualizer/visualizerMetrics';

/**
 * Receives analysis frames from the native host (ADR-0033).
 *
 * **Installed at module load, not from a component.** The host probes for this function as soon as
 * the document finishes loading, and `didFinish` fires when the HTML and scripts are in — well
 * before React has mounted anything or run an effect. Installing it in a `useEffect` therefore lost
 * the race every time: the page was correct, the sink simply did not exist yet, and the host
 * reported the page as not listening. Frames arriving during boot were dropped for the same reason.
 *
 * So the sink is a module-level singleton that exists the moment this module is imported, writes
 * straight into the analysis buffers, and keeps the small amount of *metadata* React needs in a
 * store components subscribe to.
 */

/** One frame, as `VisualizerFrame` in `FamiliarKit` sends it. Nothing checks the two against each
 * other — different languages, different repositories — so both sides are pinned to this shape by
 * tests, and a change here is a change there. */
export interface AnalysisFrame {
  frequency: string;
  timeDomain: string;
  flux: number[];
  fluxInterval: number;
  cadenceHz: number;
  playing: boolean;
  position: number;
  track?: { id: string; title?: string; artist?: string; album?: string };
}

export interface VisualizerState {
  playing: boolean;
  position: number;
  track: { id: string; title?: string; artist?: string; album?: string } | null;
}

const SINK_NAME = '__familiarAnalysis';

let state: VisualizerState = { playing: false, position: 0, track: null };
const listeners = new Set<() => void>();

// Reused across frames: this runs for as long as music plays, and allocating two typed arrays ten
// times a second would be litter for nothing. Visualizers copy out of them on their own tick.
let frequency: Uint8Array | null = null;
let timeDomain: Uint8Array | null = null;
let flux: Float32Array | null = null;

function decodeBytes(base64: string, into: Uint8Array | null): Uint8Array {
  const binary = atob(base64);
  const target = into && into.length === binary.length ? into : new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) target[i] = binary.charCodeAt(i);
  return target;
}

function receive(frame: AnalysisFrame): void {
  frequency = decodeBytes(frame.frequency, frequency);
  timeDomain = decodeBytes(frame.timeDomain, timeDomain);

  if (!flux || flux.length !== frame.flux.length) flux = new Float32Array(frame.flux.length);
  flux.set(frame.flux);

  setNativeAnalysisBuffers(frequency, timeDomain, flux, frame.fluxInterval);
  recordAnalysisFrame();

  // **Only notify on a change React would care about.** This runs ten times a second for the length
  // of a track; publishing every frame would re-render the visualizer tree at the channel's rate,
  // which is the mistake ADR-0041 had to undo one layer down on the native side. Position is
  // deliberately coarse — a visualizer that needs it precisely should read it per animation frame,
  // not per React render.
  const trackChanged = (frame.track?.id ?? null) !== (state.track?.id ?? null);
  const playingChanged = frame.playing !== state.playing;
  const positionJumped = Math.abs(frame.position - state.position) >= 0.2;

  if (trackChanged || playingChanged || positionJumped) {
    state = {
      playing: frame.playing,
      position: frame.position,
      track: frame.track ?? null,
    };
    for (const listener of listeners) listener();
  }
}

/**
 * Put the sink on `window`. Idempotent, and safe to call before anything is rendered.
 *
 * Returns nothing: the host's only question is whether the function exists, which it asks with
 * `typeof window.__familiarAnalysis === 'function'`.
 */
export function installVisualizerSink(): void {
  (window as unknown as Record<string, unknown>)[SINK_NAME] = receive;
}

export function subscribeToVisualizerState(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function getVisualizerState(): VisualizerState {
  return state;
}

/** Test seam — the sink and its buffers are module-level and outlive a test otherwise. */
export function resetVisualizerSinkForTesting(): void {
  state = { playing: false, position: 0, track: null };
  listeners.clear();
  frequency = null;
  timeDomain = null;
  flux = null;
  delete (window as unknown as Record<string, unknown>)[SINK_NAME];
}
