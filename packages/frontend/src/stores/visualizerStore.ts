/**
 * Visualizer preference store with localStorage persistence.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { DEFAULT_VISUALIZER_ID, VISUALIZER_STORAGE_KEY } from '../components/Visualizer/constants';

interface VisualizerState {
  // Current visualizer ID
  visualizerId: string;
  // Glow (bloom) level: 0 = off, 100 = full intensity
  glowLevel: number;
  /**
   * Let the server choose a visualizer to suit each track (ADR-0064 point 7).
   *
   * **Off by default, and beside the manual choice rather than replacing it.** Someone who picked a
   * visualizer expressed a preference, and silently overriding it is not a feature. Only the toggle
   * is persisted — which visualizer was chosen for which track is a fact about this run and lives in
   * `visualizerAutoSelectStore`, unpersisted for the reason its sibling gives.
   */
  autoSelect: boolean;

  // Actions
  setVisualizerId: (id: string) => void;
  setGlowLevel: (level: number) => void;
  setAutoSelect: (enabled: boolean) => void;
}

export const useVisualizerStore = create<VisualizerState>()(
  persist(
    (set) => ({
      visualizerId: DEFAULT_VISUALIZER_ID,
      glowLevel: 50,
      autoSelect: false,

      setVisualizerId: (id: string) => set({ visualizerId: id }),
      setGlowLevel: (level: number) => set({ glowLevel: Math.max(0, Math.min(100, level)) }),
      setAutoSelect: (enabled: boolean) => set({ autoSelect: enabled }),
    }),
    {
      // No `version`/`migrate`: zustand shallow-merges over the initial state, so a blob persisted
      // before `autoSelect` existed simply takes its default.
      name: VISUALIZER_STORAGE_KEY,
    }
  )
);
