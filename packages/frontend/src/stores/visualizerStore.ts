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

  // Actions
  setVisualizerId: (id: string) => void;
  setGlowLevel: (level: number) => void;
}

export const useVisualizerStore = create<VisualizerState>()(
  persist(
    (set) => ({
      visualizerId: DEFAULT_VISUALIZER_ID,
      glowLevel: 50,

      setVisualizerId: (id: string) => set({ visualizerId: id }),
      setGlowLevel: (level: number) => set({ glowLevel: Math.max(0, Math.min(100, level)) }),
    }),
    {
      name: VISUALIZER_STORAGE_KEY,
    }
  )
);
