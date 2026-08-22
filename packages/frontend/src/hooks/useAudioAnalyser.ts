import { useEffect } from 'react';
import { getAudioAnalyser, getAudioContext } from '../audio/engineInstance';
import { isMobile } from '../utils/platform';
import {
  computeFrequencyBands,
} from '../audio/analysisMetrics';
import { recordConsumedAnalysisFrame } from '../audio/analysisDiagnostics';

const mobile = isMobile();

export interface AudioAnalysisData {
  frequencyData: Uint8Array;
  timeDomainData: Uint8Array;
  averageFrequency: number;
  bass: number;
  mid: number;
  treble: number;
  /** Decaying beat envelope (0-1): spikes to 1 on a detected onset, then decays. */
  beat: number;
  /** True only on the single frame an onset (transient) is detected. */
  onset: boolean;
}

// ---------------------------------------------------------------------------
// Singleton analysis loop — one rAF loop shared by all hook instances.
// Components read the latest data via getAudioData() (typically inside
// R3F useFrame). No React state updates are triggered by the loop.
// ---------------------------------------------------------------------------

const sharedAudioDataRef: { current: AudioAnalysisData | null } = { current: null };

let subscriberCount = 0;
let loopRunning = false;
let animationFrameId: number | undefined;
let lastAnalyseTime = 0;

// Persistent output object (mutated in place, buffers reused every frame)
let sharedData: AudioAnalysisData | null = null;
let lastBinCount = 0;

// ---------------------------------------------------------------------------
// Native analysis data (set from CapacitorEngine via bridge events)
// Re-exported from the shared module for backwards compatibility.
// ---------------------------------------------------------------------------

import {
  setNativeAnalysisBuffers,
  clearNativeAnalysisBuffers,
  getNativeAnalysisBuffers,
} from '../audio/nativeAnalysisBuffers';

export { setNativeAnalysisBuffers, clearNativeAnalysisBuffers };

// ---------------------------------------------------------------------------

function computeBands(freqData: Uint8Array): void {
  const bands = computeFrequencyBands(freqData);
  sharedData!.averageFrequency = bands.averageFrequency;
  sharedData!.bass = bands.bass;
  sharedData!.mid = bands.mid;
  sharedData!.treble = bands.treble;
}

// ---------------------------------------------------------------------------
// Real-time onset / beat detection (spectral flux + adaptive threshold).
//
// Locks visuals to the actual audio without any backend/stored beat grid:
// an onset fires when the positive spectral flux (over the lower ~60% of the
// spectrum, where transients dominate) jumps above a running average. `beat`
// is a time-decaying envelope spiking to 1 on each onset for smooth pulsing.
// ---------------------------------------------------------------------------

const FLUX_EMA_ALPHA = 0.1; // how fast the running flux baseline adapts
const ONSET_SENSITIVITY = 1.4; // flux must exceed baseline * this to fire
const ONSET_MIN_FLUX = 0.010; // absolute floor (normalized) to ignore noise
const ONSET_REFRACTORY_MS = 110; // min gap between onsets (~max 9/s)
const BEAT_DECAY_MS = 230; // how long the beat envelope takes to fall to 0
const FLUX_BAND = 0.85; // fraction of the spectrum used for flux (incl. snares/hats)

let prevFreq: Uint8Array | null = null;
let fluxEMA = 0;
let beatEnv = 0;
let lastOnsetTime = 0;
/** The last native frame consumed, so an envelope is never applied twice. */
let lastNativeSequence = 0;
let lastBeatUpdate = 0;

// Silence watchdog: warn once if we're "playing" but the analyser reads silence
// for a sustained period (suspended AudioContext, broken routing, CORS taint…).

/**
 * The tuned half of onset detection: adaptive threshold, refractory, decaying envelope.
 *
 * Split out so a *supplied* flux envelope goes through exactly the same constants as a locally
 * differenced one. This matters more than it looks: ADR-0033 point 5 keeps onset derivation on the
 * page so there is one tuned implementation, and the moment a native host started sending flux
 * there were two candidate places to threshold it. This is the one.
 */
function applyFlux(flux: number, now: number): void {
  fluxEMA += FLUX_EMA_ALPHA * (flux - fluxEMA);

  let onset = false;
  if (
    flux > ONSET_MIN_FLUX &&
    flux > fluxEMA * ONSET_SENSITIVITY &&
    now - lastOnsetTime > ONSET_REFRACTORY_MS
  ) {
    onset = true;
    lastOnsetTime = now;
    beatEnv = 1;
  }

  const dt = now - lastBeatUpdate;
  lastBeatUpdate = now;
  if (!onset && dt > 0) {
    beatEnv = Math.max(0, beatEnv - dt / BEAT_DECAY_MS);
  }

  sharedData!.beat = beatEnv;
  sharedData!.onset = onset;
}

