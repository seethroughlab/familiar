import type { AudioEngine } from './types';
import { createEngine } from './createEngine';

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

/**
 * MediaStream branched off the engine's master output, for WebRTC streaming.
 * Returns null when the engine has no implementation (iOS) or audio isn't running yet.
 */
export function getEngineOutputStream(): MediaStream | null {
  const e = getEngine();
  return e.getOutputStream?.() ?? null;
}

export function areAudioEffectsAvailable(): boolean {
  const e = getEngine();
  return e.capabilities.effects !== 'none';
}

export function isVisualizerAvailable(): boolean {
  const e = getEngine();
  return e.capabilities.visualizer;
}

export function getCurrentMode(): 'webaudio' | 'native' {
  const e = getEngine();
  return e.capabilities.effects === 'native' ? 'native' : 'webaudio';
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
