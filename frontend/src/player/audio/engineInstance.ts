import type { AudioEngine } from './types';
import { createEngine } from './createEngine';
import { useNativeAudioEngine, useWebAudioOnThisPlatform } from './platform';
import type { WebAudioEngine } from './WebAudioEngine';

// ============================================================================
// Singleton Engine Instance
// ============================================================================

let engine: AudioEngine | null = null;

/**
 * Get the singleton AudioEngine instance. Creates it on first call.
 */
export function getEngine(): AudioEngine {
  if (!engine) {
    engine = createEngine();
  }
  return engine;
}

// ============================================================================
// Convenience Getters (used by visualizer, effects, WebRTC, debug)
// ============================================================================

export function getAudioAnalyser(): AnalyserNode | null {
  const e = getEngine();
  return e.getAnalyser?.() ?? null;
}

export function getAudioContext(): AudioContext | null {
  const e = getEngine();
  return e.getAudioContext?.() ?? null;
}

export function getGlobalMasterGain(): GainNode | null {
  const e = getEngine();
  return e.getMasterGainNode?.() ?? null;
}

export { getEffectsChain as getAudioEffectsChain } from '../../services/audioEffects';

export function areAudioEffectsAvailable(): boolean {
  // Native engine has its own AVAudioEngine effects (EQ, reverb, delay, distortion)
  return useWebAudioOnThisPlatform || useNativeAudioEngine;
}

export function isVisualizerAvailable(): boolean {
  // Both engines now support visualizer (Web Audio via AnalyserNode, native via FFT tap)
  return true;
}

export function getCurrentMode(): 'webaudio' | 'native' {
  return useWebAudioOnThisPlatform ? 'webaudio' : 'native';
}

// ============================================================================
// For testing
// ============================================================================

export function resetEngineForTesting(): void {
  if (engine) {
    engine.dispose();
    engine = null;
  }
}

// ============================================================================
// Type-narrowed access (when you know the engine type)
// ============================================================================

export function getWebEngine(): WebAudioEngine | null {
  const e = getEngine();
  if (e.capabilities.crossfade) return e as WebAudioEngine;
  return null;
}
