import { create } from 'zustand';
import { persist } from 'zustand/middleware';

// ============================================================================
// Types for each effect
// ============================================================================

export interface EQState {
  enabled: boolean;
  lowGain: number;    // -12 to +12 dB
  midGain: number;    // -12 to +12 dB
  highGain: number;   // -12 to +12 dB
  lowFreq: number;    // Hz (fixed at 250)
  highFreq: number;   // Hz (fixed at 4000)
}

export interface CompressorState {
  enabled: boolean;
  threshold: number;  // -60 to 0 dB
  ratio: number;      // 1 to 20
  attack: number;     // 0 to 1 seconds
  release: number;    // 0 to 1 seconds
  knee: number;       // 0 to 40 dB
  makeupGain: number; // 0 to 12 dB
}

export type ReverbPreset = 'small-room' | 'medium-room' | 'large-hall' | 'plate' | 'cathedral';

export interface ReverbState {
  enabled: boolean;
  preset: ReverbPreset;
  mix: number;        // 0 to 1 (wet/dry)
  preDelay: number;   // 0 to 100 ms
}

export interface DelayState {
  enabled: boolean;
  time: number;       // 0 to 2 seconds
  feedback: number;   // 0 to 0.9
  mix: number;        // 0 to 1
  pingPong: boolean;
}

export interface FilterState {
  enabled: boolean;
  highpassFreq: number;  // 20 to 2000 Hz (0 = off)
  lowpassFreq: number;   // 1000 to 20000 Hz (20000 = off)
  highpassQ: number;     // 0.1 to 10
  lowpassQ: number;      // 0.1 to 10
}

export interface StereoWidthState {
  enabled: boolean;
  width: number;         // 0 = mono, 1 = normal, 2 = extra wide
}

export interface SaturationState {
  enabled: boolean;
  drive: number;         // 1 to 5
  type: 'warm' | 'tape' | 'hard';
  mix: number;           // 0 to 1
}

export interface BitcrusherState {
  enabled: boolean;
  bits: number;          // 1 to 16
  sampleRateReduction: number; // 1 to 32
  mix: number;           // 0 to 1
}

export interface ChorusState {
  enabled: boolean;
  rate: number;          // 0.1 to 5 Hz
  depth: number;         // 0 to 10 ms
  voices: number;        // 2 or 3
  mix: number;           // 0 to 1
}

export interface TremoloState {
  enabled: boolean;
  rate: number;          // 0.5 to 20 Hz
  depth: number;         // 0 to 1
  shape: 'sine' | 'triangle' | 'square';
}

export interface EffectsPreset {
  name: string;
  eq: Omit<EQState, 'lowFreq' | 'highFreq'>;
  compressor: CompressorState;
  reverb: ReverbState;
  delay: DelayState;
  filter: FilterState;
  stereoWidth?: StereoWidthState;
  saturation?: SaturationState;
  bitcrusher?: BitcrusherState;
  chorus?: ChorusState;
  tremolo?: TremoloState;
}

// ============================================================================
// Store interface
// ============================================================================

interface AudioEffectsState {
  // Master enable
  masterEnabled: boolean;

  // Individual effects
  eq: EQState;
  compressor: CompressorState;
  reverb: ReverbState;
  delay: DelayState;
  filter: FilterState;
  stereoWidth: StereoWidthState;
  saturation: SaturationState;
  bitcrusher: BitcrusherState;
  chorus: ChorusState;
  tremolo: TremoloState;

  // Saved presets
  presets: EffectsPreset[];
  activePresetName: string | null;

  // Actions
  setMasterEnabled: (enabled: boolean) => void;

  // EQ actions
  setEQEnabled: (enabled: boolean) => void;
  setEQLowGain: (gain: number) => void;
  setEQMidGain: (gain: number) => void;
  setEQHighGain: (gain: number) => void;

  // Compressor actions
  setCompressorEnabled: (enabled: boolean) => void;
  setCompressorThreshold: (threshold: number) => void;
  setCompressorRatio: (ratio: number) => void;
  setCompressorAttack: (attack: number) => void;
  setCompressorRelease: (release: number) => void;
  setCompressorKnee: (knee: number) => void;
  setCompressorMakeupGain: (gain: number) => void;

