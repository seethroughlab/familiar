/**
 * Ambient synth bridge — portable interface + registration pattern.
 *
 * Mobile platforms register their native synth implementation at boot.
 * Web never registers (ambient mode requires native synth).
 */

export interface AmbientSynthBridge {
  configure(params: {
    droneVolume: number;
    motifVolume: number;
    reverbMix: number;
    delayMix: number;
    lowpassFreq: number;
  }): Promise<void>;

  startDrone(rootNote: number, secondNote: number): Promise<void>;

  glideDrone(rootNote: number, secondNote: number, glideMs: number): Promise<void>;

  playMotif(motifNotes: number[], motifTimingsMs: number[], motifNoteDurationMs: number): Promise<void>;

  stopImmediate(): Promise<void>;

  stopWithRelease(releaseMs: number): Promise<void>;

  updateMix(params: {
    droneVolume?: number;
    motifVolume?: number;
    reverbMix?: number;
  }): Promise<void>;
}

let _bridge: AmbientSynthBridge | null = null;

export function registerAmbientSynthBridge(bridge: AmbientSynthBridge): void {
  _bridge = bridge;
}

export function getAmbientSynthBridge(): AmbientSynthBridge | null {
  return _bridge;
}
