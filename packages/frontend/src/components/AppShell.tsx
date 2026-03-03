/**
 * AppShell - Persistent layout wrapper.
 *
 * Renders: Sidebar | <Outlet /> | RightPanel (optional)
 * PlayerBar (full width, bottom)
 */
import { useState, useEffect, useRef, lazy, Suspense } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { useUIStore } from '../stores/uiStore';
import { usePlayerStore } from '../stores/playerStore';
import { useSelectionStore } from '../stores/selectionStore';
import { useThemeStore } from '../stores/themeStore';
import { useAudioEngine } from '../hooks/useAudioEngine';
import { useScrobbling } from '../hooks/useScrobbling';
import { usePlayTracking } from '../hooks/usePlayTracking';
import { useMetadataEnrichment } from '../hooks/useMetadataEnrichment';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { initSyncListeners } from '../services/syncService';
import { initRemoteLogging } from '../services/remoteLogService';
import { PlayerBar } from './Player/PlayerBar';
import { Sidebar } from './Sidebar/Sidebar';
import { ContentToolbar } from './ContentToolbar';
import { ErrorBoundary } from './ErrorBoundary';
import { GlobalDropZone, ImportModal } from './Import';
import { InstallPrompt } from './PWA/InstallPrompt';
import { OfflineIndicator } from './PWA/OfflineIndicator';
import { ShortcutsHelp } from './KeyboardShortcuts';
import { TrackEditModal } from './TrackEdit';
import { MobileBottomNav } from './MobileNav';
import { PlaylistPickerModal } from './Playlists/PlaylistPickerModal';
import { createLogger } from '../utils/logger';

const log = createLogger('AppShell');

// Lazy-loaded components
const FullPlayer = lazy(() => import('./FullPlayer').then(m => ({ default: m.FullPlayer })));
const SettingsPanel = lazy(() => import('./Settings').then(m => ({ default: m.SettingsPanel })));
const QueueView = lazy(() => import('./Queue').then(m => ({ default: m.QueueView })));
const ChatPanel = lazy(() => import('./Chat').then(m => ({ default: m.ChatPanel })));

