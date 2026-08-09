import { useState, useEffect, useCallback, lazy, Suspense } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { Toaster } from 'sonner';
import { Loader2 } from 'lucide-react';
import { createLogger } from './utils/logger';

const log = createLogger('App');

import { ProfileSelector } from './components/Profiles';
import { WorkerAlert } from './components/WorkerAlert';
import { ServerSettings } from './components/Settings/ServerSettings';
import { getApiOrigin } from './api/base';
import { MobileAppRedirect } from './components/MobileAppRedirect';
import { isIOS, isNativeApp, isPWA } from './utils/platform';
import { useUpdateNotification } from './hooks/useUpdateNotification';
import { initializeProfile, type Profile } from './services/profileService';

// Layout
import { AppShell } from './components/AppShell';
import { LibraryBrowser } from './components/Library/LibraryBrowser';
import { HomeScreen } from './components/Home';

// Lazy-loaded route components
const ArtistDetail = lazy(() => import('./components/Library/ArtistDetail').then(m => ({ default: m.ArtistDetail })));
const AlbumDetail = lazy(() => import('./components/Library/AlbumDetail').then(m => ({ default: m.AlbumDetail })));
const PlaylistDetail = lazy(() => import('./components/Playlists/PlaylistDetail').then(m => ({ default: m.PlaylistDetail })));
const EphemeralPlaylistDetail = lazy(() => import('./components/Playlists/EphemeralPlaylistDetail').then(m => ({ default: m.EphemeralPlaylistDetail })));
// The guest listener (ADR-0036). Lazy like every other route component, and worth it here: a guest
// loads this page and nothing else, and everyone else never loads it at all.
const GuestListener = lazy(() => import('./components/Guest/GuestListener').then(m => ({ default: m.GuestListener })));
const FavoritesDetail = lazy(() => import('./components/Playlists/FavoritesDetail').then(m => ({ default: m.FavoritesDetail })));
const DownloadsDetail = lazy(() => import('./components/Playlists/DownloadsDetail').then(m => ({ default: m.DownloadsDetail })));
const SmartPlaylistDetail = lazy(() => import('./components/SmartPlaylists/SmartPlaylistDetail').then(m => ({ default: m.SmartPlaylistDetail })));
const MixTapesList = lazy(() => import('./components/MixTape').then(m => ({ default: m.MixTapesList })));

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
function LegacyRedirect() {
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const hash = window.location.hash.slice(1);
    const params = new URLSearchParams(window.location.search);

    // Only redirect if we have hash-based navigation
    if (!hash && !params.has('browser') && !params.has('view') && !params.has('playlist') && !params.has('smartPlaylist') && !params.has('artistDetail') && !params.has('albumDetailArtist')) {
      return;
    }

    let newPath = '/home'; // default

    // Check for detail views first
    const artistDetail = params.get('artistDetail');
    if (artistDetail) {
      newPath = `/library/artists/${encodeURIComponent(artistDetail)}`;
      navigate(newPath, { replace: true });
      return;
    }

    const albumDetailArtist = params.get('albumDetailArtist');
    const albumDetailAlbum = params.get('albumDetailAlbum');
    if (albumDetailArtist && albumDetailAlbum) {
      newPath = `/library/albums/${encodeURIComponent(albumDetailArtist)}/${encodeURIComponent(albumDetailAlbum)}`;
      navigate(newPath, { replace: true });
      return;
    }

    // Check for playlist views
    const view = params.get('view');
    if (view === 'favorites') { navigate('/favorites', { replace: true }); return; }
    if (view === 'downloads') { navigate('/downloads', { replace: true }); return; }

    const playlistId = params.get('playlist');
    if (playlistId) { navigate(`/playlists/${playlistId}`, { replace: true }); return; }

    const smartPlaylistId = params.get('smartPlaylist');
    if (smartPlaylistId) { navigate(`/smart-playlists/${smartPlaylistId}`, { replace: true }); return; }

    // Browser mapping
    const browserMap: Record<string, string> = {
      'track-list': '/library/tracks',
      'artist-list': '/library/artists',
      'album-grid': '/library/albums',
      'vibe-map': '/library/music-map',
      'discover': '/library/discover',
      'proposed-changes': '/library/proposed-changes',
    };

    const browser = params.get('browser');
    if (browser && browserMap[browser]) {
      newPath = browserMap[browser];
    } else if (hash === 'settings') {
      // Settings is now a modal, redirect to default
      navigate('/home', { replace: true });
      return;
    } else if (hash === 'playlists') {
      // Playlists are now in the sidebar
      navigate('/home', { replace: true });
      return;
    } else if (hash === 'queue') {
      navigate('/home', { replace: true });
      return;
    }

    // Preserve filter params
    const filterParams = new URLSearchParams();
    for (const key of ['search', 'artist', 'album', 'genre', 'yearFrom', 'yearTo',
      'energyMin', 'energyMax', 'valenceMin', 'valenceMax', 'downloadedOnly']) {
      const val = params.get(key);
      if (val) filterParams.set(key, val);
    }

    const filterString = filterParams.toString();
    navigate(newPath + (filterString ? `?${filterString}` : ''), { replace: true });
  }, [location, navigate]);

  return null;
}

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
  const [showMobileRedirect] = useState(
    () => isIOS() && !isNativeApp() && !isPWA() &&
          !sessionStorage.getItem('familiar-continue-in-browser')
  );
  const [mobileRedirectDismissed, setMobileRedirectDismissed] = useState(false);

  const [serverConfigured, setServerConfigured] = useState(
    () => !isNativeApp() || !!getApiOrigin()
  );
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
    if (!serverConfigured) return;
    checkProfile();
    const handleInvalidated = () => setProfile(null);
    window.addEventListener('profile-invalidated', handleInvalidated);
    return () => window.removeEventListener('profile-invalidated', handleInvalidated);
  }, [checkProfile, serverConfigured]);

  // "Change Server" in Settings dispatches this — drop back to the
  // Connect-to-Server screen without needing to restart the app.
  useEffect(() => {
    const handleReset = () => {
      setProfile(null);
      setServerConfigured(false);
    };
    window.addEventListener('server-reset', handleReset);
    return () => window.removeEventListener('server-reset', handleReset);
  }, []);

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

  if (!serverConfigured) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-6">
        <div className="w-full max-w-md space-y-6">
          <div className="text-center space-y-2">
            <h1 className="text-2xl font-bold text-white">Connect to Server</h1>
            <p className="text-zinc-400 text-sm">
              Enter the URL of your Familiar server to get started.
            </p>
          </div>
          <ServerSettings onConnected={() => setServerConfigured(true)} />
        </div>
      </div>
    );
  }

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
        <LegacyRedirect />
        {/* Watches in-flight mix tape renders and toasts on terminal state */}
        <MixTapeProgressWatcher />
        <Routes>
          {/*
            The guest listener (ADR-0036), and deliberately *outside* `AppShell`.

            A guest has no profile, no library and no player — they have a code someone sent them.
            Mounting this inside the shell would give them a sidebar to nothing and construct the
            audio engine for a page whose audio arrives over a peer connection.

            **This route has never existed here before.** The share link used to point at
            `familiar-sessions.fly.dev/listen/{code}`, which the relay served itself; retiring the
            relay leaves `buildShareLink` pointing at this origin, and without this the one thing a
            host hands to a friend would 404. That is the shape of defect this codebase keeps
            shipping, and it would have been introduced by the fix.
          */}
          <Route path="/listen/:code?" element={
            <Suspense fallback={<LazyLoadSpinner />}>
              <GuestListener />
            </Suspense>
          } />

          {/* Main app routes inside AppShell */}
          <Route element={<AppShell />}>
            <Route path="/home" element={<HomeScreen />} />
            {/* Library browser views */}
            {BROWSER_ROUTES.map(({ path, browserId }) => (
              <Route
                key={path}
                path={`/library/${path}`}
                element={<LibraryBrowser key={browserId} browserId={browserId} />}
              />
            ))}

            {/* Drill-down detail views */}
            <Route path="/library/artists/:name" element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <ArtistDetail />
              </Suspense>
            } />
            <Route path="/library/albums/:artist/:album" element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <AlbumDetail />
              </Suspense>
            } />

            {/* Collections */}
            <Route path="/favorites" element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <FavoritesDetail />
              </Suspense>
            } />
            <Route path="/downloads" element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <DownloadsDetail />
              </Suspense>
            } />

            {/* Playlists */}
            <Route path="/playlists/:id" element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <PlaylistDetail />
              </Suspense>
            } />
            <Route path="/smart-playlists/:id" element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <SmartPlaylistDetail />
              </Suspense>
            } />
            <Route path="/ephemeral/:id" element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <EphemeralPlaylistDetail />
              </Suspense>
            } />

            {/* Mix Tapes */}
            <Route path="/mixtapes" element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <MixTapesList />
              </Suspense>
            } />

            {/* Default redirect */}
            <Route index element={<Navigate to="/home" replace />} />
            <Route path="*" element={<Navigate to="/home" replace />} />
          </Route>
        </Routes>
      </QueryClientProvider>
    </BrowserRouter>
  );
}

export default App;
