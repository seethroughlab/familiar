import { useState, useEffect, useCallback, lazy, Suspense } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { Toaster } from 'sonner';
import { Loader2 } from 'lucide-react';
import { createLogger } from './utils/logger';

const log = createLogger('App');

import { ProfileSelector } from './components/Profiles';
import { WorkerAlert } from './components/WorkerAlert';
import { pluginLoader } from './services/pluginLoader';
import { initializeProfile, type Profile } from './services/profileService';

// Layout
import { AppShell } from './components/AppShell';
import { LibraryBrowser } from './components/Library/LibraryBrowser';

// Lazy-loaded route components
const AdminSetup = lazy(() => import('./components/Admin').then(m => ({ default: m.AdminSetup })));
const ArtistDetail = lazy(() => import('./components/Library/ArtistDetail').then(m => ({ default: m.ArtistDetail })));
const AlbumDetail = lazy(() => import('./components/Library/AlbumDetail').then(m => ({ default: m.AlbumDetail })));
const PlaylistDetail = lazy(() => import('./components/Playlists/PlaylistDetail').then(m => ({ default: m.PlaylistDetail })));
const EphemeralPlaylistDetail = lazy(() => import('./components/Playlists/EphemeralPlaylistDetail').then(m => ({ default: m.EphemeralPlaylistDetail })));
const FavoritesDetail = lazy(() => import('./components/Playlists/FavoritesDetail').then(m => ({ default: m.FavoritesDetail })));
const DownloadsDetail = lazy(() => import('./components/Playlists/DownloadsDetail').then(m => ({ default: m.DownloadsDetail })));
const SmartPlaylistDetail = lazy(() => import('./components/SmartPlaylists/SmartPlaylistDetail').then(m => ({ default: m.SmartPlaylistDetail })));
const WishlistRoute = lazy(() => import('./components/Playlists/WishlistRoute').then(m => ({ default: m.WishlistRoute })));

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

    let newPath = '/library/artists'; // default

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
    if (view === 'wishlist') { navigate('/wishlist', { replace: true }); return; }

    const playlistId = params.get('playlist');
    if (playlistId) { navigate(`/playlists/${playlistId}`, { replace: true }); return; }

    const smartPlaylistId = params.get('smartPlaylist');
    if (smartPlaylistId) { navigate(`/smart-playlists/${smartPlaylistId}`, { replace: true }); return; }

    // Browser mapping
    const browserMap: Record<string, string> = {
      'track-list': '/library/tracks',
      'artist-list': '/library/artists',
      'album-grid': '/library/albums',
      'mood-grid': '/library/mood-grid',
      'ego-music-map': '/library/music-map',
      'umap-explorer': '/library/explorer',
      'discover': '/library/discover',
      'proposed-changes': '/library/proposed-changes',
    };

    const browser = params.get('browser');
    if (browser && browserMap[browser]) {
      newPath = browserMap[browser];
    } else if (hash === 'settings') {
      // Settings is now a modal, redirect to default
      navigate('/library/artists', { replace: true });
      return;
    } else if (hash === 'playlists') {
      // Playlists are now in the sidebar
      navigate('/library/artists', { replace: true });
      return;
    } else if (hash === 'queue') {
      navigate('/library/artists', { replace: true });
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

// Browser ID to route path mapping
const BROWSER_ROUTES = [
  { path: 'tracks', browserId: 'track-list' },
  { path: 'artists', browserId: 'artist-list' },
  { path: 'albums', browserId: 'album-grid' },
  { path: 'mood-grid', browserId: 'mood-grid' },
  { path: 'music-map', browserId: 'ego-music-map' },
  { path: 'explorer', browserId: 'umap-explorer' },
  { path: 'discover', browserId: 'discover' },
  { path: 'proposed-changes', browserId: 'proposed-changes' },
];

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

  useEffect(() => {
    pluginLoader.initializeGlobalAPI();
    pluginLoader.loadAllPlugins().catch((err) => {
      log.error('Failed to load plugins:', err);
    });
  }, []);

  if (checkingProfile) {
    return (
      <div role="status" aria-label="Loading" className="min-h-screen bg-zinc-950 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500" />
      </div>
    );
  }

  const isAdminRoute = window.location.pathname === '/admin';

  if (profile === null && !isAdminRoute) {
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
        <Routes>
          {/* Admin route - outside AppShell */}
          <Route path="/admin" element={
            <Suspense fallback={<LazyLoadSpinner />}>
              <AdminSetup />
            </Suspense>
          } />

          {/* Main app routes inside AppShell */}
          <Route element={<AppShell />}>
            {/* Library browser views */}
            {BROWSER_ROUTES.map(({ path, browserId }) => (
              <Route
                key={path}
                path={`/library/${path}`}
                element={<LibraryBrowser browserId={browserId} />}
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
            <Route path="/wishlist" element={
              <Suspense fallback={<LazyLoadSpinner />}>
                <WishlistRoute />
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

            {/* Default redirect */}
            <Route index element={<Navigate to="/library/artists" replace />} />
            <Route path="*" element={<Navigate to="/library/artists" replace />} />
          </Route>
        </Routes>
      </QueryClientProvider>
    </BrowserRouter>
  );
}

export default App;
