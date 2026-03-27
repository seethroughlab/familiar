/**
 * Adapts the Capacitor FamiliarAmbientSynth plugin to the
 * AmbientSynthBridge interface used by the shared frontend.
 */

import type { AmbientSynthBridge } from '@familiar/frontend/src/player/ambient/ambientSynthBridge';
import { FamiliarAmbientSynth } from './plugins/familiarAmbientSynth';

export class CapacitorAmbientSynthAdapter implements AmbientSynthBridge {
  async configure(params: {
    droneVolume: number;
    motifVolume: number;
    reverbMix: number;
    delayMix: number;
    lowpassFreq: number;
  }): Promise<void> {
    await FamiliarAmbientSynth.configure(params);
  }

  async startDrone(rootNote: number, secondNote: number): Promise<void> {
    await FamiliarAmbientSynth.startDrone({ rootNote, secondNote });
  }

  async glideDrone(rootNote: number, secondNote: number, glideMs: number): Promise<void> {
    await FamiliarAmbientSynth.glideDrone({ rootNote, secondNote, glideMs });
  }

  async playMotif(motifNotes: number[], motifTimingsMs: number[], motifNoteDurationMs: number): Promise<void> {
    await FamiliarAmbientSynth.playMotif({ motifNotes, motifTimingsMs, motifNoteDurationMs });
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
}
