import { useState, useEffect, useCallback, lazy, Suspense } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'sonner';
import { Loader2 } from 'lucide-react';
import { createLogger } from '../utils/logger';

const log = createLogger('App');

import { ProfileSelector } from '../components/Profiles';
import { WorkerAlert } from '../components/WorkerAlert';
import { MobileAppRedirect } from '../components/MobileAppRedirect';
import { isIOS } from '../utils/platform';
import { useUpdateNotification } from '../hooks/useUpdateNotification';
import { initializeProfile, type Profile } from '../services/profileService';

// Layout
import { AppShell } from './AppShell';
import { LEGACY_REDIRECTS } from './routes';
import { SectionLayout } from '../screens/SectionLayout';

// Lazy-loaded route components
const OverviewPage = lazy(() => import('../screens/overview/OverviewPage').then(m => ({ default: m.OverviewPage })));
const SyncSection = lazy(() => import('../screens/library/SyncSection').then(m => ({ default: m.SyncSection })));
const DuplicatesPage = lazy(() => import('../screens/DuplicatesPage').then(m => ({ default: m.DuplicatesPage })));
const OrganizePage = lazy(() => import('../screens/OrganizePage').then(m => ({ default: m.OrganizePage })));
const ArtworkPage = lazy(() => import('../screens/ArtworkPage').then(m => ({ default: m.ArtworkPage })));
const ArtistsSection = lazy(() => import('../screens/library/ArtistsSection').then(m => ({ default: m.ArtistsSection })));
const StatusSection = lazy(() => import('../screens/analysis/StatusSection').then(m => ({ default: m.StatusSection })));
const ConfigurationSection = lazy(() => import('../screens/analysis/ConfigurationSection').then(m => ({ default: m.ConfigurationSection })));
const HealthSection = lazy(() => import('../screens/server/sections').then(m => ({ default: m.HealthSection })));
const JobsSection = lazy(() => import('../screens/server/sections').then(m => ({ default: m.JobsSection })));
const ProvidersSection = lazy(() => import('../screens/server/sections').then(m => ({ default: m.ProvidersSection })));
const BackupSection = lazy(() => import('../screens/server/sections').then(m => ({ default: m.BackupSection })));
const PeopleSection = lazy(() => import('../screens/server/sections').then(m => ({ default: m.PeopleSection })));
const AccessSection = lazy(() => import('../screens/server/sections').then(m => ({ default: m.AccessSection })));
const DiagnosticsSection = lazy(() => import('../screens/server/sections').then(m => ({ default: m.DiagnosticsSection })));
// The guest listener (ADR-0036). Lazy like every other route component, and worth it here: a guest
// loads this page and nothing else, and everyone else never loads it at all.

import { MixTapeProgressWatcher } from '../components/MixTape';

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

            {/* ADR-0126 point 1: four destinations. Overview is the index; the other three are
                layouts with a section rail, every section a route of its own (point 7).
                Child paths are written absolute so `navigationIntegrity.test.ts`, which reads
                this file for `path="/…"`, sees every one of them. */}
            <Route index element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <OverviewPage />
              </Suspense>
            } />

            <Route path="/library" element={<SectionLayout destination="/library" />}>
              <Route index element={<Suspense fallback={<LazyLoadSpinner />}><SyncSection /></Suspense>} />
              {/* Preview-only — the server exposes no apply route for either. */}
              <Route path="/library/duplicates" element={<Suspense fallback={<LazyLoadSpinner />}><DuplicatesPage /></Suspense>} />
              <Route path="/library/artists" element={<Suspense fallback={<LazyLoadSpinner />}><ArtistsSection /></Suspense>} />
              <Route path="/library/artwork" element={<Suspense fallback={<LazyLoadSpinner />}><ArtworkPage /></Suspense>} />
              <Route path="/library/organize" element={<Suspense fallback={<LazyLoadSpinner />}><OrganizePage /></Suspense>} />
            </Route>

            <Route path="/analysis" element={<SectionLayout destination="/analysis" />}>
              <Route index element={<Suspense fallback={<LazyLoadSpinner />}><StatusSection /></Suspense>} />
              <Route path="/analysis/configuration" element={<Suspense fallback={<LazyLoadSpinner />}><ConfigurationSection /></Suspense>} />
            </Route>

            <Route path="/server" element={<SectionLayout destination="/server" />}>
              <Route index element={<Suspense fallback={<LazyLoadSpinner />}><HealthSection /></Suspense>} />
              <Route path="/server/jobs" element={<Suspense fallback={<LazyLoadSpinner />}><JobsSection /></Suspense>} />
              <Route path="/server/providers" element={<Suspense fallback={<LazyLoadSpinner />}><ProvidersSection /></Suspense>} />
              <Route path="/server/backup" element={<Suspense fallback={<LazyLoadSpinner />}><BackupSection /></Suspense>} />
              <Route path="/server/people" element={<Suspense fallback={<LazyLoadSpinner />}><PeopleSection /></Suspense>} />
              <Route path="/server/access" element={<Suspense fallback={<LazyLoadSpinner />}><AccessSection /></Suspense>} />
              <Route path="/server/diagnostics" element={<Suspense fallback={<LazyLoadSpinner />}><DiagnosticsSection /></Suspense>} />
            </Route>

            {/* Old paths redirect to their successors (ADR-0126, Consequences). A router concern,
                not an ADR-0079 API alias. */}
            {Object.entries(LEGACY_REDIRECTS).map(([from, to]) => (
              <Route key={from} path={from} element={<Navigate to={to} replace />} />
            ))}

            {/* An unknown path lands on the Overview. */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </QueryClientProvider>
    </BrowserRouter>
  );
}

export default App;
