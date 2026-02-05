import { BaseEffect } from './BaseEffect';
import type { TremoloState } from '../../../stores/audioEffectsStore';

/**
 * Tremolo Effect - rhythmic volume modulation.
 *
 * Uses an LFO to modulate the amplitude for classic amp tremolo sounds.
 * Different waveforms provide different characteristics:
 * - Sine: Smooth, classic tremolo
 * - Triangle: Linear, more pronounced
 * - Square: Choppy, gate-like effect
 */
export class TremoloEffect extends BaseEffect {
  private lfo: OscillatorNode;
  private lfoGain: GainNode;
  private tremGain: GainNode;
  private _rate: number = 4;
  private _depth: number = 0.5;

  constructor(audioContext: AudioContext) {
    super(audioContext);

    // LFO oscillator
    this.lfo = audioContext.createOscillator();
    this.lfo.type = 'sine';
    this.lfo.frequency.value = 4; // 4 Hz default

    // LFO gain controls modulation depth
    this.lfoGain = audioContext.createGain();
    this.lfoGain.gain.value = 0.5; // 50% depth

    // Tremolo gain node - this is what modulates the audio
    this.tremGain = audioContext.createGain();
    this.tremGain.gain.value = 1;

    // Connect LFO to tremolo gain
    // LFO output is -1 to 1, we need to offset and scale it
    // Final gain = 1 - depth + (depth * lfo)
    // At depth=0.5: gain oscillates between 0.5 and 1
    this.lfo.connect(this.lfoGain);
    this.lfoGain.connect(this.tremGain.gain);

    // Start LFO
    this.lfo.start();

    // Connect wet path
    this.connectWetPath(this.tremGain, this.tremGain);

    // Tremolo is fully wet when enabled
    this._mix = 1;

    // Update the base gain value
    this.updateModulation();
  }

  /**
   * Update modulation parameters
   */
  private updateModulation(): void {
    // Set LFO gain for depth
    // The LFO oscillates around the base gain value
    this.setParamSmooth(this.lfoGain.gain, this._depth / 2);

    // Set base gain so signal oscillates between (1-depth) and 1
    // tremGain.gain = baseBias + lfoOutput
    // We want: gain = 1 - depth/2 + lfo * depth/2
    // So when lfo = -1: gain = 1 - depth
    // When lfo = +1: gain = 1
    const baseBias = 1 - this._depth / 2;

    // Cancel scheduled values and set new base
    const now = this.audioContext.currentTime;
    this.tremGain.gain.cancelScheduledValues(now);
    this.tremGain.gain.setValueAtTime(baseBias, now);
  }

  /**
   * Set LFO rate in Hz (0.5 to 20)
   */
  setRate(rate: number): void {
    this._rate = Math.max(0.5, Math.min(20, rate));
    this.setParamSmooth(this.lfo.frequency, this._rate);
  }

  /**
   * Set modulation depth (0 to 1)
   */
  setDepth(depth: number): void {
    this._depth = Math.max(0, Math.min(1, depth));
    this.updateModulation();
  }

  /**
   * Set LFO waveform shape
   */
  setShape(shape: 'sine' | 'triangle' | 'square'): void {
    this.lfo.type = shape;
  }

  /**
   * Update all parameters from state
   */
  updateFromState(state: TremoloState): void {
    this.enabled = state.enabled;
    this.setRate(state.rate);
    this.setDepth(state.depth);
    this.setShape(state.shape);
  }

  dispose(): void {
    super.dispose();
    this.lfo.stop();
    this.lfo.disconnect();
    this.lfoGain.disconnect();
    this.tremGain.disconnect();
  }
}
