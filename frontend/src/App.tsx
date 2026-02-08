import { useState, useEffect, useCallback, useRef, lazy, Suspense } from 'react';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { Toaster } from 'sonner';
import { TAB_PARAM_WHITELIST, type AppTab } from './utils/urlParams';
import { Search, Library, Settings, Zap, MessageSquare, X, Loader2, ListMusic } from 'lucide-react';
import { createLogger } from './utils/logger';

const log = createLogger('App');
import { PlayerBar } from './components/Player/PlayerBar';
import { LibraryView } from './components/Library';
import { ChatPanel } from './components/Chat';
import { InstallPrompt } from './components/PWA/InstallPrompt';
import { OfflineIndicator } from './components/PWA/OfflineIndicator';
import { ShortcutsHelp } from './components/KeyboardShortcuts';
import { ProfileSelector } from './components/Profiles';
import { HealthIndicator } from './components/HealthIndicator';
import { BackgroundJobsIndicator } from './components/BackgroundJobsIndicator';
import { ProposedChangesIndicator } from './components/ProposedChangesIndicator';
import { DownloadIndicator } from './components/DownloadIndicator';
import { WorkerAlert } from './components/WorkerAlert';
import { GlobalDropZone, ImportModal } from './components/Import';
import { ColumnSelector } from './components/Library/ColumnSelector';
import { ErrorBoundary } from './components/ErrorBoundary';

// Lazy-loaded components for code splitting
const SettingsPanel = lazy(() => import('./components/Settings').then(m => ({ default: m.SettingsPanel })));
const FullPlayer = lazy(() => import('./components/FullPlayer').then(m => ({ default: m.FullPlayer })));
const PlaylistsView = lazy(() => import('./components/Playlists').then(m => ({ default: m.PlaylistsView })));
const QueueView = lazy(() => import('./components/Queue').then(m => ({ default: m.QueueView })));
const AdminSetup = lazy(() => import('./components/Admin').then(m => ({ default: m.AdminSetup })));

// Loading spinner for lazy components
function LazyLoadSpinner() {
  return (
    <div role="status" aria-label="Loading" className="flex items-center justify-center py-20">
      <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
    </div>
  );
}
import { useScrobbling } from './hooks/useScrobbling';
import { usePlayTracking } from './hooks/usePlayTracking';
import { useMetadataEnrichment } from './hooks/useMetadataEnrichment';
// Listening sessions disabled for v0.1.0
// import { useListeningSession } from './hooks/useListeningSession';
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts';
import { initSyncListeners } from './services/syncService';
import { pluginLoader } from './services/pluginLoader';
import { useAudioEngine } from './hooks/useAudioEngine';
import { usePlayerStore } from './stores/playerStore';
import { useSelectionStore } from './stores/selectionStore';
import { useThemeStore } from './stores/themeStore';
import { TrackEditModal } from './components/TrackEdit';
import { initializeProfile, type Profile } from './services/profileService';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1,
    },
  },
});

type RightPanelTab = AppTab;

