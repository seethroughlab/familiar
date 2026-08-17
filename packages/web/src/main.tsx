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

/**
 * Unregister the service worker this app used to install (ADR-0059).
 *
 * **Deleting the worker is not enough.** A browser that registered `/sw.js` keeps running it, and
 * a Workbox worker serves the app shell cache-first — so every previous visitor would keep getting
 * the old bundle indefinitely, with no way to reach the new one short of clearing site data. The
 * app has to actively tear its own worker down, which is why this block outlives the PWA it
 * belonged to.
 *
 * Keep it. It costs one no-op call on a clean browser and is the only thing standing between an
 * existing install and a permanently stale app.
 */
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistrations().then((registrations) => {
    for (const registration of registrations) {
      registration.unregister().then((ok) => {
        if (ok) log.info('SW: unregistered a stale service worker (ADR-0059)');
      });
    }
  }).catch((error) => {
    log.error('SW: failed to enumerate registrations', error);
  });

  // Workbox's precache and runtime caches survive unregistration, so they go too. Named caches
  // only — `caches.keys()` here is this origin's, but being explicit keeps it obvious that the
  // Dexie track store (a different storage API entirely) is untouched.
  if (typeof caches !== 'undefined') {
    caches.keys().then((keys) => {
      for (const key of keys) {
        if (key.startsWith('workbox-') || key.endsWith('-cache') || key.startsWith('familiar-')) {
          caches.delete(key);
        }
      }
    }).catch(() => {
      // Non-fatal: a browser that refuses cache enumeration simply keeps some dead bytes.
    });
  }
}

// Render the app
renderApp();