function LazyLoadSpinner() {
  return (
    <div role="status" aria-label="Loading" className="flex items-center justify-center py-20">
      <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
    </div>
  );
}

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [importFiles, setImportFiles] = useState<File[] | null>(null);
  const [showShortcutsHelp, setShowShortcutsHelp] = useState(false);
  const [fullPlayerMounted, setFullPlayerMounted] = useState(false);

  // UI store
  const rightPanel = useUIStore((s) => s.rightPanel);
  const showSettings = useUIStore((s) => s.showSettings);
  const showFullPlayer = useUIStore((s) => s.showFullPlayer);
  const toggleRightPanel = useUIStore((s) => s.toggleRightPanel);
  const closeRightPanel = useUIStore((s) => s.closeRightPanel);
  const setShowSettings = useUIStore((s) => s.setShowSettings);
  const setShowFullPlayer = useUIStore((s) => s.setShowFullPlayer);

  // Theme
  const resolvedTheme = useThemeStore((state) => state.resolvedTheme);

  // Track edit modal
  const editingTrackId = useSelectionStore((state) => state.editingTrackId);

  // Mount FullPlayer on first open, keep mounted for slide animation
  useEffect(() => {
    if (showFullPlayer && !fullPlayerMounted) {
      setFullPlayerMounted(true);
    }
  }, [showFullPlayer, fullPlayerMounted]);

  // Initialize Audio Engine
  useAudioEngine();
  useScrobbling();
  usePlayTracking();
  useMetadataEnrichment();

  // Keyboard shortcuts
  useKeyboardShortcuts({
    onToggleFullPlayer: () => setShowFullPlayer(!showFullPlayer),
    onShowHelp: () => setShowShortcutsHelp(true),
    onEscape: () => {
      if (showShortcutsHelp) {
        setShowShortcutsHelp(false);
      } else if (showFullPlayer) {
        setShowFullPlayer(false);
      } else if (showSettings) {
        setShowSettings(false);
      } else if (rightPanel) {
        closeRightPanel();
      }
    },
  });

  // Initialize offline sync listeners
  useEffect(() => {
    return initSyncListeners();
  }, []);

  // Initialize remote logging (captures frontend logs to backend)
  useEffect(() => {
    return initRemoteLogging();
  }, []);

  // Listen for navigate-to-settings event
  useEffect(() => {
    const handler = () => setShowSettings(true);
    window.addEventListener('navigate-to-settings', handler);
    return () => window.removeEventListener('navigate-to-settings', handler);
  }, [setShowSettings]);

  // Listen for show-playlist event from ChatPanel
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.playlistId) {
        navigate(`/playlists/${detail.playlistId}`);
      }
    };
    window.addEventListener('show-playlist', handler);
    return () => window.removeEventListener('show-playlist', handler);
  }, [navigate]);

  // Listen for show-ephemeral-playlist event
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.ephemeralId) {
        navigate(`/ephemeral/${detail.ephemeralId}`);
      }
    };
    window.addEventListener('show-ephemeral-playlist', handler);
    return () => window.removeEventListener('show-ephemeral-playlist', handler);
  }, [navigate]);

  const pendingChatMessage = useUIStore((s) => s.pendingChatMessage);
  const playlistPickerTrackIds = useUIStore((s) => s.playlistPickerTrackIds);

  // Hydrate player state from IndexedDB
  const hydrate = usePlayerStore((state) => state.hydrate);
  useEffect(() => {
    hydrate();
  }, [hydrate]);

  // Triple-tap recovery for mobile
  const tapCountRef = useRef(0);
  const lastTapTimeRef = useRef(0);
  useEffect(() => {
    const handleTripleTap = () => {
      const now = Date.now();
      if (now - lastTapTimeRef.current < 500) {
        tapCountRef.current++;
        if (tapCountRef.current >= 3) {
          log.info('[AppShell] Triple-tap recovery triggered');
          setShowFullPlayer(false);
          closeRightPanel();
          setShowSettings(false);
          setShowShortcutsHelp(false);
          tapCountRef.current = 0;
        }
      } else {
        tapCountRef.current = 1;
      }
      lastTapTimeRef.current = now;
    };

    if ('ontouchstart' in window) {
      document.addEventListener('touchstart', handleTripleTap);
      return () => document.removeEventListener('touchstart', handleTripleTap);
    }
  }, [setShowFullPlayer, closeRightPanel, setShowSettings]);

  return (
    <GlobalDropZone onFilesDropped={setImportFiles}>
      <div className={`h-dynamic-screen flex flex-col select-none ${resolvedTheme === 'light' ? 'bg-white text-zinc-900' : 'bg-black text-white'}`}>
        {/* Main content area */}
        <div className="flex-1 flex overflow-hidden min-h-0">
          {/* Sidebar - hidden on mobile */}
          <div className="hidden md:flex">
            <Sidebar />
          </div>

          {/* Content area with Outlet */}
          <main className={`flex-1 flex flex-col overflow-hidden min-h-0 ${resolvedTheme === 'light' ? 'bg-gradient-to-b from-zinc-50 to-white' : 'bg-gradient-to-b from-zinc-900 to-black'}`}>
            <ContentToolbar />
            <div className="flex-1 overflow-y-auto overflow-x-hidden min-h-0">
              <Outlet key={location.pathname} />
            </div>
          </main>

          {/* Right panel - Queue or Chat (desktop only) */}
          {rightPanel && (
            <div className={`hidden md:flex w-80 border-l flex-col ${resolvedTheme === 'light' ? 'border-zinc-200 bg-white' : 'border-zinc-800 bg-zinc-900'}`}>
              <div className={`flex items-center justify-between p-4 border-b ${resolvedTheme === 'light' ? 'border-zinc-200' : 'border-zinc-800'}`}>
                <h2 className="font-semibold">{rightPanel === 'queue' ? 'Queue' : 'AI Assistant'}</h2>
                <button
                  onClick={closeRightPanel}
                  className={`p-1.5 rounded-lg transition-colors ${resolvedTheme === 'light' ? 'hover:bg-zinc-100' : 'hover:bg-zinc-800'}`}
                  aria-label={`Close ${rightPanel} panel`}
                >
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12" /></svg>
                </button>
              </div>
              <div className="flex-1 overflow-hidden min-h-0">
                <Suspense fallback={<LazyLoadSpinner />}>
                  {rightPanel === 'queue' && <QueueView />}
                  {rightPanel === 'chat' && (
                    <ChatPanel
                      pendingMessage={pendingChatMessage}
                      onPendingMessageConsumed={() => useUIStore.getState().consumePendingChatMessage()}
                    />
                  )}
                </Suspense>
              </div>
            </div>
          )}
        </div>

        {/* Player bar - fixed at bottom (above mobile nav on small screens) */}
        <ErrorBoundary name="Player">
          <PlayerBar
            onExpandClick={() => setShowFullPlayer(true)}
            onQueueToggle={() => toggleRightPanel('queue')}
            isQueueOpen={rightPanel === 'queue'}
            onChatToggle={() => toggleRightPanel('chat')}
            isChatOpen={rightPanel === 'chat'}
          />
        </ErrorBoundary>

        {/* Mobile bottom nav - fixed at very bottom on small screens */}
        <MobileBottomNav />

        {/* Full player overlay */}
        {fullPlayerMounted && (
          <ErrorBoundary name="Full Player" fullscreen>
            <Suspense fallback={
              <div role="status" aria-label="Loading" className="fixed inset-0 z-50 bg-black flex items-center justify-center">
                <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
              </div>
            }>
              <FullPlayer isOpen={showFullPlayer} onClose={() => setShowFullPlayer(false)} />
            </Suspense>
          </ErrorBoundary>
        )}

        {/* Settings modal */}
        {showSettings && (
          <div className="fixed inset-0 z-40 flex items-center justify-center">
            <div className="absolute inset-0 bg-black/60" onClick={() => setShowSettings(false)} />
            <div className={`relative w-full max-w-4xl max-h-[85vh] mx-4 rounded-xl overflow-hidden shadow-2xl ${resolvedTheme === 'light' ? 'bg-white' : 'bg-zinc-900'}`}>
              <div className={`flex items-center justify-between p-4 border-b ${resolvedTheme === 'light' ? 'border-zinc-200' : 'border-zinc-800'}`}>
                <h2 className="text-lg font-semibold">Settings</h2>
                <button
                  onClick={() => setShowSettings(false)}
                  className={`p-1.5 rounded-lg transition-colors ${resolvedTheme === 'light' ? 'hover:bg-zinc-100' : 'hover:bg-zinc-800'}`}
                  aria-label="Close settings"
                >
                  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12" /></svg>
                </button>
              </div>
              <div className="overflow-y-auto max-h-[calc(85vh-4rem)]">
                <Suspense fallback={<LazyLoadSpinner />}>
                  <SettingsPanel />
                </Suspense>
              </div>
            </div>
          </div>
        )}

        {/* Mobile chat overlay */}
        {rightPanel === 'chat' && (
          <div className="md:hidden fixed inset-0 z-50 flex">
            <div className="absolute inset-0 bg-black/50" onClick={closeRightPanel} />
            <div className={`relative w-full max-w-md ${resolvedTheme === 'light' ? 'bg-white' : 'bg-zinc-900'} flex flex-col pt-safe pb-safe`}>
              <Suspense fallback={<LazyLoadSpinner />}>
                <ChatPanel
                  pendingMessage={pendingChatMessage}
                  onPendingMessageConsumed={() => useUIStore.getState().consumePendingChatMessage()}
                  onClose={closeRightPanel}
                />
              </Suspense>
            </div>
          </div>
        )}

        {/* Mobile queue overlay */}
        {rightPanel === 'queue' && (
          <div className="md:hidden fixed inset-0 z-50 flex flex-col">
            <div className="absolute inset-0 bg-black/50" onClick={closeRightPanel} />
            <div className={`relative flex-1 mt-12 ${resolvedTheme === 'light' ? 'bg-white' : 'bg-zinc-900'} rounded-t-xl flex flex-col pb-safe`}>
              <div className="flex items-center justify-between p-4">
                <h2 className="font-semibold">Queue</h2>
                <button onClick={closeRightPanel} className="p-1.5 hover:bg-zinc-800 rounded-lg">
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12" /></svg>
                </button>
              </div>
              <div className="flex-1 overflow-hidden min-h-0">
                <Suspense fallback={<LazyLoadSpinner />}>
                  <QueueView />
                </Suspense>
              </div>
            </div>
          </div>
        )}

        {/* PWA install prompt */}
        <InstallPrompt />
        <OfflineIndicator />

        {/* Keyboard shortcuts help */}
        {showShortcutsHelp && (
          <ShortcutsHelp onClose={() => setShowShortcutsHelp(false)} />
        )}

        {/* Track edit modal */}
        {editingTrackId && <TrackEditModal />}

        {/* Playlist picker modal */}
        {playlistPickerTrackIds && <PlaylistPickerModal trackIds={playlistPickerTrackIds} />}

        {/* Import modal */}
        {importFiles && (
          <ImportModal
            files={importFiles}
            onClose={() => {
              setImportFiles(null);
              queryClient.refetchQueries({ queryKey: ['tracks'] });
            }}
          />
        )}
      </div>
    </GlobalDropZone>
  );
}
