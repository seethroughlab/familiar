import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type ShufflePresetId = 'rediscover' | 'fresh_finds' | 'comfort_zone' | 'deep_dive';

export interface ShufflePreset {
  id: ShufflePresetId;
  name: string;
  description: string;
}

export const SHUFFLE_PRESETS: ShufflePreset[] = [
  { id: 'rediscover', name: 'Rediscover', description: 'Forgotten favorites — tracks you used to play but haven\'t heard in a while' },
  { id: 'fresh_finds', name: 'Fresh Finds', description: 'Unplayed and recently added tracks' },
  { id: 'comfort_zone', name: 'Comfort Zone', description: 'Your most-played favorites' },
  { id: 'deep_dive', name: 'Deep Dive', description: 'Maximize discovery — unplayed tracks with high variety' },
];

interface ShuffleWeightState {
  enabled: boolean;
  activePreset: ShufflePresetId | null;

  setEnabled: (enabled: boolean) => void;
  setActivePreset: (preset: ShufflePresetId | null) => void;
}

export const useShuffleWeightStore = create<ShuffleWeightState>()(
  persist(
    (set) => ({
      enabled: false,
      activePreset: null,

      setEnabled: (enabled) => set({ enabled }),
      setActivePreset: (preset) => set({ activePreset: preset, enabled: preset !== null }),
    }),
    {
      name: 'familiar-shuffle-weights',
      partialize: (state) => ({
        enabled: state.enabled,
        activePreset: state.activePreset,
      }),
    }
  )
);
