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
registerEngineFactory(() => new WebAudioEngine());

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
