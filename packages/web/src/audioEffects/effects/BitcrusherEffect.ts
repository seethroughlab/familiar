import { BaseEffect } from './BaseEffect';
import type { BitcrusherState } from '@familiar/frontend/src/stores/audioEffectsStore';

/**
 * Bitcrusher Effect - digital degradation for lo-fi sounds.
 *
 * Uses an AudioWorklet for real-time bit depth and sample rate reduction.
 * Falls back to a WaveShaper approximation if worklets aren't available.
 */
export class BitcrusherEffect extends BaseEffect {
  private workletNode: AudioWorkletNode | null = null;
  private fallbackShaper: WaveShaperNode | null = null;
  private fallbackFilter: BiquadFilterNode | null = null;
  private _bits: number = 16;
  private _sampleRateReduction: number = 1;
  private workletReady: boolean = false;

  constructor(audioContext: AudioContext) {
    super(audioContext);

    // Try to use AudioWorklet, fall back to approximation
    this.initWorklet().catch(() => {
      this.initFallback();
    });

    // Initially set up fallback while worklet loads
    this.initFallback();
  }

  /**
   * Initialize AudioWorklet for accurate bitcrushing
   */
  private async initWorklet(): Promise<void> {
    // AudioWorklet processor code as a blob
    const processorCode = `
      class BitcrusherProcessor extends AudioWorkletProcessor {
        static get parameterDescriptors() {
          return [
            { name: 'bits', defaultValue: 16, minValue: 1, maxValue: 16 },
            { name: 'reduction', defaultValue: 1, minValue: 1, maxValue: 32 }
          ];
        }

        constructor() {
          super();
          this.phase = 0;
          this.lastSampleL = 0;
          this.lastSampleR = 0;
        }

        process(inputs, outputs, parameters) {
          const input = inputs[0];
          const output = outputs[0];

          if (!input || !input[0]) return true;

          const bits = parameters.bits[0] || 16;
          const reduction = parameters.reduction[0] || 1;
          const step = Math.pow(0.5, bits);

          for (let channel = 0; channel < output.length; channel++) {
            const inputChannel = input[channel] || input[0];
            const outputChannel = output[channel];

            for (let i = 0; i < outputChannel.length; i++) {
              this.phase += 1;

              if (this.phase >= reduction) {
                this.phase = 0;
                // Quantize to bit depth
                const sample = inputChannel[i];
                const crushed = step * Math.floor(sample / step + 0.5);
                if (channel === 0) this.lastSampleL = crushed;
                else this.lastSampleR = crushed;
              }

              outputChannel[i] = channel === 0 ? this.lastSampleL : this.lastSampleR;
            }
          }

          return true;
        }
      }

      registerProcessor('bitcrusher-processor', BitcrusherProcessor);
    `;

    const blob = new Blob([processorCode], { type: 'application/javascript' });
    const url = URL.createObjectURL(blob);

    try {
      await this.audioContext.audioWorklet.addModule(url);
      this.workletNode = new AudioWorkletNode(this.audioContext, 'bitcrusher-processor');

      // Reconnect wet path with worklet
      if (this.fallbackShaper) {
        // Disconnect fallback
        this.inputNode.disconnect(this.fallbackShaper);
        this.fallbackShaper.disconnect();
        this.fallbackFilter?.disconnect();
      }

      // Connect worklet
      this.connectWetPath(this.workletNode, this.workletNode);
      this.workletReady = true;

      // Apply current settings
      this.setBits(this._bits);
      this.setSampleRateReduction(this._sampleRateReduction);
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  /**
   * Initialize fallback using WaveShaper (less accurate but works everywhere)
   */
  private initFallback(): void {
    // Use waveshaper for bit reduction approximation
    this.fallbackShaper = this.audioContext.createWaveShaper();
    this.fallbackShaper.oversample = 'none';

    // Low-pass filter to simulate sample rate reduction
    this.fallbackFilter = this.audioContext.createBiquadFilter();
    this.fallbackFilter.type = 'lowpass';
    this.fallbackFilter.frequency.value = 20000;
    this.fallbackFilter.Q.value = 0.5;

    this.fallbackShaper.connect(this.fallbackFilter);

    // Set initial curve
    this.updateFallbackCurve();

    // Connect wet path
    if (!this.workletReady) {
      this.connectWetPath(this.fallbackShaper, this.fallbackFilter);
    }
  }

  /**
   * Update fallback waveshaper curve for bit depth simulation
   */
  private updateFallbackCurve(): void {
    if (!this.fallbackShaper) return;

    const bits = this._bits;
    const samples = 65536;
    const curve = new Float32Array(samples);
    const steps = Math.pow(2, bits);

    for (let i = 0; i < samples; i++) {
      const x = (i * 2) / samples - 1;
      // Quantize
      curve[i] = Math.round(x * steps) / steps;
    }

    this.fallbackShaper.curve = curve;

    // Update filter for sample rate reduction effect
    if (this.fallbackFilter) {
      // Lower cutoff simulates lower sample rate
      const nyquist = 20000 / this._sampleRateReduction;
      this.fallbackFilter.frequency.value = Math.max(500, Math.min(20000, nyquist));
    }
  }

  /**
   * Set bit depth (1-16 bits)
   */
  setBits(bits: number): void {
    this._bits = Math.max(1, Math.min(16, Math.round(bits)));

    if (this.workletNode && this.workletReady) {
      const param = this.workletNode.parameters.get('bits');
      if (param) {
        this.setParamSmooth(param, this._bits);
      }
    } else {
      this.updateFallbackCurve();
    }
  }

  /**
   * Set sample rate reduction factor (1 = normal, 32 = very crushed)
   */
  setSampleRateReduction(reduction: number): void {
    this._sampleRateReduction = Math.max(1, Math.min(32, reduction));

    if (this.workletNode && this.workletReady) {
      const param = this.workletNode.parameters.get('reduction');
      if (param) {
        this.setParamSmooth(param, this._sampleRateReduction);
      }
    } else {
      this.updateFallbackCurve();
    }
  }

  /**
   * Update all parameters from state
   */
  updateFromState(state: BitcrusherState): void {
    this.enabled = state.enabled;
    this.setBits(state.bits);
    this.setSampleRateReduction(state.sampleRateReduction);
    this.mix = state.mix;
  }

  dispose(): void {
    super.dispose();
    this.workletNode?.disconnect();
    this.fallbackShaper?.disconnect();
    this.fallbackFilter?.disconnect();
  }
}