/**
 * Run a supplied envelope through the detector, oldest value first.
 *
 * Each value is a separate observation ~23 ms apart, so they are fed in sequence rather than
 * averaged — averaging would flatten exactly the transient the detector is looking for. The
 * refractory period then does its usual job of stopping one drum hit firing twice.
 *
 * `onset` is left true if *any* value in the envelope fired, because a caller reads it once per
 * animation frame and would otherwise miss onsets that landed in the same frame.
 */
/** Fall the beat envelope by elapsed time, without treating it as a new observation. */
function decayBeat(now: number): void {
  const dt = now - lastBeatUpdate;
  lastBeatUpdate = now;
  if (dt > 0) beatEnv = Math.max(0, beatEnv - dt / BEAT_DECAY_MS);
  sharedData!.beat = beatEnv;
  sharedData!.onset = false;
}

function applyFluxEnvelope(flux: Float32Array, now: number, intervalSeconds: number): void {
  if (flux.length === 0) return;
  // **Milliseconds.** `now` is `performance.now()` and every constant in this file is in ms, where
  // the interval arrives in seconds because that is the unit an audio hop is naturally expressed
  // in. Mixing them made the four values of an envelope 0.023 ms apart instead of 23 ms — close
  // enough to simultaneous that the 110 ms refractory would swallow all but the first.
  const intervalMs = intervalSeconds * 1000;
  let fired = false;
  for (let i = 0; i < flux.length; i++) {
    // Back-dated so the refractory window measures real time between observations rather than
    // treating a whole envelope as simultaneous, which would let it swallow every value but one.
    const at = now - (flux.length - 1 - i) * intervalMs;
    applyFlux(flux[i], at);
    if (sharedData!.onset) fired = true;
  }
  if (fired) sharedData!.onset = true;
}

/**
 * Clear the detector's module-level state.
 *
 * **The state is genuinely module-level and genuinely never reset** — not on a track change, not on
 * a seek, not between tests. That is mostly harmless in the app, where the adaptive baseline
 * re-converges in under a second, but it makes tests order-dependent in a way that is very hard to
 * see: `lastOnsetTime` survives, and `performance.now()` is not faked by vitest's defaults, so a
 * second test running microseconds later sits inside the first one's 110 ms refractory window and
 * simply cannot fire. Two new tests failed this way and the first one to look at was the *existing*
 * code path, which had not changed.
 *
 * Named `ForTesting` in the idiom `resetPlaybackInterceptorForTesting` already establishes here.
 */
export function resetOnsetDetectorForTesting(): void {
  // **Stop the loop first, and this is the part that actually matters.** The rAF loop is a
  // module-level singleton guarded by `loopRunning`, and `stopLoop` only runs when the last
  // subscriber unmounts. A test that renders the hook and never unmounts therefore leaves
  // `loopRunning` true with a cancelled frame — so every later `startLoop` returns early and the
  // loop never ticks again. Two tests failed this way and looked for all the world like a broken
  // detector: the analyser was simply not running.
  stopLoop();
  prevFreq = null;
  fluxEMA = 0;
  beatEnv = 0;
  // `-Infinity`, not 0. The refractory test is `now - lastOnsetTime > 110`, so zero means "an onset
  // fired at time zero" and blocks everything for the first 110 ms of the clock. Harmless in the
  // app, where the clock starts high; fatal under a faked clock, where it never advances past it —
  // which is what made two new tests fail on a code path that had not changed.
  lastOnsetTime = Number.NEGATIVE_INFINITY;
  lastBeatUpdate = 0;
  lastNativeSequence = 0;
  // The mobile throttle's clock. Left stale, a faked clock that restarts lower than it leaves the
  // loop returning early on every frame — which looks exactly like the analyser not running.
  lastAnalyseTime = 0;
  sharedData = null;
  lastBinCount = 0;
}

function computeOnset(freq: Uint8Array, now: number): void {
  if (!prevFreq || prevFreq.length !== freq.length) {
    prevFreq = new Uint8Array(freq.length);
    prevFreq.set(freq);
    sharedData!.beat = 0;
    sharedData!.onset = false;
    lastBeatUpdate = now;
    return;
  }

  const n = Math.max(1, Math.floor(freq.length * FLUX_BAND));
  let flux = 0;
  let maxV = 0;
  for (let i = 0; i < freq.length; i++) {
    if (i < n) {
      const d = freq[i] - prevFreq[i];
      if (d > 0) flux += d;
    }
    if (freq[i] > maxV) maxV = freq[i];
    prevFreq[i] = freq[i];
  }
  flux = flux / (n * 255); // normalize to ~0-1

  applyFlux(flux, now);

  // A silence watchdog stood here, gated on `usePlayerStore.getState().isPlaying`, warning that the
  // analyser was receiving silence during playback.
  //
  // **It could never fire where it was aimed.** The surface it names in its own message is the
  // visualizer, and that surface mounts no player store — so `isPlaying` was false every time it was
  // read and the branch was unreachable. Removing it is also what frees `/visualizer` from the
  // player graph (ADR-0083 point 3): this was the last edge.
  //
  // What replaces it is better than a console warning nobody could see: the debug panel reports
  // analysis frames per second and how long since the last one, and says in words when the player
  // has stopped feeding the page.
}

