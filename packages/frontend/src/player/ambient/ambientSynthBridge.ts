/**
 * Ambient synth bridge — portable interface + registration pattern.
 *
 * Mobile platforms register their native synth implementation at boot.
 * Web never registers (ambient mode requires native synth).
 */

import type { TransitionRecipe } from './types';

export interface AmbientSynthBridge {
  configure(params: {
    droneVolume: number;
    motifVolume: number;
    reverbMix: number;
    delayMix: number;
    lowpassFreq: number;
  }): Promise<void>;

  startTransition(recipe: TransitionRecipe): Promise<void>;

  stopImmediate(): Promise<void>;

  stopWithRelease(releaseMs: number): Promise<void>;

  updateMix(params: {
    droneVolume?: number;
    motifVolume?: number;
    reverbMix?: number;
  }): Promise<void>;

  onTransitionComplete(handler: () => void): () => void;
}

let _bridge: AmbientSynthBridge | null = null;

export function registerAmbientSynthBridge(bridge: AmbientSynthBridge): void {
  _bridge = bridge;
}

export function getAmbientSynthBridge(): AmbientSynthBridge | null {
  return _bridge;
}
