import '@familiar/frontend/src/index.css';
import { registerEngineFactory } from '@familiar/frontend/src/player/audio/createEngine';
import { registerPreferencesProvider } from '@familiar/frontend/src/api/base';
import { createLogger } from '@familiar/frontend/src/utils/logger';
import { renderApp } from '@familiar/frontend/src/renderApp';
import { CapacitorEngine } from './CapacitorEngine';

const log = createLogger('App');

// Build timestamp injected by Vite at build time
declare const __BUILD_TIME__: string;
console.log(`[App] Build: ${typeof __BUILD_TIME__ !== 'undefined' ? __BUILD_TIME__ : 'dev'}`);

// Feature flag rollout gate for native engine hardening.
// localStorage.native_audio_v2 = "0" disables v2 behavior.
const nativeAudioV2Enabled = localStorage.getItem('native_audio_v2') !== '0';
if (!nativeAudioV2Enabled) {
  log.warn('native_audio_v2 disabled; running compatibility mode');
}

// Register Capacitor audio engine
registerEngineFactory(() => new CapacitorEngine());

// Register ambient synth bridge (deferred — must not block boot)
import { registerAmbientSynthBridge } from '@familiar/frontend/src/player/ambient/ambientSynthBridge';
import('./CapacitorAmbientSynthAdapter').then(({ CapacitorAmbientSynthAdapter }) => {
  registerAmbientSynthBridge(new CapacitorAmbientSynthAdapter());
}).catch(() => {
  log.warn('Ambient synth bridge not available');
});

// Register Capacitor Filesystem provider for native track storage
import { registerFilesystemProvider } from '@familiar/frontend/src/services/offlineService';
import('@capacitor/filesystem').then(({ Filesystem }) => {
  registerFilesystemProvider({
    writeFile: (options) => Filesystem.writeFile(options as Parameters<typeof Filesystem.writeFile>[0]).then(() => {}),
    deleteFile: (options) => Filesystem.deleteFile(options as Parameters<typeof Filesystem.deleteFile>[0]),
    getUri: (options) => Filesystem.getUri(options as Parameters<typeof Filesystem.getUri>[0]),
  });
}).catch(() => {
  log.warn('Capacitor Filesystem not available');
});

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

// Global handler for unhandled promise rejections
window.addEventListener('unhandledrejection', (event) => {
  log.error('Unhandled Promise Rejection:', event.reason);
  event.preventDefault();
});

// Render the app
renderApp();