  // Reverb actions
  setReverbEnabled: (enabled: boolean) => void;
  setReverbPreset: (preset: ReverbPreset) => void;
  setReverbMix: (mix: number) => void;
  setReverbPreDelay: (preDelay: number) => void;

  // Delay actions
  setDelayEnabled: (enabled: boolean) => void;
  setDelayTime: (time: number) => void;
  setDelayFeedback: (feedback: number) => void;
  setDelayMix: (mix: number) => void;
  setDelayPingPong: (pingPong: boolean) => void;

  // Filter actions
  setFilterEnabled: (enabled: boolean) => void;
  setFilterHighpassFreq: (freq: number) => void;
  setFilterLowpassFreq: (freq: number) => void;
  setFilterHighpassQ: (q: number) => void;
  setFilterLowpassQ: (q: number) => void;

  // Stereo Width actions
  setStereoWidthEnabled: (enabled: boolean) => void;
  setStereoWidth: (width: number) => void;

  // Saturation actions
  setSaturationEnabled: (enabled: boolean) => void;
  setSaturationDrive: (drive: number) => void;
  setSaturationType: (type: 'warm' | 'tape' | 'hard') => void;
  setSaturationMix: (mix: number) => void;

  // Bitcrusher actions
  setBitcrusherEnabled: (enabled: boolean) => void;
  setBitcrusherBits: (bits: number) => void;
  setBitcrusherSampleRateReduction: (reduction: number) => void;
  setBitcrusherMix: (mix: number) => void;

  // Chorus actions
  setChorusEnabled: (enabled: boolean) => void;
  setChorusRate: (rate: number) => void;
  setChorusDepth: (depth: number) => void;
  setChorusVoices: (voices: number) => void;
  setChorusMix: (mix: number) => void;

  // Tremolo actions
  setTremoloEnabled: (enabled: boolean) => void;
  setTremoloRate: (rate: number) => void;
  setTremoloDepth: (depth: number) => void;
  setTremoloShape: (shape: 'sine' | 'triangle' | 'square') => void;

  // Preset actions
  savePreset: (name: string) => void;
  loadPreset: (name: string) => void;
  deletePreset: (name: string) => void;
  resetToDefaults: () => void;
}

// ============================================================================
// Default values
// ============================================================================

const defaultEQ: EQState = {
  enabled: false,
  lowGain: 0,
  midGain: 0,
  highGain: 0,
  lowFreq: 250,
  highFreq: 4000,
};

const defaultCompressor: CompressorState = {
  enabled: false,
  threshold: -24,
  ratio: 4,
  attack: 0.003,
  release: 0.25,
  knee: 30,
  makeupGain: 0,
};

const defaultReverb: ReverbState = {
  enabled: false,
  preset: 'medium-room',
  mix: 0.3,
  preDelay: 10,
};

const defaultDelay: DelayState = {
  enabled: false,
  time: 0.3,
  feedback: 0.3,
  mix: 0.3,
  pingPong: false,
};

const defaultFilter: FilterState = {
  enabled: false,
  highpassFreq: 20,
  lowpassFreq: 20000,
  highpassQ: 0.7,
  lowpassQ: 0.7,
};

const defaultStereoWidth: StereoWidthState = {
  enabled: false,
  width: 1, // Normal stereo
};

const defaultSaturation: SaturationState = {
  enabled: false,
  drive: 1.5,
  type: 'warm',
  mix: 1,
};

const defaultBitcrusher: BitcrusherState = {
  enabled: false,
  bits: 8,
  sampleRateReduction: 4,
  mix: 1,
};

const defaultChorus: ChorusState = {
  enabled: false,
  rate: 1.5,
  depth: 3,
  voices: 2,
  mix: 0.5,
};

const defaultTremolo: TremoloState = {
  enabled: false,
  rate: 4,
  depth: 0.5,
  shape: 'sine',
};

