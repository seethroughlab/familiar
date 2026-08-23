import type { AudioEngine, AudioEngineCapabilities, EngineEvent } from '@familiar/frontend/src/audio/types';

/**
 * An `AudioEngine` that does nothing, for the embedded surface (ADR-0017).
 *
 * **This exists to be absent.** It will look like dead code to anyone who finds it without the ADR,
 * so: the embedded Discover surface runs inside a `WKWebView` in the Mac app, and the one thing it
 * must never do is become a second audio engine — two engines in one process means two queues and
 * two things holding an audio session, which is the defect
 * [ADR-0001](../../../docs/decisions/ADR-0001-native-apple-clients-supersede-capacitor.md) and
 * `CarPlayBridge` are both written to avoid.
 *
 * ADR-0016 point 4 assumed that forbidding playback was enough to prevent construction. It was not,
 * for two separate reasons. One is fixed: capability queries used to construct an engine, and no
 * longer do. The other is intrinsic — **Discover plays music.** `DiscoverTrackList` wires
 * `setQueueByTrackId` to a row's play button and `DiscoverBrowser` calls `onPlayTrack`, both of which
 * reach `getEngine()`. ADR-0016 point 5 hands those intents to the native player over a bridge, and
 * this is the floor under that bridge: a *missed* intent is inert rather than a second engine.
 *
 * Every method is deliberately silent rather than throwing. A `throw` here would surface as a crash
 * inside a web view inside a native app, which ADR-0016 itself calls the hardest place in the product
 * to diagnose anything — and the wanted behaviour for an unbridged play is nothing happening, not a
 * stack trace.
 *
 * Only the 15 required members of `AudioEngine` are implemented. All 15 optional ones are omitted, so
 * `preloadNext?.()`, `getAnalyser?.()` and the rest are `undefined` and their callers already fall
 * back — which is how the visualizer and the effects chain stay away from a surface that has neither.
 */
export class NullAudioEngine implements AudioEngine {
  /**
   * Declared here *and* registered beside the factory in the entry point, because the two are read
   * at different times: the registration answers before anything is built, and this answers if
   * anything ever is. They must agree, and `assertCapabilitiesMatch` says so out loud if they drift.
   *
   * **Injectable because the visualizer surface needs `visualizer: true` and the same silence.**
   * That combination looks contradictory and is the whole point: `isVisualizerAvailable()` reads
   * this flag to decide whether to draw a visualizer at all, so a surface declaring `false` would
   * render album art forever. What keeps ADR-0017's guarantee is not the flag but the omission —
   * `getAnalyser` and every other optional member are still missing, and `getAudioAnalyser()` calls
   * `existingEngine()?.getAnalyser?.()`, which cannot construct anything. So the visualizer surface
   * says it can show a visualizer and still cannot make or analyse a sound.
   */
  readonly capabilities: AudioEngineCapabilities;

  constructor(
    capabilities: AudioEngineCapabilities = { crossfade: false, visualizer: false, effects: 'none' }
  ) {
    this.capabilities = capabilities;
  }

  // Lifecycle
  initialize(): boolean {
    // `true` — "there is an engine and it is ready" is accurate. It is ready to do nothing.
    return true;
  }

  dispose(): void {}

  // Playback. Silent, per the note above.
  async load(): Promise<void> {}
  async play(): Promise<void> {}
  pause(): void {}
  seek(): void {}
  stop(): void {}

  // Volume & normalization
  setVolume(): void {}
  setNormalizationGain(): void {}

  // State. Zeroes and nulls, which is what "nothing is loaded" looks like everywhere else.
  getCurrentTime(): number {
    return 0;
  }

  getDuration(): number {
    return 0;
  }

  getLoadedTrackId(): string | null {
    return null;
  }

  /**
   * Never emits.
   *
   * The unsubscribe function is still real, so callers that hold it and call it on unmount behave
   * exactly as they do with a live engine. Returning a no-op that was not callable would turn this
   * into a different kind of bug than the one it prevents.
   */
  on(_handler: (event: EngineEvent) => void): () => void {
    return () => {};
  }

  // Media session / Now Playing. The native app owns the now-playing entry (ADR-0016 point 5), and
  // an embedded page writing to `MediaSession` would put a second one on the lock screen.
  updateNowPlaying(): void {}
}
