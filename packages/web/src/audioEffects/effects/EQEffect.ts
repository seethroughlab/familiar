import { BaseEffect } from './BaseEffect';
import type { EQState } from '@familiar/frontend/src/stores/audioEffectsStore';

/**
 * 3-band equalizer using BiquadFilterNodes.
 * - Low shelf at ~250 Hz
 * - Peaking filter at ~1000 Hz for mids
 * - High shelf at ~4000 Hz
 */
export class EQEffect extends BaseEffect {
  private lowShelf: BiquadFilterNode;
  private midPeak: BiquadFilterNode;
  private highShelf: BiquadFilterNode;

  constructor(audioContext: AudioContext) {
    super(audioContext);

    // Create the three EQ bands
    this.lowShelf = audioContext.createBiquadFilter();
    this.lowShelf.type = 'lowshelf';
    this.lowShelf.frequency.value = 250;
    this.lowShelf.gain.value = 0;

    this.midPeak = audioContext.createBiquadFilter();
    this.midPeak.type = 'peaking';
    this.midPeak.frequency.value = 1000;
    this.midPeak.Q.value = 1;
    this.midPeak.gain.value = 0;

    this.highShelf = audioContext.createBiquadFilter();
    this.highShelf.type = 'highshelf';
    this.highShelf.frequency.value = 4000;
    this.highShelf.gain.value = 0;

    // Chain the filters
    this.lowShelf.connect(this.midPeak);
    this.midPeak.connect(this.highShelf);

    // Connect wet path
    this.connectWetPath(this.lowShelf, this.highShelf);

    // EQ uses mix = 1 (fully wet when enabled) since it's inline processing
    this._mix = 1;
  }

  /**
   * Set low band gain in dB (-12 to +12)
   */
  setLowGain(gain: number): void {
    this.setParamSmooth(this.lowShelf.gain, Math.max(-12, Math.min(12, gain)));
  }

  /**
   * Set mid band gain in dB (-12 to +12)
   */
  setMidGain(gain: number): void {
    this.setParamSmooth(this.midPeak.gain, Math.max(-12, Math.min(12, gain)));
  }

  /**
   * Set high band gain in dB (-12 to +12)
   */
  setHighGain(gain: number): void {
    this.setParamSmooth(this.highShelf.gain, Math.max(-12, Math.min(12, gain)));
  }

  /**
   * Update all parameters from state
   */
  updateFromState(state: EQState): void {
    this.enabled = state.enabled;
    this.setLowGain(state.lowGain);
    this.setMidGain(state.midGain);
    this.setHighGain(state.highGain);
  }

  dispose(): void {
    super.dispose();
    this.lowShelf.disconnect();
    this.midPeak.disconnect();
    this.highShelf.disconnect();
  }
}
