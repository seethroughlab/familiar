/**
 * What is left of the UI store.
 *
 * It held eight fields for a music player's chrome. `rightPanel` (queue/session), `showFullPlayer`
 * and `showAmbientScreen` lost their last readers when the player went (ADR-0070, ADR-0071);
 * `showSettings` was set by the mobile "More" sheet and read by nothing at all; `sidebarCollapsed`
 * went with the sidebar (ADR-0080 point 1). All of them are deleted rather than documented, per
 * ADR-0077.
 *
 * `sidebarCollapsed` was also the only key in `partialize`, so the `persist` wrapper and the
 * `familiar-ui` localStorage key go with it — what remains is one modal's transient state, which
 * has no business surviving a reload.
 */
import { create } from 'zustand';

interface UIState {
  /** Track IDs to show in playlist picker modal */
  playlistPickerTrackIds: string[] | null;

  /** Open the playlist picker for the given track IDs */
  openPlaylistPicker: (trackIds: string[]) => void;
  /** Close the playlist picker */
  closePlaylistPicker: () => void;
}

export const useUIStore = create<UIState>()((set) => ({
  playlistPickerTrackIds: null,

  openPlaylistPicker: (trackIds) => set({ playlistPickerTrackIds: trackIds }),
  closePlaylistPicker: () => set({ playlistPickerTrackIds: null }),
}));
