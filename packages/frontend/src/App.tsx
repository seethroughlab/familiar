import { useState, useEffect, useCallback, lazy, Suspense } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'sonner';
import { Loader2 } from 'lucide-react';
import { createLogger } from './utils/logger';

const log = createLogger('App');

import { ProfileSelector } from './components/Profiles';
import { WorkerAlert } from './components/WorkerAlert';
import { MobileAppRedirect } from './components/MobileAppRedirect';
import { isIOS } from './utils/platform';
import { useUpdateNotification } from './hooks/useUpdateNotification';
import { initializeProfile, type Profile } from './services/profileService';

// Layout
import { AppShell } from './components/AppShell';
import { LibraryBrowser } from './components/Library/LibraryBrowser';

// Lazy-loaded route components
const LibraryPage = lazy(() => import('./components/Admin/LibraryPage').then(m => ({ default: m.LibraryPage })));
const ToolsPage = lazy(() => import('./components/Admin/ToolsPage').then(m => ({ default: m.ToolsPage })));
const DuplicatesPage = lazy(() => import('./components/Admin/DuplicatesPage').then(m => ({ default: m.DuplicatesPage })));
const OrganizePage = lazy(() => import('./components/Admin/OrganizePage').then(m => ({ default: m.OrganizePage })));
const ArtworkPage = lazy(() => import('./components/Admin/ArtworkPage').then(m => ({ default: m.ArtworkPage })));
const ServerPage = lazy(() => import('./components/Admin/ServerPage').then(m => ({ default: m.ServerPage })));
// The guest listener (ADR-0036). Lazy like every other route component, and worth it here: a guest
// loads this page and nothing else, and everyone else never loads it at all.

import { MixTapeProgressWatcher } from './components/MixTape';

function LazyLoadSpinner() {
  return (
    <div role="status" aria-label="Loading" className="flex items-center justify-center py-20">
      <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
    </div>
  );
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1,
    },
  },
});

/**
 * Redirect legacy hash-based URLs to new path-based routes.
 * e.g. /?browser=track-list#library → /library/tracks
 */

import { BROWSER_ROUTES } from './routes';

// PWA Reset utility
function resetPWAState() {
  log.info('[App] Resetting PWA state');
  const keysToRemove = Object.keys(localStorage).filter(
    (k) => k.startsWith('familiar-') || k.startsWith('zustand-')
  );
  keysToRemove.forEach((k) => localStorage.removeItem(k));

  if ('indexedDB' in window) {
    indexedDB.databases?.().then((dbs) => {
      dbs.forEach((db) => {
        if (db.name) {
          indexedDB.deleteDatabase(db.name);
        }
      });
    });
  }

  window.history.replaceState(null, '', window.location.pathname);
  window.location.reload();
}

if (typeof window !== 'undefined') {
  (window as unknown as { resetFamiliar: () => void }).resetFamiliar = resetPWAState;
}

function App() {
  // Send an iPhone visitor to the real listening client (ADR-0050): the phone's job is playing
  // music, and this page administers a server. The `!isPWA()` term went with ADR-0059 — there is
  // no installed copy to be already inside.
  const [showMobileRedirect] = useState(
    () => isIOS() && !sessionStorage.getItem('familiar-continue-in-browser')
  );
  const [mobileRedirectDismissed, setMobileRedirectDismissed] = useState(false);
  const [profile, setProfile] = useState<Profile | null | undefined>(undefined);
  const [checkingProfile, setCheckingProfile] = useState(true);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('reset') === 'true') {
      resetPWAState();
    }
  }, []);

  const checkProfile = useCallback(async () => {
    setCheckingProfile(true);
    try {
      const timeoutPromise = new Promise<null>((resolve) => {
        setTimeout(() => {
          log.warn('[App] Profile initialization timed out');
          resolve(null);
        }, 5000);
      });

      const p = await Promise.race([initializeProfile(), timeoutPromise]);
      setProfile(p);
    } catch (err) {
      log.error('Failed to check profile:', err);
      setProfile(null);
    } finally {
      setCheckingProfile(false);
    }
  }, []);

  useEffect(() => {
    checkProfile();
    const handleInvalidated = () => setProfile(null);
    window.addEventListener('profile-invalidated', handleInvalidated);
    return () => window.removeEventListener('profile-invalidated', handleInvalidated);
  }, [checkProfile]);

  useUpdateNotification();

  if (showMobileRedirect && !mobileRedirectDismissed) {
    return (
      <MobileAppRedirect
        onContinue={() => {
          sessionStorage.setItem('familiar-continue-in-browser', '1');
          setMobileRedirectDismissed(true);
        }}
      />
    );
  }

  // No Connect-to-Server screen. It only ever appeared when `isNativeApp()` was true, and that
  // tested for `window.Capacitor` — an app deleted on 2026-08-11 (ADR-0001 point 6). The web app
  // is same-origin, so there is no URL to ask for.

  if (checkingProfile) {
    return (
      <div role="status" aria-label="Loading" className="min-h-screen bg-zinc-950 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500" />
      </div>
    );
  }

  if (profile === null) {
    return (
      <ProfileSelector onProfileSelected={(p) => setProfile(p)} />
    );
  }

  return (
    <BrowserRouter>
      <Toaster
        theme="dark"
        position="bottom-right"
        toastOptions={{
          className: 'bg-zinc-900 border-zinc-800 text-white',
          descriptionClassName: 'text-zinc-400',
        }}
        closeButton
        richColors
      />
      <WorkerAlert />
      <QueryClientProvider client={queryClient}>
        {/* Legacy URL redirect handler */}
        {/* Watches in-flight mix tape renders and toasts on terminal state */}
        <MixTapeProgressWatcher />
        <Routes>

          {/* Main app routes inside AppShell */}
          <Route element={<AppShell />}>

            {/* The other two destinations. Library is the index route below. */}
            <Route path="/tools" element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <ToolsPage />
              </Suspense>
            } />
            {/* Phase 4. Both preview-only — the server exposes no apply route for either. */}
            <Route path="/tools/duplicates" element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <DuplicatesPage />
              </Suspense>
            } />
            <Route path="/tools/artwork" element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <ArtworkPage />
              </Suspense>
            } />
            <Route path="/tools/organize" element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <OrganizePage />
              </Suspense>
            } />
            <Route path="/server" element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <ServerPage />
              </Suspense>
            } />
            {/* Library browser views */}
            {BROWSER_ROUTES.map(({ path, browserId }) => (
              <Route
                key={path}
                path={`/library/${path}`}
                element={<LibraryBrowser key={browserId} browserId={browserId} />}
              />
            ))}
            {/* Collections */}
            {/* Mix Tapes */}

            {/* Default redirect */}
            {/* ADR-0058 point 1: the administrator lands on the thing being administered, not on a
                form. This was `Navigate to="/settings"`; there is no settings route at all now —
                ADR-0080 deleted it once theme was the only control left on it. The catch-all below
                sends an old bookmark here. */}
            <Route index element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <LibraryPage />
              </Suspense>
            } />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </QueryClientProvider>
    </BrowserRouter>
  );
}

export default App;
