import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { initApiOrigin } from './api/base';
import { createLogger } from './utils/logger';

const log = createLogger('App');

// Build timestamp injected by Vite at build time
declare const __BUILD_TIME__: string;
export const BUILD_TIME = typeof __BUILD_TIME__ !== 'undefined' ? __BUILD_TIME__ : 'dev';
console.log(`[App] Build: ${BUILD_TIME}`);

// Global handler for unhandled promise rejections
window.addEventListener('unhandledrejection', (event) => {
  // Log the error for debugging
  log.error('Unhandled Promise Rejection:', event.reason);

  // Prevent the default browser behavior (console error)
  // but still log it for debugging
  event.preventDefault();

  // Import toast store dynamically to avoid circular deps
  import('./stores/toastStore').then(({ showError }) => {
    // Only show toast for non-network errors (network errors are usually handled elsewhere)
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
    // If we can't even import the toast store, just log it
    log.error('Failed to show error toast');
  });
});

// Force service worker update check (skip in Capacitor — no SW in native app)
const isCapacitorNative = !!(window as unknown as Record<string, unknown>).Capacitor &&
  (window as unknown as { Capacitor: { isNativePlatform?: () => boolean } })
    .Capacitor.isNativePlatform?.() === true;

if ('serviceWorker' in navigator && !isCapacitorNative) {
  navigator.serviceWorker.getRegistration().then((reg) => {
    if (reg) {
      log.info('SW: Checking for updates...');
      reg.update().then(() => {
        log.info('SW: Update check complete');
      });
    }
  });
}

// Initialize API origin (resolves backend URL for Capacitor, no-op on web)
initApiOrigin().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
