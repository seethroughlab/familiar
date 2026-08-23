/**
 * What the visualizer pipeline is actually doing, for the debug panel.
 *
 * **Four rates, because "it looks choppy" has four different causes** and they are not
 * distinguishable by watching:
 *
 * - the **host's** animation loop, which is what reads the analysis buffer;
 * - **analysis frames from the native player**, which arrive at about 10 Hz because macOS clamps
 *   the tap to 100 ms buffers — if this is well under 10 the app is starving the page;
 * - **messages posted into the plugin**, which should track the host loop;
 * - the **plugin's own** frame rate, which is the only one that matches what a person sees, and
 *   the only one the host cannot measure for itself.
 *
 * That last one is why the plugin reports it. The document has an opaque origin, so nothing here
 * can reach into the frame and count — it has to volunteer the number, and the shim in every
 * shipped plugin does it in one line.
 *
 * Everything is counted into a one-second bucket rather than averaged over the session: a session
 * average hides a stall, which is exactly the thing being looked for.
 */

export interface VisualizerMetrics {
  /** This page's requestAnimationFrame rate. */
  hostFps: number;
  /** Analysis frames arriving from the native player per second. ~10 is healthy. */
  analysisFps: number;
  /** `familiar:audio` messages posted into the plugin per second. */
  postedFps: number;
  /** The plugin's own frame rate, if it reports one. Null when it does not. */
  pluginFps: number | null;
  /** Milliseconds since the last analysis frame. Climbs when the native side stops sending. */
  analysisAgeMs: number;
  /** The most recent values sent, so a dead-looking scene can be checked against live numbers. */
  last: { bass: number; beat: number; onset: boolean; averageFrequency: number } | null;
}

const EMPTY: VisualizerMetrics = {
  hostFps: 0, analysisFps: 0, postedFps: 0, pluginFps: null, analysisAgeMs: 0, last: null,
};

let current = EMPTY;
let hostFrames = 0;
let analysisFrames = 0;
let postedFrames = 0;
let pluginFps: number | null = null;
let lastAnalysisAt = 0;
let last: VisualizerMetrics['last'] = null;
let windowStartedAt = 0;

const listeners = new Set<(m: VisualizerMetrics) => void>();

/** Called once per host animation frame. */
export function recordHostFrame(): void {
  hostFrames++;
  roll();
}

/** Called when a frame arrives from the native player (`visualizerSink`). */
export function recordAnalysisFrame(): void {
  analysisFrames++;
  lastAnalysisAt = performance.now();
}

/** Called for each `familiar:audio` posted into the plugin. */
export function recordPostedFrame(values: NonNullable<VisualizerMetrics['last']>): void {
  postedFrames++;
  last = values;
}

/** Called when a plugin volunteers its frame rate. */
export function recordPluginFps(fps: number): void {
  pluginFps = fps;
}

function roll(): void {
  const now = performance.now();
  if (windowStartedAt === 0) { windowStartedAt = now; return; }
  const elapsed = now - windowStartedAt;
  if (elapsed < 1000) return;

  const perSecond = (n: number) => Math.round((n * 1000) / elapsed);
  current = {
    hostFps: perSecond(hostFrames),
    analysisFps: perSecond(analysisFrames),
    postedFps: perSecond(postedFrames),
    pluginFps,
    analysisAgeMs: lastAnalysisAt === 0 ? Infinity : Math.round(now - lastAnalysisAt),
    last,
  };
  hostFrames = 0;
  analysisFrames = 0;
  postedFrames = 0;
  windowStartedAt = now;
  listeners.forEach((l) => l(current));
}

export function subscribeToMetrics(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function getMetrics(): VisualizerMetrics {
  return current;
}

/**
 * Whether the debug panel is showing, read from the URL.
 *
 * The same route `visualizer` and `autoSelect` already take: the native host owns the switch and
 * says so on the URL, because a page that remembered its own answer would disagree with the menu
 * that toggles it. Read once — the host reloads the page when it changes, which is how the
 * visualizer choice already works.
 */
export function debugPanelEnabled(search: string = window.location.search): boolean {
  return new URLSearchParams(search).get('debug') === '1';
}
