/**
 * Visualizer preference store with localStorage persistence.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { DEFAULT_VISUALIZER_ID } from '../components/Visualizer/types';

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
      name: 'familiar-visualizer',
    }
  )
);
