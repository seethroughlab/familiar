/**
 * Tracks in-flight Mix Tape renders so a global watcher can poll for status
 * and toast the user when each one is ready (or failed).
 *
 * Two layers:
 *   1. tracked ids — set by ExportMixTapeModal after a successful POST,
 *      cleared once the render reaches a terminal state.
 *   2. <MixTapeProgressWatcher /> — mounted at app shell level, polls
 *      each tracked id every 2s.
 */
import { create } from 'zustand';

interface MixTapesState {
  trackedIds: string[];
  add: (id: string) => void;
  remove: (id: string) => void;
}

export const useMixTapesStore = create<MixTapesState>((set, get) => ({
  trackedIds: [],
  add: (id) => {
    if (get().trackedIds.includes(id)) return;
    set({ trackedIds: [...get().trackedIds, id] });
  },
  remove: (id) => {
    set({ trackedIds: get().trackedIds.filter((x) => x !== id) });
  },
}));

/** Convenience used by the export modal — keeps callers from importing the store directly. */
export function trackMixTape(id: string): void {
  useMixTapesStore.getState().add(id);
}
