/**
 * AppShell — persistent layout for the administration tool.
 *
 * Renders: TopBar over <Outlet />.
 *
 * **Nothing here constructs an audio engine.** The shell used to mount a player bar, a
 * queue/session right panel, a full-player overlay and an ambient overlay, and `useAppBootstrap`
 * built an audio engine, a scrobbler and a play tracker on every page load — in a tool whose job is
 * scanning a library and reading server health. All of it went with the fallback player
 * (ADR-0058 point 4's trigger, ADR-0070, ADR-0071).
 *
 * This is the same property `renderEmbed.tsx` gives the embedded surfaces and for the same reason:
 * hiding a player is not the same as not having one.
 *
 * **One responsive layout, not two** (ADR-0080 point 1). The sidebar-on-desktop /
 * bottom-bar-on-mobile split is gone along with `ContentToolbar`, whose search box and column
 * chooser rendered only under `/library/*` — where the one mounted route reads neither.
 */
import { useRef } from 'react';
import { Outlet } from 'react-router-dom';
import { ScrollContainerContext } from '../hooks/useScrollContainer';
import { useLastfmCallback } from '../hooks/useLastfmCallback';
import { useUIStore } from '../stores/uiStore';
import { useSelectionStore } from '../stores/selectionStore';
import { TopBar } from './TopBar';
import { ErrorBoundary } from './ErrorBoundary';
import { OfflineIndicator } from './PWA/OfflineIndicator';
import { TrackEditModal } from './TrackEdit';
import { PlaylistPickerModal } from './Playlists/PlaylistPickerModal';

export function AppShell() {
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const editingTrackId = useSelectionStore((state) => state.editingTrackId);
  const playlistPickerTrackIds = useUIStore((s) => s.playlistPickerTrackIds);

  // Handle Last.fm OAuth callback token in URL
  useLastfmCallback();

  return (
      <div className="h-dynamic-screen flex flex-col select-none bg-black text-white pt-safe-top">
        <TopBar />

        <main className="flex-1 flex flex-col overflow-hidden min-h-0 bg-gradient-to-b from-zinc-900 to-black">
          <ScrollContainerContext.Provider value={scrollContainerRef}>
            <div ref={scrollContainerRef} className="flex-1 overflow-y-auto overflow-x-hidden min-h-0">
              <ErrorBoundary name="Screen">
                <Outlet />
              </ErrorBoundary>
            </div>
          </ScrollContainerContext.Provider>
        </main>

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
