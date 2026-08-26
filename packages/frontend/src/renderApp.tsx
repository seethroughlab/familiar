import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import { initApiOrigin, initServerToken, registerProfileProvider } from './api/base';
import { getSelectedProfileId, clearSelectedProfile } from './services/profileSelection';

/**
 * Shared app renderer. Called by platform-specific entry points (web/main.tsx, ios/main.tsx)
 * after they've registered their platform services (engine factory, preferences, etc).
 */
export function renderApp(options?: { onReady?: () => void }): void {
  // Register profile provider so api/base doesn't import from services/ directly
  registerProfileProvider({ getSelectedProfileId, clearSelectedProfile });

  // Initialize API origin (resolves backend URL for Capacitor, no-op on web) and the server token
  // (ADR-0045). Both must resolve before the first request: the token is read synchronously by the
  // request interceptor, so a render that beat this would send its opening requests unauthenticated
  // and get a 401 on a server that is configured correctly.
  Promise.all([initApiOrigin(), initServerToken()]).then(() => {
    options?.onReady?.();
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
  });
}
