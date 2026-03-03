import { BaseEffect } from './BaseEffect';
import type { CompressorState } from '@familiar/frontend/src/stores/audioEffectsStore';

/**
 * Dynamics compressor using Web Audio DynamicsCompressorNode
 * with makeup gain.
 */
export class CompressorEffect extends BaseEffect {
  private compressor: DynamicsCompressorNode;
  private makeupGain: GainNode;

  constructor(audioContext: AudioContext) {
    super(audioContext);

    // Create compressor
    this.compressor = audioContext.createDynamicsCompressor();
    this.compressor.threshold.value = -24;
    this.compressor.ratio.value = 4;
    this.compressor.attack.value = 0.003;
    this.compressor.release.value = 0.25;
    this.compressor.knee.value = 30;

    // Create makeup gain
    this.makeupGain = audioContext.createGain();
    this.makeupGain.gain.value = 1;

    // Chain: compressor -> makeupGain
    this.compressor.connect(this.makeupGain);

    // Connect wet path
    this.connectWetPath(this.compressor, this.makeupGain);

    // Compressor uses mix = 1 (inline processing)
    this._mix = 1;
  }

  /**
   * Set threshold in dB (-60 to 0)
   */
  setThreshold(threshold: number): void {
    this.setParamSmooth(
      this.compressor.threshold,
      Math.max(-60, Math.min(0, threshold))
    );
  }

  /**
   * Set ratio (1 to 20)
   */
  setRatio(ratio: number): void {
    this.setParamSmooth(this.compressor.ratio, Math.max(1, Math.min(20, ratio)));
  }

  /**
   * Set attack time in seconds (0 to 1)
   */
  setAttack(attack: number): void {
    this.setParamSmooth(this.compressor.attack, Math.max(0, Math.min(1, attack)));
  }

  /**
   * Set release time in seconds (0 to 1)
   */
  setRelease(release: number): void {
    this.setParamSmooth(
      this.compressor.release,
      Math.max(0, Math.min(1, release))
    );
  }

  /**
   * Set knee width in dB (0 to 40)
   */
  setKnee(knee: number): void {
    this.setParamSmooth(this.compressor.knee, Math.max(0, Math.min(40, knee)));
  }

  /**
   * Set makeup gain in dB (0 to 12)
   * Converts from dB to linear gain
   */
  setMakeupGain(gainDb: number): void {
    const linearGain = Math.pow(10, Math.max(0, Math.min(12, gainDb)) / 20);
    this.setParamSmooth(this.makeupGain.gain, linearGain);
  }

  /**
   * Get current gain reduction (for metering)
   */
  getReduction(): number {
    return this.compressor.reduction;
  }

  /**
   * Update all parameters from state
   */
  updateFromState(state: CompressorState): void {
    this.enabled = state.enabled;
    this.setThreshold(state.threshold);
    this.setRatio(state.ratio);
    this.setAttack(state.attack);
    this.setRelease(state.release);
    this.setKnee(state.knee);
    this.setMakeupGain(state.makeupGain);
  }

  dispose(): void {
    super.dispose();
    this.compressor.disconnect();
    this.makeupGain.disconnect();
  }
}
