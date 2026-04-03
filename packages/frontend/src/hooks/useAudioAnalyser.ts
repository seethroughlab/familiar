import { useEffect } from 'react';
import { getAudioAnalyser, getAudioContext } from '../player/audio/engineInstance';
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

function analyseLoop() {
  if (!loopRunning) return;
  animationFrameId = requestAnimationFrame(analyseLoop);

  // Throttle analysis work to ~30fps on mobile (still re-queues rAF above)
  if (mobile) {
    const now = performance.now();
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
      };
    }

    sharedData.frequencyData.set(nativeBuffers.frequency);
    sharedData.timeDomainData.set(nativeBuffers.timeDomain);
    computeBands(sharedData.frequencyData);
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
    };
  }

  // Read directly into the shared buffers (no allocations, no copy)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  analyser.getByteFrequencyData(sharedData.frequencyData as any);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  analyser.getByteTimeDomainData(sharedData.timeDomainData as any);

  computeBands(sharedData.frequencyData);
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
