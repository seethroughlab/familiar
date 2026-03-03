import { BaseEffect } from './BaseEffect';
import type { DelayState } from '@familiar/frontend/src/stores/audioEffectsStore';

/**
 * Delay effect with feedback and optional ping-pong stereo mode.
 *
 * For ping-pong mode, we use a stereo approach where left and right
 * channels are delayed alternately.
 */
export class DelayEffect extends BaseEffect {
  private delayNodeL: DelayNode;
  private delayNodeR: DelayNode;
  private feedbackGainL: GainNode;
  private feedbackGainR: GainNode;
  private splitter: ChannelSplitterNode;
  private merger: ChannelMergerNode;
  private monoDelay: DelayNode;
  private monoFeedback: GainNode;
  private _pingPong: boolean = false;

  constructor(audioContext: AudioContext) {
    super(audioContext);

    // Create mono delay path (used when ping-pong is off)
    this.monoDelay = audioContext.createDelay(2);
    this.monoDelay.delayTime.value = 0.3;

    this.monoFeedback = audioContext.createGain();
    this.monoFeedback.gain.value = 0.3;

    // Mono feedback loop
    this.monoDelay.connect(this.monoFeedback);
    this.monoFeedback.connect(this.monoDelay);

    // Create stereo ping-pong path
    this.splitter = audioContext.createChannelSplitter(2);
    this.merger = audioContext.createChannelMerger(2);

    this.delayNodeL = audioContext.createDelay(2);
    this.delayNodeL.delayTime.value = 0.3;

    this.delayNodeR = audioContext.createDelay(2);
    this.delayNodeR.delayTime.value = 0.3;

    this.feedbackGainL = audioContext.createGain();
    this.feedbackGainL.gain.value = 0.3;

    this.feedbackGainR = audioContext.createGain();
    this.feedbackGainR.gain.value = 0.3;

    // Ping-pong routing: L -> delayL -> feedbackL -> delayR
    //                     R -> delayR -> feedbackR -> delayL
    this.splitter.connect(this.delayNodeL, 0);
    this.splitter.connect(this.delayNodeR, 1);

    this.delayNodeL.connect(this.feedbackGainL);
    this.delayNodeR.connect(this.feedbackGainR);

    // Cross-feedback for ping-pong
    this.feedbackGainL.connect(this.delayNodeR);
    this.feedbackGainR.connect(this.delayNodeL);

    // Output to merger
    this.delayNodeL.connect(this.merger, 0, 0);
    this.delayNodeR.connect(this.merger, 0, 1);

    // Initially use mono path
    this.connectWetPath(this.monoDelay, this.monoDelay);
  }

  /**
   * Set ping-pong mode
   */
  set pingPong(value: boolean) {
    if (this._pingPong === value) return;

    // Disconnect current wet path based on CURRENT state (before update)
    if (this._pingPong) {
      // Currently ping-pong, disconnect stereo path
      this.inputNode.disconnect(this.splitter);
      this.merger.disconnect(this.wetGain);
    } else {
      // Currently mono, disconnect mono path
      this.inputNode.disconnect(this.monoDelay);
      this.monoDelay.disconnect(this.wetGain);
    }

    this._pingPong = value;

    if (value) {
      // Use stereo ping-pong path
      this.inputNode.connect(this.splitter);
      this.merger.connect(this.wetGain);
    } else {
      // Use mono path
      this.inputNode.connect(this.monoDelay);
      this.monoDelay.connect(this.wetGain);
    }
  }

  get pingPong(): boolean {
    return this._pingPong;
  }

  /**
   * Set delay time in seconds (0 to 2)
   */
  setTime(seconds: number): void {
    const time = Math.max(0.001, Math.min(2, seconds));
    this.setParamSmooth(this.monoDelay.delayTime, time);
    this.setParamSmooth(this.delayNodeL.delayTime, time);
    this.setParamSmooth(this.delayNodeR.delayTime, time);
  }

  /**
   * Set feedback amount (0 to 0.9)
   * Capped at 0.9 to prevent runaway feedback
   */
  setFeedback(amount: number): void {
    const feedback = Math.max(0, Math.min(0.9, amount));
    this.setParamSmooth(this.monoFeedback.gain, feedback);
    this.setParamSmooth(this.feedbackGainL.gain, feedback);
    this.setParamSmooth(this.feedbackGainR.gain, feedback);
  }

  /**
   * Update all parameters from state
   */
  updateFromState(state: DelayState): void {
    this.enabled = state.enabled;
    this.mix = state.mix;
    this.pingPong = state.pingPong;
    this.setTime(state.time);
    this.setFeedback(state.feedback);
  }

  dispose(): void {
    super.dispose();
    this.monoDelay.disconnect();
    this.monoFeedback.disconnect();
    this.delayNodeL.disconnect();
    this.delayNodeR.disconnect();
    this.feedbackGainL.disconnect();
    this.feedbackGainR.disconnect();
    this.splitter.disconnect();
    this.merger.disconnect();
  }
}
