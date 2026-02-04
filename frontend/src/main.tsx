import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Version for debugging cache issues
const APP_VERSION = 'v3-ios-fix-2024-01-23';
console.log(`[Familiar] ${APP_VERSION} loaded`);

// Global handler for unhandled promise rejections
window.addEventListener('unhandledrejection', (event) => {
  // Log the error for debugging
  console.error('[Unhandled Promise Rejection]', event.reason);

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
    console.error('Failed to show error toast');
  });
});

// Force service worker update check
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistration().then((reg) => {
    if (reg) {
      console.log('[SW] Checking for updates...');
      reg.update().then(() => {
        console.log('[SW] Update check complete');
      });
    }
  });
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
