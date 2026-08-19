/**
 * AppShell — persistent layout for the administration tool.
 *
 * Renders: Sidebar | <Outlet />, with the mobile nav below.
 *
 * **Nothing here constructs an audio engine.** The shell used to mount a player bar, a
 * queue/session right panel, a full-player overlay and an ambient overlay, and `useAppBootstrap`
 * built an audio engine, a scrobbler and a play tracker on every page load — in a tool whose job is
 * scanning a library and reading server health. All of it went with the fallback player
 * (ADR-0058 point 4's trigger, ADR-0070, ADR-0071).
 *
 * This is the same property `renderEmbed.tsx` gives the embedded surfaces and for the same reason:
 * hiding a player is not the same as not having one.
 */
import { useRef } from 'react';
import { Outlet } from 'react-router-dom';
import { ScrollContainerContext } from '../hooks/useScrollContainer';
import { useLastfmCallback } from '../hooks/useLastfmCallback';
import { useUIStore } from '../stores/uiStore';
import { useSelectionStore } from '../stores/selectionStore';
import { useThemeStore } from '../stores/themeStore';
import { Sidebar } from './Sidebar/Sidebar';
import { ContentToolbar } from './ContentToolbar';
import { ErrorBoundary } from './ErrorBoundary';
import { OfflineIndicator } from './PWA/OfflineIndicator';
import { TrackEditModal } from './TrackEdit';
import { MobileBottomNav } from './MobileNav';
import { PlaylistPickerModal } from './Playlists/PlaylistPickerModal';

export function AppShell() {
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const resolvedTheme = useThemeStore((state) => state.resolvedTheme);
  const editingTrackId = useSelectionStore((state) => state.editingTrackId);
  const playlistPickerTrackIds = useUIStore((s) => s.playlistPickerTrackIds);

  // Handle Last.fm OAuth callback token in URL
  useLastfmCallback();

  return (
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
            <ScrollContainerContext.Provider value={scrollContainerRef}>
              <div ref={scrollContainerRef} className="flex-1 overflow-y-auto overflow-x-hidden min-h-0">
                <ErrorBoundary name="Screen">
                  <Outlet />
                </ErrorBoundary>
              </div>
            </ScrollContainerContext.Provider>
          </main>
        </div>

        {/* Mobile bottom nav - fixed at very bottom on small screens */}
        <MobileBottomNav />

        {/* No install prompt: ADR-0059 retired the PWA. The OfflineIndicator stays — it reports
            that the *server* is unreachable, which an administration tool needs to say. */}
        <OfflineIndicator />

        {/* Track edit modal */}
        {editingTrackId && <TrackEditModal />}

        {/* Playlist picker modal */}
        {playlistPickerTrackIds && <PlaylistPickerModal trackIds={playlistPickerTrackIds} />}

      </div>
  );
}