// Built-in presets
const builtInPresets: EffectsPreset[] = [
  {
    name: 'Warm Vinyl',
    eq: { enabled: true, lowGain: 2, midGain: -1, highGain: -3 },
    compressor: { ...defaultCompressor, enabled: false },
    reverb: { enabled: true, preset: 'small-room', mix: 0.15, preDelay: 5 },
    delay: { ...defaultDelay, enabled: false },
    filter: { enabled: true, highpassFreq: 30, lowpassFreq: 12000, highpassQ: 0.5, lowpassQ: 0.5 },
    saturation: { enabled: true, drive: 1.5, type: 'tape', mix: 0.4 },
  },
  {
    name: 'Live Concert',
    eq: { enabled: true, lowGain: 1, midGain: 0, highGain: 2 },
    compressor: { ...defaultCompressor, enabled: true, threshold: -18, ratio: 3 },
    reverb: { enabled: true, preset: 'large-hall', mix: 0.35, preDelay: 20 },
    delay: { ...defaultDelay, enabled: false },
    filter: { ...defaultFilter, enabled: false },
    stereoWidth: { enabled: true, width: 1.3 },
  },
  {
    name: 'Studio Polish',
    eq: { enabled: true, lowGain: 0, midGain: 1, highGain: 1 },
    compressor: { enabled: true, threshold: -20, ratio: 4, attack: 0.005, release: 0.2, knee: 20, makeupGain: 2 },
    reverb: { enabled: true, preset: 'plate', mix: 0.2, preDelay: 0 },
    delay: { ...defaultDelay, enabled: false },
    filter: { ...defaultFilter, enabled: false },
    saturation: { enabled: true, drive: 1.3, type: 'warm', mix: 0.3 },
  },
  {
    name: 'Bass Boost',
    eq: { enabled: true, lowGain: 6, midGain: 0, highGain: 0 },
    compressor: { enabled: true, threshold: -15, ratio: 6, attack: 0.01, release: 0.15, knee: 10, makeupGain: 0 },
    reverb: { ...defaultReverb, enabled: false },
    delay: { ...defaultDelay, enabled: false },
    filter: { ...defaultFilter, enabled: false },
  },
  {
    name: 'Dreamy',
    eq: { enabled: true, lowGain: -2, midGain: 0, highGain: 3 },
    compressor: { ...defaultCompressor, enabled: false },
    reverb: { enabled: true, preset: 'cathedral', mix: 0.5, preDelay: 30 },
    delay: { enabled: true, time: 0.4, feedback: 0.4, mix: 0.25, pingPong: true },
    filter: { enabled: true, highpassFreq: 80, lowpassFreq: 16000, highpassQ: 0.5, lowpassQ: 0.7 },
    chorus: { enabled: true, rate: 0.8, depth: 4, voices: 2, mix: 0.3 },
    stereoWidth: { enabled: true, width: 1.5 },
  },
  {
    name: 'Lo-Fi',
    eq: { enabled: true, lowGain: 3, midGain: -2, highGain: -4 },
    compressor: { enabled: true, threshold: -20, ratio: 4, attack: 0.02, release: 0.3, knee: 20, makeupGain: 2 },
    reverb: { enabled: true, preset: 'small-room', mix: 0.25, preDelay: 10 },
    delay: { enabled: true, time: 0.15, feedback: 0.2, mix: 0.15, pingPong: false },
    filter: { enabled: true, highpassFreq: 60, lowpassFreq: 8000, highpassQ: 0.5, lowpassQ: 0.7 },
  },
  {
    name: 'Late Night',
    eq: { enabled: true, lowGain: 1, midGain: 2, highGain: -4 },
    compressor: { enabled: true, threshold: -25, ratio: 2.5, attack: 0.01, release: 0.4, knee: 30, makeupGain: 1 },
    reverb: { enabled: true, preset: 'medium-room', mix: 0.2, preDelay: 15 },
    delay: { ...defaultDelay, enabled: false },
    filter: { enabled: true, highpassFreq: 40, lowpassFreq: 14000, highpassQ: 0.5, lowpassQ: 0.5 },
  },
  {
    name: 'Club',
    eq: { enabled: true, lowGain: 8, midGain: -2, highGain: 3 },
    compressor: { enabled: true, threshold: -12, ratio: 8, attack: 0.002, release: 0.1, knee: 5, makeupGain: 3 },
    reverb: { ...defaultReverb, enabled: false },
    delay: { ...defaultDelay, enabled: false },
    filter: { enabled: true, highpassFreq: 30, lowpassFreq: 18000, highpassQ: 1, lowpassQ: 0.7 },
  },
  {
    name: 'Telephone',
    eq: { enabled: true, lowGain: -6, midGain: 4, highGain: -6 },
    compressor: { enabled: true, threshold: -15, ratio: 6, attack: 0.005, release: 0.15, knee: 10, makeupGain: 4 },
    reverb: { ...defaultReverb, enabled: false },
    delay: { ...defaultDelay, enabled: false },
    filter: { enabled: true, highpassFreq: 400, lowpassFreq: 3500, highpassQ: 1.5, lowpassQ: 1.5 },
  },
  {
    name: 'Underwater',
    eq: { enabled: true, lowGain: 4, midGain: -3, highGain: -8 },
    compressor: { ...defaultCompressor, enabled: false },
    reverb: { enabled: true, preset: 'cathedral', mix: 0.6, preDelay: 40 },
    delay: { enabled: true, time: 0.8, feedback: 0.5, mix: 0.3, pingPong: true },
    filter: { enabled: true, highpassFreq: 20, lowpassFreq: 2500, highpassQ: 0.5, lowpassQ: 2 },
  },
  {
    name: '80s Gated',
    eq: { enabled: true, lowGain: 2, midGain: 3, highGain: 5 },
    compressor: { enabled: true, threshold: -15, ratio: 10, attack: 0.001, release: 0.05, knee: 0, makeupGain: 4 },
    reverb: { enabled: true, preset: 'plate', mix: 0.35, preDelay: 0 },
    delay: { ...defaultDelay, enabled: false },
    filter: { ...defaultFilter, enabled: false },
  },
  {
    name: 'Spoken Word',
    eq: { enabled: true, lowGain: -2, midGain: 4, highGain: 2 },
    compressor: { enabled: true, threshold: -18, ratio: 6, attack: 0.003, release: 0.2, knee: 15, makeupGain: 3 },
    reverb: { ...defaultReverb, enabled: false },
    delay: { ...defaultDelay, enabled: false },
    filter: { enabled: true, highpassFreq: 80, lowpassFreq: 16000, highpassQ: 0.7, lowpassQ: 0.5 },
  },
  // Presets using new effects
  {
    name: 'Wide Stereo',
    eq: { enabled: true, lowGain: 0, midGain: 0, highGain: 2 },
    compressor: { ...defaultCompressor, enabled: false },
    reverb: { enabled: true, preset: 'small-room', mix: 0.15, preDelay: 5 },
    delay: { ...defaultDelay, enabled: false },
    filter: { ...defaultFilter, enabled: false },
    stereoWidth: { enabled: true, width: 1.6 },
  },
  {
    name: 'Analog Warmth',
    eq: { enabled: true, lowGain: 2, midGain: 0, highGain: -1 },
    compressor: { enabled: true, threshold: -20, ratio: 3, attack: 0.01, release: 0.3, knee: 20, makeupGain: 1 },
    reverb: { ...defaultReverb, enabled: false },
    delay: { ...defaultDelay, enabled: false },
    filter: { enabled: true, highpassFreq: 30, lowpassFreq: 16000, highpassQ: 0.5, lowpassQ: 0.5 },
    saturation: { enabled: true, drive: 2, type: 'tape', mix: 0.7 },
  },
  {
    name: 'Retro 8-Bit',
    eq: { enabled: true, lowGain: -2, midGain: 2, highGain: -4 },
    compressor: { ...defaultCompressor, enabled: false },
    reverb: { ...defaultReverb, enabled: false },
    delay: { ...defaultDelay, enabled: false },
    filter: { enabled: true, highpassFreq: 100, lowpassFreq: 8000, highpassQ: 0.7, lowpassQ: 1 },
    bitcrusher: { enabled: true, bits: 8, sampleRateReduction: 4, mix: 0.8 },
  },
  {
    name: 'Thick & Lush',
    eq: { enabled: true, lowGain: 1, midGain: 1, highGain: 2 },
    compressor: { ...defaultCompressor, enabled: false },
    reverb: { enabled: true, preset: 'medium-room', mix: 0.25, preDelay: 10 },
    delay: { ...defaultDelay, enabled: false },
    filter: { ...defaultFilter, enabled: false },
    chorus: { enabled: true, rate: 1, depth: 4, voices: 3, mix: 0.4 },
    stereoWidth: { enabled: true, width: 1.3 },
  },
  {
    name: 'Vintage Amp',
    eq: { enabled: true, lowGain: 2, midGain: 3, highGain: 1 },
    compressor: { enabled: true, threshold: -15, ratio: 4, attack: 0.005, release: 0.2, knee: 15, makeupGain: 2 },
    reverb: { enabled: true, preset: 'small-room', mix: 0.2, preDelay: 5 },
    delay: { ...defaultDelay, enabled: false },
    filter: { ...defaultFilter, enabled: false },
    saturation: { enabled: true, drive: 2.5, type: 'warm', mix: 0.6 },
    tremolo: { enabled: true, rate: 5, depth: 0.3, shape: 'sine' },
  },
  {
    name: 'Psychedelic',
    eq: { enabled: true, lowGain: 2, midGain: -1, highGain: 4 },
    compressor: { ...defaultCompressor, enabled: false },
    reverb: { enabled: true, preset: 'large-hall', mix: 0.4, preDelay: 25 },
    delay: { enabled: true, time: 0.375, feedback: 0.5, mix: 0.3, pingPong: true },
    filter: { ...defaultFilter, enabled: false },
    chorus: { enabled: true, rate: 0.5, depth: 6, voices: 3, mix: 0.35 },
    stereoWidth: { enabled: true, width: 1.8 },
  },
  {
    name: 'Synthwave',
    eq: { enabled: true, lowGain: 4, midGain: -2, highGain: 3 },
    compressor: { enabled: true, threshold: -15, ratio: 5, attack: 0.003, release: 0.15, knee: 10, makeupGain: 2 },
    reverb: { enabled: true, preset: 'plate', mix: 0.3, preDelay: 10 },
    delay: { enabled: true, time: 0.25, feedback: 0.35, mix: 0.2, pingPong: true },
    filter: { ...defaultFilter, enabled: false },
    chorus: { enabled: true, rate: 2, depth: 3, voices: 2, mix: 0.25 },
    stereoWidth: { enabled: true, width: 1.4 },
  },
  {
    name: 'Broken Radio',
    eq: { enabled: true, lowGain: -8, midGain: 6, highGain: -6 },
    compressor: { enabled: true, threshold: -10, ratio: 10, attack: 0.001, release: 0.1, knee: 0, makeupGain: 6 },
    reverb: { ...defaultReverb, enabled: false },
    delay: { ...defaultDelay, enabled: false },
    filter: { enabled: true, highpassFreq: 500, lowpassFreq: 4000, highpassQ: 2, lowpassQ: 2 },
    bitcrusher: { enabled: true, bits: 6, sampleRateReduction: 8, mix: 0.6 },
    saturation: { enabled: true, drive: 3, type: 'hard', mix: 0.5 },
  },
];

