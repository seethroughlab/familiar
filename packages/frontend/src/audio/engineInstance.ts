import type { AudioEngine, AudioEngineCapabilities } from './types';
import { assertCapabilitiesMatch, createEngine, getDeclaredCapabilities } from './createEngine';

// ============================================================================
// Singleton Engine Instance
// ============================================================================

let engine: AudioEngine | null = null;

/**
 * Get the singleton AudioEngine instance. Creates it on first call.
 *
 * **This is the only place an engine is ever constructed, and only playback should reach it.** That
 * was not true until ADR-0017's follow-up: every capability helper below used to start with a
 * `getEngine()` call, so asking whether effects were available built a `WebAudioEngine` and, with
 * it, an `AudioContext`. A component deciding whether to draw a visualizer button was starting the
 * audio stack, having played nothing.
 *
 * It mattered most where it was least visible. ADR-0016 point 4 governs embedding a web surface in
 * the Mac app and reasons that a browse-only page constructs no second engine — which was false for
 * exactly this reason, since a settings or player component asking a question was enough. The
 * separation below is what makes that premise true rather than aspirational.
 */
export function getEngine(): AudioEngine {
  if (!engine) {
    engine = createEngine();
    assertCapabilitiesMatch(engine);
  }
  return engine;
}

/**
 * The engine if one has already been built, and never a new one.
 *
 * Everything below that reaches into a live audio graph goes through this. Before anything has
 * played there are no nodes to hand out, and `null` is the honest answer — building an engine to
 * discover it has no analyser yet is how the graph came to exist before it was wanted.
 */
function existingEngine(): AudioEngine | null {
  return engine;
}

// ============================================================================
// Capabilities — answered from the registration, never by constructing
// ============================================================================

/** What an unregistered app can do, which is nothing. */
const NO_CAPABILITIES: AudioEngineCapabilities = {
  crossfade: false,
  visualizer: false,
  effects: 'none',
};

/**
 * What the audio engine can do, whether or not one exists yet.
 *
 * Reads the descriptor the platform entry point registered beside its factory. A surface that
 * registers nothing — an embedded browse-only page — gets `NO_CAPABILITIES`, so the UI hides the
 * controls it cannot honour instead of throwing.
 */
export function getEngineCapabilities(): AudioEngineCapabilities {
  return getDeclaredCapabilities() ?? NO_CAPABILITIES;
}

export function areAudioEffectsAvailable(): boolean {
  return getEngineCapabilities().effects !== 'none';
}

export function isVisualizerAvailable(): boolean {
  return getEngineCapabilities().visualizer;
}

export function getCurrentMode(): 'webaudio' | 'native' {
  return getEngineCapabilities().effects === 'native' ? 'native' : 'webaudio';
}

// ============================================================================
// Live audio nodes (used by visualizer, effects, WebRTC, debug)
// ============================================================================

export function getAudioAnalyser(): AnalyserNode | null {
  return existingEngine()?.getAnalyser?.() ?? null;
}

export function getAudioContext(): AudioContext | null {
  return existingEngine()?.getAudioContext?.() ?? null;
}

export function getGlobalMasterGain(): GainNode | null {
  return existingEngine()?.getMasterGainNode?.() ?? null;
}

/**
 * MediaStream branched off the engine's master output, for WebRTC streaming.
 * Returns null when the engine has no implementation (iOS), when audio isn't running yet, or when
 * nothing has been played at all.
 */
export function getEngineOutputStream(): MediaStream | null {
  return existingEngine()?.getOutputStream?.() ?? null;
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
