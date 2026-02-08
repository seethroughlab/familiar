import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type NormalizationMode = 'track' | 'album' | 'auto';

interface AudioSettingsState {
  // Crossfade duration in seconds (0 = gapless without fade, max 10)
  crossfadeDuration: number;

  // Whether crossfade is enabled
  crossfadeEnabled: boolean;

  // Volume normalization
  normalizationEnabled: boolean;
  normalizationMode: NormalizationMode;
  normalizationTargetLufs: number;
  normalizationPreamp: number; // dB
  normalizationPreventClipping: boolean;

  // Actions
  setCrossfadeDuration: (duration: number) => void;
  setCrossfadeEnabled: (enabled: boolean) => void;
  setNormalizationEnabled: (enabled: boolean) => void;
  setNormalizationMode: (mode: NormalizationMode) => void;
  setNormalizationTargetLufs: (lufs: number) => void;
  setNormalizationPreamp: (db: number) => void;
  setNormalizationPreventClipping: (prevent: boolean) => void;
}

export const useAudioSettingsStore = create<AudioSettingsState>()(
  persist(
    (set) => ({
      crossfadeDuration: 3,
      crossfadeEnabled: true,

      normalizationEnabled: false,
      normalizationMode: 'track' as NormalizationMode,
      normalizationTargetLufs: -14,
      normalizationPreamp: 0,
      normalizationPreventClipping: true,

      setCrossfadeDuration: (duration) =>
        set({
          crossfadeDuration: Math.max(0, Math.min(10, duration)),
        }),

      setCrossfadeEnabled: (enabled) => set({ crossfadeEnabled: enabled }),

      setNormalizationEnabled: (enabled) => set({ normalizationEnabled: enabled }),
      setNormalizationMode: (mode) => set({ normalizationMode: mode }),
      setNormalizationTargetLufs: (lufs) =>
        set({ normalizationTargetLufs: Math.max(-23, Math.min(-5, lufs)) }),
      setNormalizationPreamp: (db) =>
        set({ normalizationPreamp: Math.max(-6, Math.min(6, db)) }),
      setNormalizationPreventClipping: (prevent) =>
        set({ normalizationPreventClipping: prevent }),
    }),
    {
      name: 'familiar-audio-settings',
    }
  )
);
