import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface UIState {
  /** Which right panel is open, if any. Queue and Chat are mutually exclusive. */
  rightPanel: 'queue' | 'chat' | null;
  /** Whether the settings modal is showing */
  showSettings: boolean;
  /** Whether the sidebar is collapsed to icon-only mode */
  sidebarCollapsed: boolean;
  /** Whether the full player overlay is showing */
  showFullPlayer: boolean;
  /** Pending chat message to send when chat panel opens */
  pendingChatMessage: string | null;
  /** Track IDs to show in playlist picker modal */
  playlistPickerTrackIds: string[] | null;

  // Actions
  toggleRightPanel: (panel: 'queue' | 'chat') => void;
  closeRightPanel: () => void;
  setShowSettings: (show: boolean) => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setShowFullPlayer: (show: boolean) => void;
  /** Set a pending chat message and open the chat panel */
  triggerChat: (message: string) => void;
  /** Read and clear the pending chat message */
  consumePendingChatMessage: () => string | null;
  /** Open the playlist picker for the given track IDs */
  openPlaylistPicker: (trackIds: string[]) => void;
  /** Close the playlist picker */
  closePlaylistPicker: () => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set, get) => ({
      rightPanel: null,
      showSettings: false,
      sidebarCollapsed: false,
      showFullPlayer: false,
      pendingChatMessage: null,
      playlistPickerTrackIds: null,

      toggleRightPanel: (panel) => {
        const current = get().rightPanel;
        set({ rightPanel: current === panel ? null : panel });
      },
      closeRightPanel: () => set({ rightPanel: null }),
      setShowSettings: (show) => set({ showSettings: show }),
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
      setShowFullPlayer: (show) => set({ showFullPlayer: show }),
      triggerChat: (message) => set({ pendingChatMessage: message, rightPanel: 'chat' }),
      consumePendingChatMessage: () => {
        const msg = get().pendingChatMessage;
        if (msg) set({ pendingChatMessage: null });
        return msg;
      },
      openPlaylistPicker: (trackIds) => set({ playlistPickerTrackIds: trackIds }),
      closePlaylistPicker: () => set({ playlistPickerTrackIds: null }),
    }),
    {
      name: 'familiar-ui',
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
      }),
    }
  )
);
