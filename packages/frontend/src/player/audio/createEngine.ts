import type { AudioEngine, AudioEngineCapabilities } from './types';

/**
 * Registration-based engine factory.
 * Platform-specific packages (web, ios) register their engine implementation
 * at boot time, before the app renders.
 *
 * Capabilities are registered *alongside* the factory, and separately from it, because asking what
 * an engine can do must not build one. See `engineInstance.ts` for the defect that caused: a
 * component deciding whether to draw a visualizer button was constructing an `AudioContext`.
 */
let factory: (() => AudioEngine) | null = null;
let declared: AudioEngineCapabilities | null = null;

/**
 * @param capabilities What the engine this factory builds will report. Required, and passed here
 *   rather than read off an instance, so the answer exists before anything is constructed. It is
 *   checked against the real engine the first time one is built — see `assertCapabilitiesMatch`.
 */
export function registerEngineFactory(
  f: () => AudioEngine,
  capabilities: AudioEngineCapabilities
): void {
  factory = f;
  declared = capabilities;
}

/**
 * What the registered engine can do, without building it.
 *
 * `null` when nothing has been registered, which callers turn into "can do nothing" rather than
 * into an error — a capability question has a sensible answer before boot completes, unlike a
 * request to play something.
 */
export function getDeclaredCapabilities(): AudioEngineCapabilities | null {
  return declared;
}

export function createEngine(): AudioEngine {
  if (!factory) {
    throw new Error('No audio engine registered. Call registerEngineFactory() before rendering the app.');
  }
  return factory();
}

/**
 * Catches a declaration that has drifted from the engine it describes.
 *
 * The cost of moving capabilities off the instance is that two things now state them, and they can
 * disagree — a silent, confusing failure where the UI offers effects the engine does not have.
 * Reported loudly at the one moment both are in hand, rather than thrown: a mismatch is a developer
 * error, and taking playback down for it would be worse than the bug it reports.
 */
export function assertCapabilitiesMatch(engine: AudioEngine): void {
  if (!declared) return;
  const actual = engine.capabilities;
  if (
    declared.crossfade !== actual.crossfade ||
    declared.visualizer !== actual.visualizer ||
    declared.effects !== actual.effects
  ) {
    console.error(
      '[audio] Registered capabilities do not match the engine that was built.',
      { declared, actual }
    );
  }
}

/** Test-only: forget the registration, so a suite can register a different engine. */
export function resetEngineFactoryForTesting(): void {
  factory = null;
  declared = null;
}