function AppContent() {
  const [search, setSearch] = useState('');
  const [importFiles, setImportFiles] = useState<File[] | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();

  // Triple-tap recovery mechanism for mobile (closes all overlays)
  const tapCountRef = useRef(0);
  const lastTapTimeRef = useRef(0);
  useEffect(() => {
    const handleTripleTap = () => {
      const now = Date.now();
      if (now - lastTapTimeRef.current < 500) {
        tapCountRef.current++;
        if (tapCountRef.current >= 3) {
          // Triple tap detected - close all overlays
          log.info('[AppContent] Triple-tap recovery triggered');
          setShowFullPlayer(false);
          setShowMobileChat(false);
          setShowChatPanel(false);
          setShowShortcutsHelp(false);
          tapCountRef.current = 0;
        }
      } else {
        tapCountRef.current = 1;
      }
      lastTapTimeRef.current = now;
    };

    // Only add on touch devices
    if ('ontouchstart' in window) {
      document.addEventListener('touchstart', handleTripleTap);
      return () => document.removeEventListener('touchstart', handleTripleTap);
    }
  }, []);

  // Determine initial tab from URL hash or path
  const getTabFromUrl = (): RightPanelTab => {
    // Check hash first (e.g., #settings, #playlists)
    const hash = window.location.hash.slice(1); // Remove #
    if (hash === 'settings' || hash === 'playlists' || hash === 'library' || hash === 'queue') {
      return hash;
    }
    // Fall back to pathname (e.g., /settings from OAuth callback)
    const path = window.location.pathname;
    log.debug('[AppContent] getTabFromUrl, hash:', hash, 'path:', path);
    if (path === '/settings') return 'settings';
    if (path === '/playlists') return 'playlists';
    if (path === '/queue') return 'queue';

    // Check for playlist-specific view params (downloads, favorites, wishlist)
    // These belong to the playlists tab even without the hash
    const searchParams = new URLSearchParams(window.location.search);
    const view = searchParams.get('view');
    if (view === 'downloads' || view === 'favorites' || view === 'wishlist') {
      return 'playlists';
    }
    // Also check for playlist or smartPlaylist params
    if (searchParams.get('playlist') || searchParams.get('smartPlaylist')) {
      return 'playlists';
    }

    return 'library';
  };

  const [rightPanelTab, setRightPanelTabState] = useState<RightPanelTab>(() => {
    const tab = getTabFromUrl();
    log.debug('[AppContent] Initial tab set to:', tab);
    return tab;
  });

  // Wrap setRightPanelTab to also update URL hash and clear irrelevant params
  const setRightPanelTab = useCallback((tab: RightPanelTab) => {
    setRightPanelTabState(tab);

    // Clear params that don't belong to the new tab using centralized whitelist
    const currentParams = new URLSearchParams(window.location.search);
    const allowedParams = new Set(TAB_PARAM_WHITELIST[tab]);

    for (const key of Array.from(currentParams.keys())) {
      if (!allowedParams.has(key)) {
        currentParams.delete(key);
      }
    }

    // Build new URL with hash and cleaned params using React Router
    const paramString = currentParams.toString();
    const newUrl = paramString ? `?${paramString}#${tab}` : `#${tab}`;
    navigate(newUrl, { replace: true });
  }, [navigate]);

  // Sync tab state with URL changes (works for both programmatic and browser navigation)
  useEffect(() => {
    const tab = getTabFromUrl();
    setRightPanelTabState(tab);
  }, [location]);
  const [showFullPlayer, setShowFullPlayer] = useState(false);
  const [fullPlayerMounted, setFullPlayerMounted] = useState(false);

  // Mount FullPlayer on first open, keep mounted for slide animation
  useEffect(() => {
    if (showFullPlayer && !fullPlayerMounted) {
      setFullPlayerMounted(true);
    }
  }, [showFullPlayer, fullPlayerMounted]);

  // Listening sessions disabled for v0.1.0
  // const [showSessionPanel, setShowSessionPanel] = useState(false);
  const [showShortcutsHelp, setShowShortcutsHelp] = useState(false);
  const [showMobileChat, setShowMobileChat] = useState(false);
  const [showQueuePanel, setShowQueuePanel] = useState(false);
  const [showChatPanel, setShowChatPanel] = useState(false);
  const [mobileSearchExpanded, setMobileSearchExpanded] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Initialize Audio Engine (must be here to persist across navigation)
  useAudioEngine();

  // Initialize Last.fm scrobbling
  useScrobbling();

  // Initialize local play history tracking
  usePlayTracking();

  // Initialize automatic metadata enrichment
  useMetadataEnrichment();

  // Initialize keyboard shortcuts
  useKeyboardShortcuts({
    onToggleFullPlayer: () => setShowFullPlayer((prev) => !prev),
    onShowHelp: () => setShowShortcutsHelp(true),
    onEscape: () => {
      // Close overlays in order of priority
      if (showShortcutsHelp) {
        setShowShortcutsHelp(false);
      } else if (showFullPlayer) {
        setShowFullPlayer(false);
      } else if (showMobileChat) {
        setShowMobileChat(false);
      } else if (showChatPanel) {
        setShowChatPanel(false);
      }
    },
  });

  // Initialize offline sync listeners
  useEffect(() => {
    const cleanup = initSyncListeners();
    return cleanup;
  }, []);

  // Listen for navigate-to-settings event from HealthIndicator
  useEffect(() => {
    const handleNavigateToSettings = () => {
      setRightPanelTab('settings');
    };
    window.addEventListener('navigate-to-settings', handleNavigateToSettings);
    return () => window.removeEventListener('navigate-to-settings', handleNavigateToSettings);
  }, [setRightPanelTab]);

  // Listen for show-playlist event from ChatPanel when LLM creates a playlist
  const [selectedPlaylistId, setSelectedPlaylistId] = useState<string | null>(null);
  useEffect(() => {
    const handleShowPlaylist = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.playlistId) {
        setSelectedPlaylistId(detail.playlistId);
        setRightPanelTab('playlists');
      }
    };
    window.addEventListener('show-playlist', handleShowPlaylist);
    return () => window.removeEventListener('show-playlist', handleShowPlaylist);
  }, [setRightPanelTab]);

  // Listen for show-ephemeral-playlist event when LLM creates an ephemeral playlist
  useEffect(() => {
    const handleShowEphemeralPlaylist = () => {
      // Just switch to playlists tab - the unsaved section will show automatically
      setRightPanelTab('playlists');
    };
    window.addEventListener('show-ephemeral-playlist', handleShowEphemeralPlaylist);
    return () => window.removeEventListener('show-ephemeral-playlist', handleShowEphemeralPlaylist);
  }, [setRightPanelTab]);

  // Listen for trigger-chat event from context menus (e.g., "Make Playlist From This Track")
  const [pendingChatMessage, setPendingChatMessage] = useState<string | null>(null);
  useEffect(() => {
    const handleTriggerChat = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.message) {
        setPendingChatMessage(detail.message);
        // Open the appropriate chat panel based on viewport
        if (window.innerWidth >= 768) {
          setShowChatPanel(true);
        } else {
          setShowMobileChat(true);
        }
      }
    };
    window.addEventListener('trigger-chat', handleTriggerChat);
    return () => window.removeEventListener('trigger-chat', handleTriggerChat);
  }, []);

  // Hydrate player state from IndexedDB
  const hydrate = usePlayerStore((state) => state.hydrate);
  useEffect(() => {
    hydrate();
  }, [hydrate]);

  // Listening sessions disabled for v0.1.0 - re-enable when signaling server is ready
  // const userId = 'user-' + (localStorage.getItem('familiar-user-id') || (() => {
  //   const id = Math.random().toString(36).substring(7);
  //   localStorage.setItem('familiar-user-id', id);
  //   return id;
  // })());
  // const username = localStorage.getItem('familiar-username') || 'Anonymous';
  // const {
  //   session,
  //   isConnecting,
  //   error: sessionError,
  //   chatMessages,
  //   isHost,
  //   createSession,
  //   joinSession,
  //   leaveSession,
  //   sendChatMessage,
  // } = useListeningSession({ userId, username });

  // Get resolved theme for conditional styling
  const resolvedTheme = useThemeStore((state) => state.resolvedTheme);

  // Track edit modal state
  const editingTrackId = useSelectionStore((state) => state.editingTrackId);

  return (
    <GlobalDropZone onFilesDropped={setImportFiles}>
      {/* Use h-dvh for iOS dynamic viewport, fallback to h-screen */}
      <div className={`h-screen h-[100dvh] flex flex-col select-none ${resolvedTheme === 'light' ? 'bg-white text-zinc-900' : 'bg-black text-white'}`}>
        {/* Main content area - pb-24 on mobile accounts for fixed player bar + safe area */}
        <div className="flex-1 flex overflow-hidden pb-20 md:pb-20">
          {/* Left panel - Chat (hidden on mobile, shown via overlay; desktop slides in when toggled) */}
          {showChatPanel && (
            <div className={`hidden md:flex w-96 border-r ${resolvedTheme === 'light' ? 'border-zinc-200 bg-white' : 'border-zinc-800 bg-zinc-900'} flex-col`}>
              <div className={`flex items-center justify-between p-4 border-b ${resolvedTheme === 'light' ? 'border-zinc-200' : 'border-zinc-800'}`}>
                <h2 className="font-semibold">AI Assistant</h2>
                <button
                  onClick={() => setShowChatPanel(false)}
                  className={`p-1.5 rounded-lg transition-colors ${resolvedTheme === 'light' ? 'hover:bg-zinc-100' : 'hover:bg-zinc-800'}`}
                  aria-label="Close chat panel"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="flex-1 overflow-hidden">
                <ErrorBoundary name="Chat">
                  <ChatPanel
                    pendingMessage={pendingChatMessage}
                    onPendingMessageConsumed={() => setPendingChatMessage(null)}
                  />
                </ErrorBoundary>
              </div>
            </div>
          )}

          {/* Mobile chat overlay */}
          {showMobileChat && (
            <div className="md:hidden fixed inset-0 z-50 flex">
              {/* Backdrop */}
              <div
                className="absolute inset-0 bg-black/50"
                onClick={() => setShowMobileChat(false)}
              />
              {/* Chat panel - includes safe area padding */}
              <div className={`relative w-full max-w-md ${resolvedTheme === 'light' ? 'bg-white' : 'bg-zinc-900'} flex flex-col pt-safe pb-safe`}>
                <ErrorBoundary name="Chat">
                  <ChatPanel
                    pendingMessage={pendingChatMessage}
                    onPendingMessageConsumed={() => setPendingChatMessage(null)}
                    onClose={() => setShowMobileChat(false)}
                  />
                </ErrorBoundary>
              </div>
            </div>
          )}

          {/* Right panel - Library/Context */}
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Header with tabs - includes safe area padding for notch */}
            <header className={`relative z-30 backdrop-blur-md border-b pt-safe ${resolvedTheme === 'light' ? 'bg-white/80 border-zinc-200' : 'bg-zinc-900/80 border-zinc-800'}`}>
              <div className="px-4 py-3 flex items-center gap-2 md:gap-4">
                {/* Mobile search expanded state - takes over header */}
                {mobileSearchExpanded ? (
                  <div className="flex-1 flex items-center gap-2 md:hidden">
                    <div className="flex-1 relative">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
                      <input
                        ref={searchInputRef}
                        type="search"
                        inputMode="search"
                        placeholder="Search tracks..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        onBlur={() => {
                          // Delay to allow tap on X button
                          setTimeout(() => setMobileSearchExpanded(false), 150);
                        }}
                        className="w-full pl-10 pr-4 py-2 bg-zinc-800 border border-zinc-700 rounded-full text-base placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent"
                        autoFocus
                      />
                    </div>
                    <button
                      onClick={() => {
                        setSearch('');
                        setMobileSearchExpanded(false);
                      }}
                      className="p-2 rounded-lg text-zinc-400 hover:text-white"
                      aria-label="Cancel search"
                    >
                      <X className="w-5 h-5" />
                    </button>
                  </div>
                ) : (
                  <>
                    {/* Chat toggle - mobile opens overlay, desktop toggles slide-in panel */}
                    <button
                      onClick={() => {
                        if (window.innerWidth >= 768) {
                          setShowChatPanel(!showChatPanel);
                        } else {
                          setShowMobileChat(true);
                        }
                      }}
                      className={`px-2 sm:px-3 py-1.5 text-sm rounded-md transition-colors whitespace-nowrap ${showChatPanel
                        ? 'bg-zinc-800 text-white'
                        : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
                        }`}
                      aria-label={showChatPanel ? 'Close chat' : 'Open chat'}
                      title="AI Assistant"
                    >
                      <MessageSquare className="w-4 h-4 inline-block sm:mr-1.5" />
                      <span className="hidden sm:inline">Chat</span>
                    </button>

                    {/* Tabs */}
                    <div className="flex gap-1 overflow-x-auto">
                      <button
                        onClick={() => setRightPanelTab('library')}
                        className={`px-2 sm:px-3 py-1.5 text-sm rounded-md transition-colors whitespace-nowrap ${rightPanelTab === 'library'
                          ? 'bg-zinc-800 text-white'
                          : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
                          }`}
                        aria-label="Library"
                      >
                        <Library className="w-4 h-4 inline-block sm:mr-1.5" />
                        <span className="hidden sm:inline">Library</span>
                      </button>
                      <button
                        onClick={() => setRightPanelTab('playlists')}
                        className={`px-2 sm:px-3 py-1.5 text-sm rounded-md transition-colors whitespace-nowrap ${rightPanelTab === 'playlists'
                          ? 'bg-zinc-800 text-white'
                          : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
                          }`}
                        aria-label="Playlists"
                      >
                        <Zap className="w-4 h-4 inline-block sm:mr-1.5" />
                        <span className="hidden sm:inline">Playlists</span>
                      </button>
                      <button
                        onClick={() => {
                          // Desktop: toggle docked panel; Mobile: use tab
                          if (window.innerWidth >= 768) {
                            setShowQueuePanel(!showQueuePanel);
                          } else {
                            setRightPanelTab('queue');
                          }
                        }}
                        className={`px-2 sm:px-3 py-1.5 text-sm rounded-md transition-colors whitespace-nowrap ${rightPanelTab === 'queue' || showQueuePanel
                          ? 'bg-zinc-800 text-white'
                          : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
                          }`}
                        aria-label="Queue"
                      >
                        <ListMusic className="w-4 h-4 inline-block sm:mr-1.5" />
                        <span className="hidden sm:inline">Queue</span>
                      </button>
                      <button
                        onClick={() => setRightPanelTab('settings')}
                        className={`px-2 sm:px-3 py-1.5 text-sm rounded-md transition-colors whitespace-nowrap ${rightPanelTab === 'settings'
                          ? 'bg-zinc-800 text-white'
                          : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
                          }`}
                        aria-label="Settings"
                      >
                        <Settings className="w-4 h-4 inline-block sm:mr-1.5" />
                        <span className="hidden sm:inline">Settings</span>
                      </button>
                    </div>

                    {/* Mobile search icon (library view only) */}
                    {rightPanelTab === 'library' && (
                      <button
                        onClick={() => {
                          setMobileSearchExpanded(true);
                          // Focus will happen via autoFocus
                        }}
                        className="md:hidden p-2 rounded-lg text-zinc-400 hover:text-white hover:bg-zinc-800/50"
                        aria-label="Search"
                      >
                        <Search className="w-5 h-5" />
                      </button>
                    )}

                    {/* Desktop search and column selector (only in library view) */}
                    {rightPanelTab === 'library' && (
                      <>
                        <div className="hidden md:block flex-1 max-w-md">
                          <div className="relative">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
                            <input
                              type="search"
                              placeholder="Search tracks..."
                              value={search}
                              onChange={(e) => setSearch(e.target.value)}
                              className="w-full pl-10 pr-4 py-2 bg-zinc-800 border border-zinc-700 rounded-full text-base placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent"
                            />
                          </div>
                        </div>
                        <div className="hidden md:block">
                          <ColumnSelector />
                        </div>
                      </>
                    )}

                    {/* Spacer to push indicators right */}
                    <div className="flex-1" />

                    {/* Download progress indicator - shows when downloads are in progress */}
                    <DownloadIndicator />

                    {/* Proposed changes indicator - shows when changes need review */}
                    <ProposedChangesIndicator />

                    {/* Background jobs indicator - shows when jobs are running */}
                    <BackgroundJobsIndicator />

                    {/* Health indicator - only shows when issues detected */}
                    <HealthIndicator />
                  </>
                )}
              </div>
            </header>

            {/* Content */}
            <main className={`flex-1 overflow-y-auto ${resolvedTheme === 'light' ? 'bg-gradient-to-b from-zinc-50 to-white' : 'bg-gradient-to-b from-zinc-900 to-black'}`}>
              {rightPanelTab === 'library' && (
                <div className="md:h-full md:min-h-0">
                  <LibraryView initialSearch={search || undefined} />
                </div>
              )}
              {rightPanelTab === 'playlists' && (
                <div className="px-4 py-6">
                  <Suspense fallback={<LazyLoadSpinner />}>
                    <PlaylistsView
                      selectedPlaylistId={selectedPlaylistId}
                      onPlaylistViewed={() => setSelectedPlaylistId(null)}
                    />
                  </Suspense>
                </div>
              )}
              {/* Queue tab content - only show on mobile; desktop uses docked panel */}
              {rightPanelTab === 'queue' && (
                <div className="h-full md:hidden">
                  <Suspense fallback={<LazyLoadSpinner />}>
                    <QueueView />
                  </Suspense>
                </div>
              )}
              {rightPanelTab === 'settings' && (
                <Suspense fallback={<LazyLoadSpinner />}>
                  <SettingsPanel />
                </Suspense>
              )}
            </main>
          </div>

          {/* Right panel - Queue (desktop only, docked) */}
          {showQueuePanel && (
            <div className={`hidden md:flex w-80 border-l ${resolvedTheme === 'light' ? 'border-zinc-200 bg-white' : 'border-zinc-800 bg-zinc-900'} flex-col`}>
              <div className={`flex items-center justify-between p-4 border-b ${resolvedTheme === 'light' ? 'border-zinc-200' : 'border-zinc-800'}`}>
                <h2 className="font-semibold">Queue</h2>
                <button
                  onClick={() => setShowQueuePanel(false)}
                  className={`p-1.5 rounded-lg transition-colors ${resolvedTheme === 'light' ? 'hover:bg-zinc-100' : 'hover:bg-zinc-800'}`}
                  aria-label="Close queue panel"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="flex-1 overflow-hidden">
                <Suspense fallback={<LazyLoadSpinner />}>
                  <QueueView />
                </Suspense>
              </div>
            </div>
          )}
        </div>

        {/* Player bar - fixed at bottom */}
        <ErrorBoundary name="Player">
          <PlayerBar
            onExpandClick={() => setShowFullPlayer(true)}
          // Listening sessions disabled for v0.1.0
          />
        </ErrorBoundary>

        {/* Full player overlay - mounted once, slides up/down */}
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

        {/* PWA install prompt */}
        <InstallPrompt />

        {/* Offline indicator */}
        <OfflineIndicator />

        {/* Listening sessions disabled for v0.1.0 - re-enable when signaling server is ready */}

        {/* Keyboard shortcuts help */}
        {showShortcutsHelp && (
          <ShortcutsHelp onClose={() => setShowShortcutsHelp(false)} />
        )}

        {/* Track edit modal */}
        {editingTrackId && <TrackEditModal />}

        {/* Import modal */}
        {importFiles && (
          <ImportModal
            files={importFiles}
            onClose={() => {
              setImportFiles(null);
              // Refetch tracks after modal closes
              queryClient.refetchQueries({ queryKey: ['tracks'] });
            }}
          />
        )}
      </div>
    </GlobalDropZone>
  );
}

