import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface UIState {
  /** Which right panel is open, if any. Queue and Session are mutually exclusive. */
  rightPanel: 'queue' | 'session' | null;
  /** Whether the settings modal is showing */
  showSettings: boolean;
  /** Whether the sidebar is collapsed to icon-only mode */
  sidebarCollapsed: boolean;
  /** Whether the full player overlay is showing */
  showFullPlayer: boolean;
  /** Track IDs to show in playlist picker modal */
  playlistPickerTrackIds: string[] | null;
  /** Whether the ambient screen overlay is showing */
  showAmbientScreen: boolean;

  // Actions
  toggleRightPanel: (panel: 'queue' | 'session') => void;
  closeRightPanel: () => void;
  setShowSettings: (show: boolean) => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setShowFullPlayer: (show: boolean) => void;
  /** Open the playlist picker for the given track IDs */
  openPlaylistPicker: (trackIds: string[]) => void;
  /** Close the playlist picker */
  closePlaylistPicker: () => void;
  setShowAmbientScreen: (show: boolean) => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set, get) => ({
      rightPanel: null,
      showSettings: false,
      sidebarCollapsed: false,
      showFullPlayer: false,
      playlistPickerTrackIds: null,
      showAmbientScreen: false,

      toggleRightPanel: (panel) => {
        const current = get().rightPanel;
        set({ rightPanel: current === panel ? null : panel });
      },
      closeRightPanel: () => set({ rightPanel: null }),
      setShowSettings: (show) => set({ showSettings: show }),
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
      setShowFullPlayer: (show) => set({ showFullPlayer: show }),
      openPlaylistPicker: (trackIds) => set({ playlistPickerTrackIds: trackIds }),
      closePlaylistPicker: () => set({ playlistPickerTrackIds: null }),
      setShowAmbientScreen: (show) => set({ showAmbientScreen: show }),
    }),
    {
      name: 'familiar-ui',
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
      }),
    }
  )
);
