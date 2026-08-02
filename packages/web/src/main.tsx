import '@familiar/frontend/src/index.css';
import { registerEngineFactory } from '@familiar/frontend/src/player/audio/createEngine';
import { createLogger } from '@familiar/frontend/src/utils/logger';
import { renderApp } from '@familiar/frontend/src/renderApp';
import { WebAudioEngine } from './WebAudioEngine';

const log = createLogger('App');

// Build timestamp injected by Vite at build time
declare const __BUILD_TIME__: string;
console.log(`[App] Build: ${typeof __BUILD_TIME__ !== 'undefined' ? __BUILD_TIME__ : 'dev'}`);

// Register Web Audio engine
// Capabilities are declared here as well as on the engine, so that asking what audio can do never
// builds an audio graph — see `engineInstance.ts`. They are checked against the real engine the
// first time one is constructed.
registerEngineFactory(() => new WebAudioEngine(), {
  crossfade: true,
  visualizer: true,
  effects: 'web',
});

// Global handler for unhandled promise rejections
window.addEventListener('unhandledrejection', (event) => {
  log.error('Unhandled Promise Rejection:', event.reason);
  event.preventDefault();

  import('@familiar/frontend/src/stores/toastStore').then(({ showError }) => {
    const reason = event.reason;
    const isNetworkError =
      reason?.message?.includes('fetch') ||
      reason?.message?.includes('network') ||
      reason?.code === 'ERR_NETWORK';

    if (!isNetworkError) {
      showError('An unexpected error occurred', {
        description: 'Some features may not work correctly. Try refreshing the page.',
      });
    }
  }).catch(() => {
    log.error('Failed to show error toast');
  });
});

// Service worker update check (web only — no SW in native apps)
if ('serviceWorker' in navigator) {
  // With registerType: 'autoUpdate' a new SW activates in the background, but an
  // already-open page (especially a docked PWA) keeps running the old in-memory
  // bundle until it's reloaded. Reload once the new SW takes control so deploys
  // go live without a manual relaunch.
  //
  // Only reload when a controller was already present at load time: on a first-ever
  // visit clientsClaim fires controllerchange too, but the page already has the
  // latest assets, so reloading there would be a pointless extra refresh. Guarded
  // so it fires at most once.
  const hadControllerAtLoad = !!navigator.serviceWorker.controller;
  let reloadingForSwUpdate = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!hadControllerAtLoad || reloadingForSwUpdate) return;
    reloadingForSwUpdate = true;
    log.info('SW: New service worker took control — reloading for fresh assets');
    window.location.reload();
  });

  navigator.serviceWorker.getRegistration().then((reg) => {
    if (reg) {
      log.info('SW: Checking for updates...');
      reg.update().then(() => {
        log.info('SW: Update check complete');
      });
    }
  });
}

// Render the app
renderApp();
