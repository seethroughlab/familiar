import { BaseEffect } from './BaseEffect';
import type { FilterState } from '@familiar/frontend/src/stores/audioEffectsStore';

/**
 * High-pass and low-pass filter combination.
 *
 * Useful for removing low rumble or harsh high frequencies,
 * or for creative DJ-style filter sweeps.
 */
export class FilterEffect extends BaseEffect {
  private highpassFilter: BiquadFilterNode;
  private lowpassFilter: BiquadFilterNode;

  constructor(audioContext: AudioContext) {
    super(audioContext);

    // Create highpass filter
    this.highpassFilter = audioContext.createBiquadFilter();
    this.highpassFilter.type = 'highpass';
    this.highpassFilter.frequency.value = 20; // Essentially off
    this.highpassFilter.Q.value = 0.7;

    // Create lowpass filter
    this.lowpassFilter = audioContext.createBiquadFilter();
    this.lowpassFilter.type = 'lowpass';
    this.lowpassFilter.frequency.value = 20000; // Essentially off
    this.lowpassFilter.Q.value = 0.7;

    // Chain: highpass -> lowpass
    this.highpassFilter.connect(this.lowpassFilter);

    // Connect wet path
    this.connectWetPath(this.highpassFilter, this.lowpassFilter);

    // Filter uses mix = 1 (inline processing)
    this._mix = 1;
  }

  /**
   * Set highpass filter frequency in Hz (20 to 2000)
   * Setting to 20Hz effectively disables the filter
   */
  setHighpassFrequency(freq: number): void {
    this.setParamSmooth(
      this.highpassFilter.frequency,
      Math.max(20, Math.min(2000, freq))
    );
  }

  /**
   * Set lowpass filter frequency in Hz (1000 to 20000)
   * Setting to 20000Hz effectively disables the filter
   */
  setLowpassFrequency(freq: number): void {
    this.setParamSmooth(
      this.lowpassFilter.frequency,
      Math.max(1000, Math.min(20000, freq))
    );
  }

  /**
   * Set highpass Q (resonance) value (0.1 to 10)
   */
  setHighpassQ(q: number): void {
    this.setParamSmooth(this.highpassFilter.Q, Math.max(0.1, Math.min(10, q)));
  }

  /**
   * Set lowpass Q (resonance) value (0.1 to 10)
   */
  setLowpassQ(q: number): void {
    this.setParamSmooth(this.lowpassFilter.Q, Math.max(0.1, Math.min(10, q)));
  }

  /**
   * Update all parameters from state
   */
  updateFromState(state: FilterState): void {
    this.enabled = state.enabled;
    this.setHighpassFrequency(state.highpassFreq);
    this.setLowpassFrequency(state.lowpassFreq);
    this.setHighpassQ(state.highpassQ);
    this.setLowpassQ(state.lowpassQ);
  }

  /**
   * Get current filter frequencies for display
   */
  getFrequencies(): { highpass: number; lowpass: number } {
    return {
      highpass: this.highpassFilter.frequency.value,
      lowpass: this.lowpassFilter.frequency.value,
    };
  }

  dispose(): void {
    super.dispose();
    this.highpassFilter.disconnect();
    this.lowpassFilter.disconnect();
  }
}
