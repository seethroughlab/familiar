import { useEffect } from 'react';
import { getAudioAnalyser, getAudioContext } from '../player/audio/engineInstance';
import { usePlayerStore } from '../stores/playerStore';
import { isMobile } from '../utils/platform';
import {
  computeFrequencyBands,
} from '../player/audio/analysisMetrics';
import { recordConsumedAnalysisFrame } from '../player/audio/analysisDiagnostics';

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
} from '../player/audio/nativeAnalysisBuffers';

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
let lastBeatUpdate = 0;

// Silence watchdog: warn once if we're "playing" but the analyser reads silence
// for a sustained period (suspended AudioContext, broken routing, CORS taint…).
let lastSignalTime = 0;
let silenceWarned = false;

function computeOnset(freq: Uint8Array, now: number): void {
  if (!prevFreq || prevFreq.length !== freq.length) {
    prevFreq = new Uint8Array(freq.length);
    prevFreq.set(freq);
    sharedData!.beat = 0;
    sharedData!.onset = false;
    lastBeatUpdate = now;
    lastSignalTime = now;
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

  // Silence watchdog (only meaningful while the player thinks it's playing).
  const playing = usePlayerStore.getState().isPlaying;
  if (!playing || maxV > 3) {
    lastSignalTime = now;
    silenceWarned = false;
  } else if (now - lastSignalTime > 1500 && !silenceWarned) {
    silenceWarned = true;
    // eslint-disable-next-line no-console
    console.warn(
      '[Visualizer] AnalyserNode is receiving silence during playback — ' +
        'check AudioContext state / audio routing / CORS on the stream.'
    );
  }
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
    computeOnset(sharedData.frequencyData, now);
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
