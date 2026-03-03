import { BaseEffect } from './BaseEffect';
import type { SaturationState } from '@familiar/frontend/src/stores/audioEffectsStore';

/**
 * Saturation Effect - adds harmonic warmth and soft clipping.
 *
 * Uses a WaveShaperNode with different saturation curves:
 * - Warm: Gentle tube-like saturation
 * - Tape: Analog tape compression/saturation
 * - Hard: More aggressive clipping
 */
export class SaturationEffect extends BaseEffect {
  private inputGain: GainNode;
  private waveshaper: WaveShaperNode;
  private outputGain: GainNode;
  private _drive: number = 1;
  private _type: 'warm' | 'tape' | 'hard' = 'warm';

  constructor(audioContext: AudioContext) {
    super(audioContext);

    // Input gain (drive)
    this.inputGain = audioContext.createGain();
    this.inputGain.gain.value = 1;

    // Waveshaper for saturation
    this.waveshaper = audioContext.createWaveShaper();
    this.waveshaper.oversample = '2x'; // Reduce aliasing

    // Output gain (makeup/compensation)
    this.outputGain = audioContext.createGain();
    this.outputGain.gain.value = 1;

    // Connect chain
    this.inputGain.connect(this.waveshaper);
    this.waveshaper.connect(this.outputGain);

    // Set initial curve
    this.updateCurve();

    // Connect wet path
    this.connectWetPath(this.inputGain, this.outputGain);
  }

  /**
   * Generate saturation curve based on type and drive
   */
  private updateCurve(): void {
    const samples = 8192;
    const curve = new Float32Array(samples);
    const drive = this._drive;

    for (let i = 0; i < samples; i++) {
      const x = (i * 2) / samples - 1; // -1 to 1

      switch (this._type) {
        case 'warm':
          // Soft tube-like saturation using tanh
          curve[i] = Math.tanh(x * drive);
          break;

        case 'tape': {
          // Tape-like compression with asymmetric saturation
          const k = drive * 2;
          if (x >= 0) {
            curve[i] = (1 - Math.exp(-k * x)) / (1 - Math.exp(-k));
          } else {
            curve[i] = -(1 - Math.exp(k * x)) / (1 - Math.exp(-k));
          }
          // Add slight even harmonics (tape characteristic)
          curve[i] = curve[i] * 0.9 + (x * x * x) * 0.1 * drive;
          break;
        }

        case 'hard': {
          // Harder clipping with more harmonics
          const hardX = x * drive;
          if (hardX > 0.5) {
            curve[i] = 0.5 + (hardX - 0.5) / (1 + Math.pow(hardX - 0.5, 2));
          } else if (hardX < -0.5) {
            curve[i] = -0.5 + (hardX + 0.5) / (1 + Math.pow(hardX + 0.5, 2));
          } else {
            curve[i] = hardX;
          }
          // Normalize
          curve[i] = Math.max(-1, Math.min(1, curve[i]));
          break;
        }
      }
    }

    this.waveshaper.curve = curve;

    // Compensate output level based on drive
    const compensation = 1 / Math.sqrt(drive);
    this.setParamSmooth(this.outputGain.gain, compensation);
  }

  /**
   * Set drive amount (1 = subtle, 5 = heavy)
   */
  setDrive(drive: number): void {
    this._drive = Math.max(1, Math.min(5, drive));
    this.updateCurve();
  }

  /**
   * Set saturation type
   */
  setType(type: 'warm' | 'tape' | 'hard'): void {
    this._type = type;
    this.updateCurve();
  }

  /**
   * Update all parameters from state
   */
  updateFromState(state: SaturationState): void {
    this.enabled = state.enabled;
    this._drive = state.drive;
    this._type = state.type;
    this.mix = state.mix;
    this.updateCurve();
  }

  dispose(): void {
    super.dispose();
    this.inputGain.disconnect();
    this.waveshaper.disconnect();
    this.outputGain.disconnect();
  }
}
