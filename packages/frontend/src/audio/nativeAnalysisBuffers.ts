/**
 * Native analysis buffer management.
 *
 * The seam between a native host that has the audio and a page that only draws it. Written by the
 * embedded visualizer surface, read by `useAudioAnalyser`. Kept out of the hooks layer so a writer
 * does not have to import from it.
 */

let nativeFrequencyData: Uint8Array | null = null;
let nativeTimeDomainData: Uint8Array | null = null;
let nativeFlux: Float32Array | null = null;
let nativeFluxInterval = 0;
let nativeSequence = 0;

/**
 * Onset strength per analysis window, oldest first — the envelope the native side computed.
 *
 * **This exists because the page cannot compute it.** `computeOnset` derives flux by differencing
 * *consecutive spectra*, which works when a fresh spectrum arrives every animation frame. Frames
 * from a native host arrive at 10 Hz against a 60 Hz render loop — macOS clamps `installTap` to a
 * 100 ms buffer, measured — so five of every six passes would difference a spectrum against itself,
 * read zero flux, drag the running baseline to zero, and then fire on every buffer arrival. A
 * detector reporting the transport rather than the music.
 *
 * The native side already computes flux per 1024-sample window while folding the buffer, so it
 * sends the envelope instead: ~43 Hz of onset resolution inside a 10 Hz channel, and every tuned
 * constant stays here where it always was.
 */
export function setNativeAnalysisBuffers(
  freq: Uint8Array,
  time: Uint8Array,
  flux?: Float32Array | null,
  /** Seconds between consecutive `flux` values — the analysis hop, not the frame rate. */
  fluxInterval = 0
): void {
  nativeFrequencyData = freq;
  nativeTimeDomainData = time;
  nativeFlux = flux ?? null;
  nativeFluxInterval = fluxInterval;
  nativeSequence += 1;
}

export function clearNativeAnalysisBuffers(): void {
  nativeFrequencyData = null;
  nativeTimeDomainData = null;
  nativeFlux = null;
  nativeFluxInterval = 0;
  nativeSequence = 0;
}

export function getNativeAnalysisBuffers(): {
  frequency: Uint8Array | null;
  timeDomain: Uint8Array | null;
  /** Null when the host sends no envelope — the detector then falls back to differencing. */
  flux: Float32Array | null;
  /** Seconds between `flux` values. Zero when there is no envelope. */
  fluxInterval: number;
  /**
   * Increments on every write, so a reader can tell a fresh frame from a stale one.
   *
   * **The onset envelope must be consumed exactly once**, and nothing else here guarantees that.
   * These buffers persist between writes, and the render loop runs at 60 fps against a channel
   * delivering 10 frames a second — so without a sequence the same envelope is replayed about six
   * times, the refractory masks the repeated onsets, and the decay runs six times too fast. The
   * symptom is a beat envelope that spikes and vanishes within one frame.
   */
  sequence: number;
} {
  return {
    frequency: nativeFrequencyData,
    timeDomain: nativeTimeDomainData,
    flux: nativeFlux,
    fluxInterval: nativeFluxInterval,
    sequence: nativeSequence,
  };
}
