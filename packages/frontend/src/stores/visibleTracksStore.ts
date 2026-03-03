/**
 * Store for tracking which tracks are currently visible in the library view.
 * This allows the LLM to access the current view context.
 */
import { create } from 'zustand';

interface VisibleTrack {
  id: string;
  title: string;
  artist: string;
  album: string;
}

interface VisibleTracksState {
  /** Track IDs currently visible in the track list */
  trackIds: string[];

  /** Basic info about visible tracks (for LLM context) */
  tracks: VisibleTrack[];

  /** Total count of tracks matching current filters (may be more than loaded) */
  totalCount: number;

  /** Current filter description (for LLM context) */
  filterDescription: string;

  /** Actions */
  setVisibleTracks: (tracks: VisibleTrack[], totalCount: number, filterDescription?: string) => void;
  clear: () => void;
}

export const useVisibleTracksStore = create<VisibleTracksState>()((set) => ({
  trackIds: [],
  tracks: [],
  totalCount: 0,
  filterDescription: '',

  setVisibleTracks: (tracks, totalCount, filterDescription = '') =>
    set({
      trackIds: tracks.map((t) => t.id),
      tracks,
      totalCount,
      filterDescription,
    }),

  clear: () =>
    set({
      trackIds: [],
      tracks: [],
      totalCount: 0,
      filterDescription: '',
    }),
}));
