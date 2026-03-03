/**
 * Base class for bypassable audio effects with wet/dry mixing.
 *
 * All effects are created once and never disconnected. Bypass is achieved
 * through wet/dry gain control to prevent audio clicks.
 */
export abstract class BaseEffect {
  protected audioContext: AudioContext;
  protected inputNode: GainNode;
  protected outputNode: GainNode;
  protected dryGain: GainNode;
  protected wetGain: GainNode;
  protected _enabled: boolean = false;
  protected _mix: number = 1; // 1 = fully wet when enabled

  constructor(audioContext: AudioContext) {
    this.audioContext = audioContext;

    // Create input/output routing nodes
    this.inputNode = audioContext.createGain();
    this.outputNode = audioContext.createGain();
    this.dryGain = audioContext.createGain();
    this.wetGain = audioContext.createGain();

    // Initial state: dry only (bypassed)
    this.dryGain.gain.value = 1;
    this.wetGain.gain.value = 0;

    // Connect dry path: input -> dryGain -> output
    this.inputNode.connect(this.dryGain);
    this.dryGain.connect(this.outputNode);

    // Wet path will be: input -> [effect processing] -> wetGain -> output
    this.wetGain.connect(this.outputNode);
  }

  /**
   * Get the input node to connect to this effect
   */
  get input(): AudioNode {
    return this.inputNode;
  }

  /**
   * Get the output node to connect from this effect
   */
  get output(): AudioNode {
    return this.outputNode;
  }

  /**
   * Enable or disable the effect with smooth gain transitions
   */
  set enabled(value: boolean) {
    this._enabled = value;
    this.updateGains();
  }

  get enabled(): boolean {
    return this._enabled;
  }

  /**
   * Set the wet/dry mix (0 = fully dry, 1 = fully wet)
   * Only applies when effect is enabled
   */
  set mix(value: number) {
    this._mix = Math.max(0, Math.min(1, value));
    this.updateGains();
  }

  get mix(): number {
    return this._mix;
  }

  /**
   * Update gain values with smooth transitions
   */
  protected updateGains(): void {
    const now = this.audioContext.currentTime;
    const smoothTime = 0.02; // 20ms smooth transition

    if (this._enabled) {
      // Equal-power crossfade
      const wetAmount = this._mix;
      const dryAmount = 1 - this._mix;

      this.wetGain.gain.setTargetAtTime(wetAmount, now, smoothTime);
      this.dryGain.gain.setTargetAtTime(dryAmount, now, smoothTime);
    } else {
      // Bypassed: dry only
      this.wetGain.gain.setTargetAtTime(0, now, smoothTime);
      this.dryGain.gain.setTargetAtTime(1, now, smoothTime);
    }
  }

  /**
   * Connect effect processing nodes. Called by subclasses to set up
   * the wet path: input -> [processing] -> wetGain
   */
  protected connectWetPath(firstNode: AudioNode, lastNode: AudioNode): void {
    this.inputNode.connect(firstNode);
    lastNode.connect(this.wetGain);
  }

  /**
   * Set a parameter with smooth transitions to prevent clicks
   */
  protected setParamSmooth(
    param: AudioParam,
    value: number,
    timeConstant: number = 0.02
  ): void {
    param.setTargetAtTime(value, this.audioContext.currentTime, timeConstant);
  }

  /**
   * Cleanup resources
   */
  dispose(): void {
    this.inputNode.disconnect();
    this.outputNode.disconnect();
    this.dryGain.disconnect();
    this.wetGain.disconnect();
  }
}