// ============================================================================
// Store
// ============================================================================

export const useAudioEffectsStore = create<AudioEffectsState>()(
  persist(
    (set, get) => ({
      masterEnabled: false,
      eq: defaultEQ,
      compressor: defaultCompressor,
      reverb: defaultReverb,
      delay: defaultDelay,
      filter: defaultFilter,
      stereoWidth: defaultStereoWidth,
      saturation: defaultSaturation,
      bitcrusher: defaultBitcrusher,
      chorus: defaultChorus,
      tremolo: defaultTremolo,
      presets: builtInPresets,
      activePresetName: null,

      setMasterEnabled: (enabled) => set({ masterEnabled: enabled }),

      // EQ
      setEQEnabled: (enabled) =>
        set((state) => ({
          eq: { ...state.eq, enabled },
          activePresetName: null,
        })),
      setEQLowGain: (gain) =>
        set((state) => ({
          eq: { ...state.eq, lowGain: Math.max(-12, Math.min(12, gain)) },
          activePresetName: null,
        })),
      setEQMidGain: (gain) =>
        set((state) => ({
          eq: { ...state.eq, midGain: Math.max(-12, Math.min(12, gain)) },
          activePresetName: null,
        })),
      setEQHighGain: (gain) =>
        set((state) => ({
          eq: { ...state.eq, highGain: Math.max(-12, Math.min(12, gain)) },
          activePresetName: null,
        })),

      // Compressor
      setCompressorEnabled: (enabled) =>
        set((state) => ({
          compressor: { ...state.compressor, enabled },
          activePresetName: null,
        })),
      setCompressorThreshold: (threshold) =>
        set((state) => ({
          compressor: { ...state.compressor, threshold: Math.max(-60, Math.min(0, threshold)) },
          activePresetName: null,
        })),
      setCompressorRatio: (ratio) =>
        set((state) => ({
          compressor: { ...state.compressor, ratio: Math.max(1, Math.min(20, ratio)) },
          activePresetName: null,
        })),
      setCompressorAttack: (attack) =>
        set((state) => ({
          compressor: { ...state.compressor, attack: Math.max(0, Math.min(1, attack)) },
          activePresetName: null,
        })),
      setCompressorRelease: (release) =>
        set((state) => ({
          compressor: { ...state.compressor, release: Math.max(0, Math.min(1, release)) },
          activePresetName: null,
        })),
      setCompressorKnee: (knee) =>
        set((state) => ({
          compressor: { ...state.compressor, knee: Math.max(0, Math.min(40, knee)) },
          activePresetName: null,
        })),
      setCompressorMakeupGain: (gain) =>
        set((state) => ({
          compressor: { ...state.compressor, makeupGain: Math.max(0, Math.min(12, gain)) },
          activePresetName: null,
        })),

      // Reverb
      setReverbEnabled: (enabled) =>
        set((state) => ({
          reverb: { ...state.reverb, enabled },
          activePresetName: null,
        })),
      setReverbPreset: (preset) =>
        set((state) => ({
          reverb: { ...state.reverb, preset },
          activePresetName: null,
        })),
      setReverbMix: (mix) =>
        set((state) => ({
          reverb: { ...state.reverb, mix: Math.max(0, Math.min(1, mix)) },
          activePresetName: null,
        })),
      setReverbPreDelay: (preDelay) =>
        set((state) => ({
          reverb: { ...state.reverb, preDelay: Math.max(0, Math.min(100, preDelay)) },
          activePresetName: null,
        })),

      // Delay
      setDelayEnabled: (enabled) =>
        set((state) => ({
          delay: { ...state.delay, enabled },
          activePresetName: null,
        })),
      setDelayTime: (time) =>
        set((state) => ({
          delay: { ...state.delay, time: Math.max(0, Math.min(2, time)) },
          activePresetName: null,
        })),
      setDelayFeedback: (feedback) =>
        set((state) => ({
          delay: { ...state.delay, feedback: Math.max(0, Math.min(0.9, feedback)) },
          activePresetName: null,
        })),
      setDelayMix: (mix) =>
        set((state) => ({
          delay: { ...state.delay, mix: Math.max(0, Math.min(1, mix)) },
          activePresetName: null,
        })),
      setDelayPingPong: (pingPong) =>
        set((state) => ({
          delay: { ...state.delay, pingPong },
          activePresetName: null,
        })),

      // Filter
      setFilterEnabled: (enabled) =>
        set((state) => ({
          filter: { ...state.filter, enabled },
          activePresetName: null,
        })),
      setFilterHighpassFreq: (freq) =>
        set((state) => ({
          filter: { ...state.filter, highpassFreq: Math.max(20, Math.min(2000, freq)) },
          activePresetName: null,
        })),
      setFilterLowpassFreq: (freq) =>
        set((state) => ({
          filter: { ...state.filter, lowpassFreq: Math.max(1000, Math.min(20000, freq)) },
          activePresetName: null,
        })),
      setFilterHighpassQ: (q) =>
        set((state) => ({
          filter: { ...state.filter, highpassQ: Math.max(0.1, Math.min(10, q)) },
          activePresetName: null,
        })),
      setFilterLowpassQ: (q) =>
        set((state) => ({
          filter: { ...state.filter, lowpassQ: Math.max(0.1, Math.min(10, q)) },
          activePresetName: null,
        })),

      // Stereo Width
      setStereoWidthEnabled: (enabled) =>
        set((state) => ({
          stereoWidth: { ...state.stereoWidth, enabled },
          activePresetName: null,
        })),
      setStereoWidth: (width) =>
        set((state) => ({
          stereoWidth: { ...state.stereoWidth, width: Math.max(0, Math.min(2, width)) },
          activePresetName: null,
        })),

      // Saturation
      setSaturationEnabled: (enabled) =>
        set((state) => ({
          saturation: { ...state.saturation, enabled },
          activePresetName: null,
        })),
      setSaturationDrive: (drive) =>
        set((state) => ({
          saturation: { ...state.saturation, drive: Math.max(1, Math.min(5, drive)) },
          activePresetName: null,
        })),
      setSaturationType: (type) =>
        set((state) => ({
          saturation: { ...state.saturation, type },
          activePresetName: null,
        })),
      setSaturationMix: (mix) =>
        set((state) => ({
          saturation: { ...state.saturation, mix: Math.max(0, Math.min(1, mix)) },
          activePresetName: null,
        })),

      // Bitcrusher
      setBitcrusherEnabled: (enabled) =>
        set((state) => ({
          bitcrusher: { ...state.bitcrusher, enabled },
          activePresetName: null,
        })),
      setBitcrusherBits: (bits) =>
        set((state) => ({
          bitcrusher: { ...state.bitcrusher, bits: Math.max(1, Math.min(16, Math.round(bits))) },
          activePresetName: null,
        })),
      setBitcrusherSampleRateReduction: (reduction) =>
        set((state) => ({
          bitcrusher: { ...state.bitcrusher, sampleRateReduction: Math.max(1, Math.min(32, reduction)) },
          activePresetName: null,
        })),
      setBitcrusherMix: (mix) =>
        set((state) => ({
          bitcrusher: { ...state.bitcrusher, mix: Math.max(0, Math.min(1, mix)) },
          activePresetName: null,
        })),

      // Chorus
      setChorusEnabled: (enabled) =>
        set((state) => ({
          chorus: { ...state.chorus, enabled },
          activePresetName: null,
        })),
      setChorusRate: (rate) =>
        set((state) => ({
          chorus: { ...state.chorus, rate: Math.max(0.1, Math.min(5, rate)) },
          activePresetName: null,
        })),
      setChorusDepth: (depth) =>
        set((state) => ({
          chorus: { ...state.chorus, depth: Math.max(0, Math.min(10, depth)) },
          activePresetName: null,
        })),
      setChorusVoices: (voices) =>
        set((state) => ({
          chorus: { ...state.chorus, voices: Math.max(2, Math.min(3, Math.round(voices))) },
          activePresetName: null,
        })),
      setChorusMix: (mix) =>
        set((state) => ({
          chorus: { ...state.chorus, mix: Math.max(0, Math.min(1, mix)) },
          activePresetName: null,
        })),

      // Tremolo
      setTremoloEnabled: (enabled) =>
        set((state) => ({
          tremolo: { ...state.tremolo, enabled },
          activePresetName: null,
        })),
      setTremoloRate: (rate) =>
        set((state) => ({
          tremolo: { ...state.tremolo, rate: Math.max(0.5, Math.min(20, rate)) },
          activePresetName: null,
        })),
      setTremoloDepth: (depth) =>
        set((state) => ({
          tremolo: { ...state.tremolo, depth: Math.max(0, Math.min(1, depth)) },
          activePresetName: null,
        })),
      setTremoloShape: (shape) =>
        set((state) => ({
          tremolo: { ...state.tremolo, shape },
          activePresetName: null,
        })),

      // Presets
      savePreset: (name) => {
        const state = get();
        const newPreset: EffectsPreset = {
          name,
          eq: {
            enabled: state.eq.enabled,
            lowGain: state.eq.lowGain,
            midGain: state.eq.midGain,
            highGain: state.eq.highGain,
          },
          compressor: { ...state.compressor },
          reverb: { ...state.reverb },
          delay: { ...state.delay },
          filter: { ...state.filter },
          stereoWidth: { ...state.stereoWidth },
          saturation: { ...state.saturation },
          bitcrusher: { ...state.bitcrusher },
          chorus: { ...state.chorus },
          tremolo: { ...state.tremolo },
        };

        set((state) => ({
          presets: [
            ...state.presets.filter((p) => p.name !== name),
            newPreset,
          ],
          activePresetName: name,
        }));
      },

      loadPreset: (name) => {
        const preset = get().presets.find((p) => p.name === name);
        if (!preset) return;

        set({
          eq: { ...defaultEQ, ...preset.eq },
          compressor: preset.compressor,
          reverb: preset.reverb,
          delay: preset.delay,
          filter: preset.filter,
          stereoWidth: preset.stereoWidth ?? defaultStereoWidth,
          saturation: preset.saturation ?? defaultSaturation,
          bitcrusher: preset.bitcrusher ?? defaultBitcrusher,
          chorus: preset.chorus ?? defaultChorus,
          tremolo: preset.tremolo ?? defaultTremolo,
          activePresetName: name,
          masterEnabled: true, // Enable effects when loading a preset
        });
      },

      deletePreset: (name) => {
        // Don't allow deleting built-in presets
        if (builtInPresets.some((p) => p.name === name)) return;

        set((state) => ({
          presets: state.presets.filter((p) => p.name !== name),
          activePresetName: state.activePresetName === name ? null : state.activePresetName,
        }));
      },

      resetToDefaults: () =>
        set({
          masterEnabled: false,
          eq: defaultEQ,
          compressor: defaultCompressor,
          reverb: defaultReverb,
          delay: defaultDelay,
          filter: defaultFilter,
          stereoWidth: defaultStereoWidth,
          saturation: defaultSaturation,
          bitcrusher: defaultBitcrusher,
          chorus: defaultChorus,
          tremolo: defaultTremolo,
          activePresetName: null,
        }),
    }),
    {
      name: 'familiar-audio-effects',
      // Merge persisted state with current defaults to pick up new built-in presets
      merge: (persistedState, currentState) => {
        const persisted = persistedState as Partial<AudioEffectsState> | undefined;
        if (!persisted) return currentState;

        // Get user's custom presets (those not in built-in list)
        const builtInNames = new Set(builtInPresets.map((p) => p.name));
        const userPresets = (persisted.presets ?? []).filter(
          (p) => !builtInNames.has(p.name)
        );

        // Merge: all current built-in presets + user's custom presets
        const mergedPresets = [...builtInPresets, ...userPresets];

        return {
          ...currentState,
          ...persisted,
          // Always use the latest built-in presets + user presets
          presets: mergedPresets,
          // Ensure new effect states have defaults if not in persisted state
          stereoWidth: persisted.stereoWidth ?? currentState.stereoWidth,
          saturation: persisted.saturation ?? currentState.saturation,
          bitcrusher: persisted.bitcrusher ?? currentState.bitcrusher,
          chorus: persisted.chorus ?? currentState.chorus,
          tremolo: persisted.tremolo ?? currentState.tremolo,
        };
      },
    }
  )
);