// PWA Reset utility - clears all persisted state
function resetPWAState() {
  log.info('[App] Resetting PWA state');
  // Clear all localStorage keys for this app
  const keysToRemove = Object.keys(localStorage).filter(
    (k) => k.startsWith('familiar-') || k.startsWith('zustand-')
  );
  keysToRemove.forEach((k) => localStorage.removeItem(k));

  // Clear IndexedDB databases
  if ('indexedDB' in window) {
    indexedDB.databases?.().then((dbs) => {
      dbs.forEach((db) => {
        if (db.name) {
          indexedDB.deleteDatabase(db.name);
        }
      });
    });
  }

  // Clear URL state
  window.history.replaceState(null, '', window.location.pathname);

  // Reload to apply clean state
  window.location.reload();
}

// Expose reset function globally for debugging
if (typeof window !== 'undefined') {
  (window as unknown as { resetFamiliar: () => void }).resetFamiliar = resetPWAState;
}

function App() {
  const [profile, setProfile] = useState<Profile | null | undefined>(undefined);
  const [checkingProfile, setCheckingProfile] = useState(true);

  // Check for reset parameter in URL
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('reset') === 'true') {
      resetPWAState();
    }
  }, []);

  const checkProfile = useCallback(async () => {
    setCheckingProfile(true);
    try {
      // Add timeout to prevent hanging on iOS when IndexedDB/Dexie gets stuck
      const timeoutPromise = new Promise<null>((resolve) => {
        setTimeout(() => {
          log.warn('[App] Profile initialization timed out - IndexedDB may be unavailable');
          resolve(null);
        }, 5000);
      });

      const p = await Promise.race([
        initializeProfile(),
        timeoutPromise,
      ]);
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

    // Listen for profile invalidation events (from API client)
    const handleInvalidated = () => {
      setProfile(null);
    };
    window.addEventListener('profile-invalidated', handleInvalidated);

    return () => {
      window.removeEventListener('profile-invalidated', handleInvalidated);
    };
  }, [checkProfile]);

  // Initialize plugin system and load plugins
  useEffect(() => {
    // Initialize the global Familiar API for plugins
    pluginLoader.initializeGlobalAPI();

    // Load all enabled plugins
    pluginLoader.loadAllPlugins().catch((err) => {
      log.error('Failed to load plugins:', err);
    });
  }, []);

  // Show loading spinner while checking profile
  if (checkingProfile) {
    return (
      <div role="status" aria-label="Loading" className="min-h-screen bg-zinc-950 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  // Check if we're on /admin route - allow access without profile for initial setup
  const isAdminRoute = window.location.pathname === '/admin';

  // Show profile selector if no profile selected (unless on admin route)
  if (profile === null && !isAdminRoute) {
    return (
      <ProfileSelector
        onProfileSelected={(p) => {
          setProfile(p);
        }}
      />
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
        <Routes>
          <Route path="/admin" element={
            <Suspense fallback={<LazyLoadSpinner />}>
              <AdminSetup />
            </Suspense>
          } />
          {/* Listening sessions disabled for v0.1.0 */}
          {/* <Route path="/guest" element={<GuestListener />} /> */}
          <Route path="*" element={<AppContent />} />
        </Routes>
      </QueryClientProvider>
    </BrowserRouter>
  );
}

export default App;
