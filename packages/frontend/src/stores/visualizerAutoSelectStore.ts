/**
 * What auto-select decided, for this run (ADR-0064 points 3 and 7).
 *
 * **Deliberately not persisted**, for the reason its sibling `visualizerPluginStore` gives: every
 * fact here is about the track playing now and the plugins present now. A choice restored from last
 * launch would be attributed to whatever happens to be playing this time, and the server-reported
 * `ignored` list would still name a tag the author has since fixed.
 *
 * The persisted half — whether auto-select is on at all — is a listener preference and lives in
 * `visualizerStore` under ADR-0029 point 4.
 */
import { create } from 'zustand';

interface VisualizerAutoSelectState {
  /** The visualizer auto-select settled on, or null when it has not chosen (yet, or at all). */
  chosenId: string | null;
  /** The track `chosenId` was chosen for, so a stale choice can be told from a current one. */
  trackId: string | null;
  /**
   * True when the last ranking had nothing to rank against — an unanalysed track. Distinct from
   * "not asked yet", because the picker says so rather than leaving auto-select looking broken.
   */
  unranked: boolean;
  /**
   * Declarations the *server* did not recognise, by visualizer id. The client checks structure and
   * the server checks vocabulary (it owns the descriptor list), so an author's unknown tag can only
   * be reported from here.
   */
  ignoredByVisualizer: Record<string, string[]>;

  recordChoice: (args: {
    trackId: string;
    chosenId: string | null;
    unranked: boolean;
    ignoredByVisualizer: Record<string, string[]>;
  }) => void;
  reset: () => void;
}

export const useVisualizerAutoSelectStore = create<VisualizerAutoSelectState>()((set) => ({
  chosenId: null,
  trackId: null,
  unranked: false,
  ignoredByVisualizer: {},

  recordChoice: ({ trackId, chosenId, unranked, ignoredByVisualizer }) =>
    set((state) => ({
      trackId,
      // A ranking that produced no choice must not clear the one in force — that is what "keep the
      // current visualizer" means when a track has no analysis.
      chosenId: chosenId ?? state.chosenId,
      unranked,
      // Merged rather than replaced: only the candidates in this request are described, and
      // forgetting the rest would make the picker's list flicker between tracks.
      ignoredByVisualizer: { ...state.ignoredByVisualizer, ...ignoredByVisualizer },
    })),

  reset: () => set({ chosenId: null, trackId: null, unranked: false, ignoredByVisualizer: {} }),
}));