function analyseLoop() {
  if (!loopRunning) return;
  animationFrameId = requestAnimationFrame(analyseLoop);

  const now = performance.now();
  // Throttle analysis work to ~30fps on mobile (still re-queues rAF above)
  if (mobile) {
    if (now - lastAnalyseTime < 33) return;
    lastAnalyseTime = now;
  }

  // --- Native analysis path (iOS Capacitor) ---
  const nativeBuffers = getNativeAnalysisBuffers();
  if (nativeBuffers.frequency && nativeBuffers.timeDomain) {
    const binCount = nativeBuffers.frequency.length;
    if (!sharedData || lastBinCount !== binCount) {
      lastBinCount = binCount;
      sharedData = {
        frequencyData: new Uint8Array(binCount),
        timeDomainData: new Uint8Array(binCount),
        averageFrequency: 0,
        bass: 0,
        mid: 0,
        treble: 0,
        beat: 0,
        onset: false,
      };
    }

    sharedData.frequencyData.set(nativeBuffers.frequency);
    sharedData.timeDomainData.set(nativeBuffers.timeDomain);
    computeBands(sharedData.frequencyData);

    if (nativeBuffers.flux && nativeBuffers.sequence !== lastNativeSequence) {
      lastNativeSequence = nativeBuffers.sequence;
      // The host sent an onset envelope, so use it rather than differencing. See
      // `setNativeAnalysisBuffers` — at 10 Hz, differencing here compares a spectrum against
      // itself five frames in six and the detector degenerates into a buffer-arrival counter.
      //
      // `prevFreq` is still kept in step so that a host which *stops* sending an envelope falls
      // back to differencing cleanly instead of on a spectrum from minutes ago.
      if (!prevFreq || prevFreq.length !== sharedData.frequencyData.length) {
        prevFreq = new Uint8Array(sharedData.frequencyData.length);
      }
      prevFreq.set(sharedData.frequencyData);
      applyFluxEnvelope(nativeBuffers.flux, now, nativeBuffers.fluxInterval || 1 / 43);
    } else if (!nativeBuffers.flux) {
      computeOnset(sharedData.frequencyData, now);
    } else {
      // Same envelope as last frame — already consumed. Decay the beat envelope on the render
      // clock so it still falls smoothly at 60 fps between the channel's 10 Hz arrivals.
      decayBeat(now);
    }
    sharedAudioDataRef.current = sharedData;
    recordConsumedAnalysisFrame('native', sharedData.frequencyData, sharedData.timeDomainData);
    return;
  }

  // --- Web Audio AnalyserNode path ---
  const analyser = getAudioAnalyser();
  const context = getAudioContext();

  if (!analyser || !context || context.state !== 'running') {
    return;
  }

  // Lazily allocate buffers once (when analyser size is known)
  const binCount = analyser.frequencyBinCount;
  if (!sharedData || lastBinCount !== binCount) {
    lastBinCount = binCount;
    sharedData = {
      frequencyData: new Uint8Array(binCount),
      timeDomainData: new Uint8Array(binCount),
      averageFrequency: 0,
      bass: 0,
      mid: 0,
      treble: 0,
      beat: 0,
      onset: false,
    };
  }

  // Read directly into the shared buffers (no allocations, no copy)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  analyser.getByteFrequencyData(sharedData.frequencyData as any);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  analyser.getByteTimeDomainData(sharedData.timeDomainData as any);

  computeBands(sharedData.frequencyData);
  computeOnset(sharedData.frequencyData, now);
  sharedAudioDataRef.current = sharedData;
  recordConsumedAnalysisFrame('web', sharedData.frequencyData, sharedData.timeDomainData);
}

function startLoop() {
  if (loopRunning) return;
  loopRunning = true;
  animationFrameId = requestAnimationFrame(analyseLoop);
}

function stopLoop() {
  loopRunning = false;
  if (animationFrameId !== undefined) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = undefined;
  }
}

// Get current audio data synchronously (for use in useFrame / rAF loops)
export function getAudioData(): AudioAnalysisData | null {
  return sharedAudioDataRef.current;
}

/**
 * Subscribe to the audio analysis loop. The first subscriber starts
 * the singleton rAF loop; the last unsubscriber stops it.
 *
 * Most consumers should read data via getAudioData() inside useFrame.
 * The returned value is the current snapshot (not reactive — no
 * React re-renders are triggered by audio data changes).
 */
export function useAudioAnalyser(enabled: boolean = true): AudioAnalysisData | null {
  useEffect(() => {
    if (!enabled) return;

    subscriberCount++;
    startLoop();

    return () => {
      subscriberCount--;
      if (subscriberCount <= 0) {
        subscriberCount = 0;
        stopLoop();
      }
    };
  }, [enabled]);

  return enabled ? sharedAudioDataRef.current : null;
}
