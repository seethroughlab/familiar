import { registerEngineFactory } from '@familiar/frontend/src/player/audio/createEngine';
import { registerNativeEffectsSync } from '@familiar/frontend/src/stores/audioEffectsStore';
import { registerPreferencesProvider } from '@familiar/frontend/src/api/base';
import { createLogger } from '@familiar/frontend/src/utils/logger';
import { renderApp } from '@familiar/frontend/src/renderApp';
import { CapacitorEngine } from './CapacitorEngine';
import { FamiliarAudio } from './plugins/familiarAudio';
import type { AudioEffectsState } from '@familiar/frontend/src/stores/audioEffectsStore';

const log = createLogger('App');

// Build timestamp injected by Vite at build time
declare const __BUILD_TIME__: string;
console.log(`[App] Build: ${typeof __BUILD_TIME__ !== 'undefined' ? __BUILD_TIME__ : 'dev'}`);

// Register Capacitor audio engine
registerEngineFactory(() => new CapacitorEngine());

// Register Capacitor Preferences provider for API origin persistence
import('@capacitor/preferences').then(({ Preferences }) => {
  registerPreferencesProvider({
    get: async (key: string) => {
      const { value } = await Preferences.get({ key });
      return value;
    },
    set: async (key: string, value: string) => {
      await Preferences.set({ key, value });
    },
  });
}).catch(() => {
  log.warn('Capacitor Preferences not available');
});

// Register native effects sync — push state changes to AVAudioEngine
registerNativeEffectsSync((state: AudioEffectsState) => {
  const bypassed = !state.masterEnabled;
  FamiliarAudio.setMasterBypass({ bypassed });

  if (!bypassed) {
    FamiliarAudio.setEQ({
      lowGain: state.eq.lowGain,
      midGain: state.eq.midGain,
      highGain: state.eq.highGain,
      enabled: state.eq.enabled,
    });

    FamiliarAudio.setCompressor({
      threshold: state.compressor.threshold,
      ratio: state.compressor.ratio,
      attack: state.compressor.attack,
      release: state.compressor.release,
      knee: state.compressor.knee,
      makeupGain: state.compressor.makeupGain,
      enabled: state.compressor.enabled,
    });

    FamiliarAudio.setReverb({
      preset: state.reverb.preset,
      wetDryMix: state.reverb.mix,
      enabled: state.reverb.enabled,
      preDelay: state.reverb.preDelay,
    });

    FamiliarAudio.setDelay({
      time: state.delay.time,
      feedback: state.delay.feedback,
      wetDryMix: state.delay.mix,
      enabled: state.delay.enabled,
      pingPong: state.delay.pingPong,
    });

    FamiliarAudio.setFilter({
      highpassFreq: state.filter.highpassFreq,
      lowpassFreq: state.filter.lowpassFreq,
      highpassQ: state.filter.highpassQ,
      lowpassQ: state.filter.lowpassQ,
      enabled: state.filter.enabled,
    });

    FamiliarAudio.setDistortion({
      preset: state.saturation.type,
      wetDryMix: state.saturation.mix,
      enabled: state.saturation.enabled,
      drive: state.saturation.drive,
    });

    FamiliarAudio.setChorus({
      rate: state.chorus.rate,
      depth: state.chorus.depth,
      voices: state.chorus.voices,
      mix: state.chorus.mix,
      enabled: state.chorus.enabled,
    });

    FamiliarAudio.setStereoWidth({
      width: state.stereoWidth.width,
      enabled: state.stereoWidth.enabled,
    });

    FamiliarAudio.setTremolo({
      rate: state.tremolo.rate,
      depth: state.tremolo.depth,
      shape: state.tremolo.shape,
      enabled: state.tremolo.enabled,
    });

    FamiliarAudio.setBitcrusher({
      bits: state.bitcrusher.bits,
      sampleRateReduction: state.bitcrusher.sampleRateReduction,
      mix: state.bitcrusher.mix,
      enabled: state.bitcrusher.enabled,
    });
  }
});

// Global handler for unhandled promise rejections
window.addEventListener('unhandledrejection', (event) => {
  log.error('Unhandled Promise Rejection:', event.reason);
  event.preventDefault();
});

// Render the app
renderApp();
