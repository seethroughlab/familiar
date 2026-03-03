import { BaseEffect } from './BaseEffect';
import type { ReverbState, ReverbPreset } from '@familiar/frontend/src/stores/audioEffectsStore';

/**
 * Reverb preset configurations
 */
interface ReverbConfig {
  name: string;
  decay: number;      // Decay time in seconds
  density: number;    // 0-1, affects IR complexity
  dampening: number;  // 0-1, high frequency damping
  size: number;       // Room size multiplier
}

const REVERB_CONFIGS: Record<ReverbPreset, ReverbConfig> = {
  'small-room': { name: 'Small Room', decay: 0.5, density: 0.3, dampening: 0.4, size: 0.3 },
  'medium-room': { name: 'Medium Room', decay: 1.0, density: 0.5, dampening: 0.3, size: 0.5 },
  'large-hall': { name: 'Large Hall', decay: 2.5, density: 0.7, dampening: 0.2, size: 0.8 },
  'plate': { name: 'Plate', decay: 1.5, density: 0.9, dampening: 0.5, size: 0.4 },
  'cathedral': { name: 'Cathedral', decay: 4.0, density: 0.8, dampening: 0.15, size: 1.0 },
};

/**
 * Voss-McCartney pink noise generator.
 * Uses 16 octave generators for full audio spectrum coverage.
 * Produces true pink noise (-3dB/octave rolloff) without bass buildup.
 */
class PinkNoiseGenerator {
  private static readonly NUM_OCTAVES = 16;
  private octaves: number[] = new Array(PinkNoiseGenerator.NUM_OCTAVES).fill(0);
  private counter = 0;
  private runningSum = 0;

  constructor() {
    // Initialize all octaves with random values
    for (let i = 0; i < PinkNoiseGenerator.NUM_OCTAVES; i++) {
      this.octaves[i] = Math.random() * 2 - 1;
      this.runningSum += this.octaves[i];
    }
  }

  next(): number {
    // Find which octave to update by counting trailing zeros
    const lastCounter = this.counter;
    this.counter++;
    const changed = lastCounter ^ this.counter;

    // Update octaves where bits changed from 0 to 1
    for (let i = 0; i < PinkNoiseGenerator.NUM_OCTAVES; i++) {
      if (changed & (1 << i)) {
        this.runningSum -= this.octaves[i];
        this.octaves[i] = Math.random() * 2 - 1;
        this.runningSum += this.octaves[i];
        break; // Only one bit changes per increment
      }
    }

    // Normalize by number of octaves and add white noise for high frequencies
    const white = Math.random() * 2 - 1;
    return (this.runningSum / PinkNoiseGenerator.NUM_OCTAVES + white) * 0.5;
  }
}

/**
 * Convolution reverb effect with algorithmically generated impulse responses.
 */
export class ReverbEffect extends BaseEffect {
  private convolver: ConvolverNode;
  private preDelayNode: DelayNode;
  private currentPreset: ReverbPreset = 'medium-room';
  private irCache: Map<ReverbPreset, AudioBuffer> = new Map();

  constructor(audioContext: AudioContext) {
    super(audioContext);

    // Create nodes
    this.preDelayNode = audioContext.createDelay(0.1);
    this.preDelayNode.delayTime.value = 0.01;

    this.convolver = audioContext.createConvolver();

    // Chain: preDelay -> convolver
    this.preDelayNode.connect(this.convolver);

    // Connect wet path
    this.connectWetPath(this.preDelayNode, this.convolver);

    // Generate initial IR
    this.loadPreset('medium-room');
  }

