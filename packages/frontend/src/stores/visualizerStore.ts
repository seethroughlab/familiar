/**
 * Visualizer preference store with localStorage persistence.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { DEFAULT_VISUALIZER_ID, VISUALIZER_STORAGE_KEY } from '../components/Visualizer/constants';

interface VisualizerState {
  // Current visualizer ID
  visualizerId: string;

  // Actions
  setVisualizerId: (id: string) => void;
}

export const useVisualizerStore = create<VisualizerState>()(
  persist(
    (set) => ({
      visualizerId: DEFAULT_VISUALIZER_ID,

      setVisualizerId: (id: string) => set({ visualizerId: id }),
    }),
    {
      name: VISUALIZER_STORAGE_KEY,
    }
  )
);
