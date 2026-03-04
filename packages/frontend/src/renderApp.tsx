import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import { initApiOrigin } from './api/base';

/**
 * Shared app renderer. Called by platform-specific entry points (web/main.tsx, ios/main.tsx)
 * after they've registered their platform services (engine factory, preferences, etc).
 */
export function renderApp(): void {
  // Initialize API origin (resolves backend URL for Capacitor, no-op on web)
  initApiOrigin().then(() => {
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
  });
}
