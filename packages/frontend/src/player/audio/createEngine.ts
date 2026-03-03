import type { AudioEngine } from './types';

/**
 * Registration-based engine factory.
 * Platform-specific packages (web, ios) register their engine implementation
 * at boot time, before the app renders.
 */
let factory: (() => AudioEngine) | null = null;

export function registerEngineFactory(f: () => AudioEngine): void {
  factory = f;
}

export function createEngine(): AudioEngine {
  if (!factory) {
    throw new Error('No audio engine registered. Call registerEngineFactory() before rendering the app.');
  }
  return factory();
}
