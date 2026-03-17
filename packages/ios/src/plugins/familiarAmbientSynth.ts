/**
 * Capacitor plugin type definition for FamiliarAmbientSynth.
 *
 * Mirrors the AmbientSynthBridge interface for the native Swift implementation.
 */

import { registerPlugin } from '@capacitor/core';

export interface FamiliarAmbientSynthPlugin {
  configure(options: {
    droneVolume: number;
    motifVolume: number;
    reverbMix: number;
    delayMix: number;
    lowpassFreq: number;
  }): Promise<void>;

  startTransition(options: {
    droneRootNote: number;
    droneSecondNote: number;
    droneAttackMs: number;
    droneReleaseMs: number;
    motifNotes: number[];
    motifTimingsMs: number[];
    motifNoteDurationMs: number;
  }): Promise<void>;

  stopImmediate(): Promise<void>;

  stopWithRelease(options: { releaseMs: number }): Promise<void>;

  updateMix(options: {
    droneVolume?: number;
    motifVolume?: number;
    reverbMix?: number;
  }): Promise<void>;
}

export const FamiliarAmbientSynth = registerPlugin<FamiliarAmbientSynthPlugin>('FamiliarAmbientSynth');
