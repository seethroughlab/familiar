import { BaseEffect } from './BaseEffect';
import type { ChorusState } from '../../../stores/audioEffectsStore';

/**
 * Chorus Effect - creates thickness and movement through modulated delays.
 *
 * Uses multiple delay lines with LFO modulation to create a rich,
 * detuned sound. Classic chorus uses 2-3 voices with slightly different
 * modulation rates for a fuller sound.
 */
export class ChorusEffect extends BaseEffect {
  private delays: DelayNode[];
  private lfos: OscillatorNode[];
  private lfoGains: GainNode[];
  private voiceGains: GainNode[];
  private merger: ChannelMergerNode;
  private _rate: number = 1;
  private _depth: number = 0.002;
  private _voices: number = 2;

  constructor(audioContext: AudioContext) {
    super(audioContext);

    // Create 3 voice chorus (we'll control how many are active)
    this.delays = [];
    this.lfos = [];
    this.lfoGains = [];
    this.voiceGains = [];

    this.merger = audioContext.createChannelMerger(2);

    // Create 3 voices with slightly different characteristics
    for (let i = 0; i < 3; i++) {
      // Delay line (base delay around 20-30ms)
      const delay = audioContext.createDelay(0.1);
      delay.delayTime.value = 0.025 + i * 0.005; // 25ms, 30ms, 35ms base

      // LFO for modulating delay time
      const lfo = audioContext.createOscillator();
      lfo.type = 'sine';
      lfo.frequency.value = 0.5 + i * 0.3; // Slightly different rates

      // LFO gain controls modulation depth
      const lfoGain = audioContext.createGain();
      lfoGain.gain.value = 0.002; // 2ms depth

      // Voice output gain
      const voiceGain = audioContext.createGain();
      voiceGain.gain.value = i < 2 ? 0.5 : 0; // Only 2 voices active by default

      // Connect LFO to delay time
      lfo.connect(lfoGain);
      lfoGain.connect(delay.delayTime);

      // Connect delay to voice gain, then to stereo merger
      // Spread voices across stereo field
      delay.connect(voiceGain);

      // Pan voices: voice 0 -> left, voice 1 -> right, voice 2 -> center
      if (i === 0) {
        voiceGain.connect(this.merger, 0, 0); // Left
        const rightGain = audioContext.createGain();
        rightGain.gain.value = 0.3;
        voiceGain.connect(rightGain);
        rightGain.connect(this.merger, 0, 1);
      } else if (i === 1) {
        voiceGain.connect(this.merger, 0, 1); // Right
        const leftGain = audioContext.createGain();
        leftGain.gain.value = 0.3;
        voiceGain.connect(leftGain);
        leftGain.connect(this.merger, 0, 0);
      } else {
        // Center voice
        voiceGain.connect(this.merger, 0, 0);
        voiceGain.connect(this.merger, 0, 1);
      }

      // Start LFO
      lfo.start();

      this.delays.push(delay);
      this.lfos.push(lfo);
      this.lfoGains.push(lfoGain);
      this.voiceGains.push(voiceGain);
    }

    // Connect input to all delay lines
    const inputSplitter = audioContext.createGain();
    for (const delay of this.delays) {
      inputSplitter.connect(delay);
    }

    // Connect wet path
    this.connectWetPath(inputSplitter, this.merger);
  }

  /**
   * Set LFO rate in Hz (0.1 to 5)
   */
  setRate(rate: number): void {
    this._rate = Math.max(0.1, Math.min(5, rate));

    this.lfos.forEach((lfo, i) => {
      // Each voice has slightly different rate for richness
      const voiceRate = this._rate * (1 + i * 0.15);
      this.setParamSmooth(lfo.frequency, voiceRate);
    });
  }

  /**
   * Set modulation depth in ms (0 to 10)
   */
  setDepth(depthMs: number): void {
    this._depth = Math.max(0, Math.min(0.01, depthMs / 1000));

    this.lfoGains.forEach((gain) => {
      this.setParamSmooth(gain.gain, this._depth);
    });
  }

  /**
   * Set number of active voices (2 or 3)
   */
  setVoices(voices: number): void {
    this._voices = Math.max(2, Math.min(3, Math.round(voices)));

    this.voiceGains.forEach((gain, i) => {
      const active = i < this._voices;
      const level = active ? 0.5 : 0;
      this.setParamSmooth(gain.gain, level);
    });
  }

  /**
   * Update all parameters from state
   */
  updateFromState(state: ChorusState): void {
    this.enabled = state.enabled;
    this.setRate(state.rate);
    this.setDepth(state.depth);
    this.setVoices(state.voices);
    this.mix = state.mix;
  }

  dispose(): void {
    super.dispose();
    this.lfos.forEach((lfo) => {
      lfo.stop();
      lfo.disconnect();
    });
    this.delays.forEach((d) => d.disconnect());
    this.lfoGains.forEach((g) => g.disconnect());
    this.voiceGains.forEach((g) => g.disconnect());
    this.merger.disconnect();
  }
}