  /**
   * Generate an impulse response algorithmically with improved quality:
   * - Pink-ish noise (less harsh than white noise)
   * - Gaussian-spread early reflections with stereo decorrelation
   * - Progressive lowpass filtering for natural high-frequency decay
   */
  private generateImpulseResponse(config: ReverbConfig): AudioBuffer {
    const sampleRate = this.audioContext.sampleRate;
    const length = Math.floor(sampleRate * config.decay * 1.5);
    const buffer = this.audioContext.createBuffer(2, length, sampleRate);

    for (let channel = 0; channel < 2; channel++) {
      const channelData = buffer.getChannelData(channel);

      // 1. Generate early reflections with gaussian spread and stereo decorrelation
      const numReflections = 18;
      const stereoOffset = channel === 0 ? 0 : 0.002; // 2ms offset for right channel

      for (let r = 0; r < numReflections; r++) {
        // Exponential spacing: closer together early, spreading out
        const reflectionTime = Math.pow(r + 1, 1.3) * 0.003 * config.size + stereoOffset;
        const reflectionSample = Math.floor(reflectionTime * sampleRate);
        const amplitude = Math.pow(0.85, r) * 0.4; // Exponential decay

        // Gaussian burst instead of single sample (spread over ~5 samples)
        for (let s = -2; s <= 2; s++) {
          const idx = reflectionSample + s;
          if (idx >= 0 && idx < length) {
            const gaussWeight = Math.exp(-s * s / 2);
            channelData[idx] += amplitude * gaussWeight * (Math.random() * 0.4 + 0.8);
          }
        }
      }

      // 2. Generate true pink noise using Voss-McCartney algorithm
      const pinkGen = new PinkNoiseGenerator();

      for (let i = 0; i < length; i++) {
        const t = i / sampleRate;

        // Basic exponential decay envelope
        const decay = Math.exp(-3 * t / config.decay);

        // Generate pink noise
        const noise = pinkGen.next() * config.density;

        // Add diffuse reverb tail (late reflections)
        channelData[i] += noise * decay;
      }

      // 3. Apply progressive lowpass filter for natural high-frequency dampening
      let prevSample = 0;
      const baseCutoff = 1 - config.dampening * 0.8; // 0.2 to 1.0

      for (let i = 0; i < length; i++) {
        const progress = i / length;
        // Cutoff decreases over time, filtering more highs as reverb decays
        const cutoff = baseCutoff * (1 - progress * config.dampening);
        const filtered = cutoff * channelData[i] + (1 - cutoff) * prevSample;
        prevSample = filtered;
        channelData[i] = filtered;
      }

      // 4. Normalize
      let maxVal = 0;
      for (let i = 0; i < length; i++) {
        maxVal = Math.max(maxVal, Math.abs(channelData[i]));
      }
      if (maxVal > 0) {
        const normFactor = 0.5 / maxVal;
        for (let i = 0; i < length; i++) {
          channelData[i] *= normFactor;
        }
      }
    }

    return buffer;
  }

  /**
   * Load a reverb preset
   */
  async loadPreset(preset: ReverbPreset): Promise<void> {
    this.currentPreset = preset;
    const config = REVERB_CONFIGS[preset];

    // Check cache first
    let ir = this.irCache.get(preset);

    if (!ir) {
      // Generate new IR
      ir = this.generateImpulseResponse(config);
      this.irCache.set(preset, ir);
    }

    this.convolver.buffer = ir;

    // Auto pre-delay based on room size (0-30ms)
    const autoPreDelay = config.size * 0.03;
    this.setParamSmooth(this.preDelayNode.delayTime, autoPreDelay);
  }

  /**
   * Set pre-delay time in milliseconds (0 to 100)
   */
  setPreDelay(ms: number): void {
    const seconds = Math.max(0, Math.min(100, ms)) / 1000;
    this.setParamSmooth(this.preDelayNode.delayTime, seconds);
  }

  /**
   * Update all parameters from state
   */
  async updateFromState(state: ReverbState): Promise<void> {
    this.enabled = state.enabled;
    this.mix = state.mix;

    // Load preset first (which sets auto pre-delay), then apply user's pre-delay
    if (state.preset !== this.currentPreset) {
      await this.loadPreset(state.preset);
    }
    this.setPreDelay(state.preDelay);
  }

  /**
   * Get current preset name for display
   */
  getPresetName(): string {
    return REVERB_CONFIGS[this.currentPreset].name;
  }

  dispose(): void {
    super.dispose();
    this.preDelayNode.disconnect();
    this.convolver.disconnect();
    this.irCache.clear();
  }
}
