/**
 * Adapts the Capacitor FamiliarAmbientSynth plugin to the
 * AmbientSynthBridge interface used by the shared frontend.
 */

import type { AmbientSynthBridge } from '@familiar/frontend/src/player/ambient/ambientSynthBridge';
import type { TransitionRecipe } from '@familiar/frontend/src/player/ambient/types';
import { FamiliarAmbientSynth } from './plugins/familiarAmbientSynth';

export class CapacitorAmbientSynthAdapter implements AmbientSynthBridge {
  private transitionCompleteHandlers = new Set<() => void>();

  async configure(params: {
    droneVolume: number;
    motifVolume: number;
    reverbMix: number;
    delayMix: number;
    lowpassFreq: number;
  }): Promise<void> {
    await FamiliarAmbientSynth.configure(params);
  }

  async startTransition(recipe: TransitionRecipe): Promise<void> {
    await FamiliarAmbientSynth.startTransition(recipe);
    // Estimate transition complete based on drone attack + motif duration
    const estimatedDuration = recipe.droneAttackMs + recipe.motifNoteDurationMs;
    setTimeout(() => {
      this.transitionCompleteHandlers.forEach(h => h());
    }, estimatedDuration);
  }

  async stopImmediate(): Promise<void> {
    await FamiliarAmbientSynth.stopImmediate();
  }

  async stopWithRelease(releaseMs: number): Promise<void> {
    await FamiliarAmbientSynth.stopWithRelease({ releaseMs });
  }

  async updateMix(params: {
    droneVolume?: number;
    motifVolume?: number;
    reverbMix?: number;
  }): Promise<void> {
    await FamiliarAmbientSynth.updateMix(params);
  }

  onTransitionComplete(handler: () => void): () => void {
    this.transitionCompleteHandlers.add(handler);
    return () => this.transitionCompleteHandlers.delete(handler);
  }
}
