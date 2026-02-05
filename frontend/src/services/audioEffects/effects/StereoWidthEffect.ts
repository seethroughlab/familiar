import { BaseEffect } from './BaseEffect';
import type { StereoWidthState } from '../../../stores/audioEffectsStore';

/**
 * Stereo Width Effect - expands or narrows the stereo image.
 *
 * Uses mid-side processing:
 * - Mid = (L + R) / 2 (center/mono content)
 * - Side = (L - R) / 2 (stereo content)
 *
 * Width control adjusts the balance between mid and side:
 * - 0% = mono (no side)
 * - 100% = normal stereo
 * - 200% = extra wide (boosted side, reduced mid)
 */
export class StereoWidthEffect extends BaseEffect {
  private splitter: ChannelSplitterNode;
  private merger: ChannelMergerNode;

  // Left output gains
  private midGainL: GainNode;
  private midGainR: GainNode;
  private sideGainL: GainNode;
  private sideGainR: GainNode;

  // Right output gains
  private midGainL2: GainNode;
  private midGainR2: GainNode;
  private sideGainL2: GainNode;
  private sideGainR2: GainNode;

  constructor(audioContext: AudioContext) {
    super(audioContext);

    // Create channel splitter and merger
    this.splitter = audioContext.createChannelSplitter(2);
    this.merger = audioContext.createChannelMerger(2);

    // Create gain nodes for mid-side processing
    // For left output: L = Mid + Side = (L+R)/2 + (L-R)/2
    // For right output: R = Mid - Side = (L+R)/2 - (L-R)/2
    this.midGainL = audioContext.createGain();
    this.midGainR = audioContext.createGain();
    this.sideGainL = audioContext.createGain();
    this.sideGainR = audioContext.createGain();

    // Initial gains for 100% width (normal stereo)
    this.midGainL.gain.value = 0.5;
    this.midGainR.gain.value = 0.5;
    this.sideGainL.gain.value = 0.5;
    this.sideGainR.gain.value = -0.5; // Negative for right channel

    // Split input into L and R
    // Left channel contributions to output
    this.splitter.connect(this.midGainL, 0);  // L -> midL
    this.splitter.connect(this.sideGainL, 0); // L -> sideL

    // Right channel contributions to output
    this.splitter.connect(this.midGainR, 1);  // R -> midR
    this.splitter.connect(this.sideGainR, 1); // R -> sideR

    // Merge to left output
    this.midGainL.connect(this.merger, 0, 0);
    this.midGainR.connect(this.merger, 0, 0);
    this.sideGainL.connect(this.merger, 0, 0);
    this.sideGainR.connect(this.merger, 0, 0);

    // Right output (same gains but side is inverted)
    this.midGainL2 = audioContext.createGain();
    this.midGainR2 = audioContext.createGain();
    this.sideGainL2 = audioContext.createGain();
    this.sideGainR2 = audioContext.createGain();

    this.midGainL2.gain.value = 0.5;
    this.midGainR2.gain.value = 0.5;
    this.sideGainL2.gain.value = -0.5; // Inverted for right output
    this.sideGainR2.gain.value = 0.5;

    this.splitter.connect(this.midGainL2, 0);
    this.splitter.connect(this.sideGainL2, 0);
    this.splitter.connect(this.midGainR2, 1);
    this.splitter.connect(this.sideGainR2, 1);

    this.midGainL2.connect(this.merger, 0, 1);
    this.midGainR2.connect(this.merger, 0, 1);
    this.sideGainL2.connect(this.merger, 0, 1);
    this.sideGainR2.connect(this.merger, 0, 1);

    // Connect wet path
    this.connectWetPath(this.splitter, this.merger);

    // Full wet when enabled
    this._mix = 1;
  }

  /**
   * Set stereo width (0 = mono, 1 = normal, 2 = extra wide)
   */
  setWidth(width: number): void {
    const w = Math.max(0, Math.min(2, width));

    // Calculate mid and side amounts
    // At width=0: mid=1, side=0 (mono)
    // At width=1: mid=0.5, side=0.5 (normal)
    // At width=2: mid=0, side=1 (extra wide)
    const midAmount = 1 - w * 0.5;
    const sideAmount = w * 0.5;

    // Update left output gains
    this.setParamSmooth(this.midGainL.gain, midAmount);
    this.setParamSmooth(this.midGainR.gain, midAmount);
    this.setParamSmooth(this.sideGainL.gain, sideAmount);
    this.setParamSmooth(this.sideGainR.gain, -sideAmount);

    // Update right output gains
    this.setParamSmooth(this.midGainL2.gain, midAmount);
    this.setParamSmooth(this.midGainR2.gain, midAmount);
    this.setParamSmooth(this.sideGainL2.gain, -sideAmount);
    this.setParamSmooth(this.sideGainR2.gain, sideAmount);
  }

  /**
   * Update all parameters from state
   */
  updateFromState(state: StereoWidthState): void {
    this.enabled = state.enabled;
    this.setWidth(state.width);
  }

  dispose(): void {
    super.dispose();
    this.splitter.disconnect();
    this.merger.disconnect();
    this.midGainL.disconnect();
    this.midGainR.disconnect();
    this.sideGainL.disconnect();
    this.sideGainR.disconnect();
    this.midGainL2.disconnect();
    this.midGainR2.disconnect();
    this.sideGainL2.disconnect();
    this.sideGainR2.disconnect();
  }
}
