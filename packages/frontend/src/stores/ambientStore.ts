/**
 * Ambient session state store.
 *
 * Manages ambient playback session: status, controls, current/upcoming snippets,
 * history. Completely independent from playerStore.
 */

import { create } from 'zustand';
import type {
  AmbientControls,
  AmbientDescriptor,
  AmbientSessionStatus,
  AmbientSnippet,
} from '../player/ambient/types';

interface AmbientState {
  status: AmbientSessionStatus;
  controls: AmbientControls;
  currentSnippet: AmbientSnippet | null;
  snippetCurrentTime: number;
  upcomingSnippets: AmbientSnippet[];
  history: AmbientSnippet[];
  seedDescriptor: AmbientDescriptor | null;
  poolSize: number;
  poolCollapsed: boolean;
  error: string | null;

  // Actions
  setStatus: (status: AmbientSessionStatus) => void;
  setCurrentSnippet: (snippet: AmbientSnippet | null) => void;
  setSnippetCurrentTime: (time: number) => void;
  setUpcomingSnippets: (snippets: AmbientSnippet[]) => void;
  addToHistory: (snippet: AmbientSnippet) => void;
  setSeedDescriptor: (descriptor: AmbientDescriptor | null) => void;
  setPoolInfo: (poolSize: number, poolCollapsed: boolean) => void;
  setError: (error: string | null) => void;
  updateControls: (updates: Partial<AmbientControls>) => void;
  reset: () => void;
}

const DEFAULT_CONTROLS: AmbientControls = {
  intensity: 'balanced',
  snippetLength: 16,
  transitionDensity: 'moderate',
  filterPreset: 'all',
};

export const useAmbientStore = create<AmbientState>()((set, get) => ({
  status: 'idle',
  controls: { ...DEFAULT_CONTROLS },
  currentSnippet: null,
  snippetCurrentTime: 0,
  upcomingSnippets: [],
  history: [],
  seedDescriptor: null,
  poolSize: 0,
  poolCollapsed: false,
  error: null,

  setStatus: (status) => set({ status, error: status === 'error' ? get().error : null }),
  setCurrentSnippet: (snippet) => set({ currentSnippet: snippet }),
  setSnippetCurrentTime: (time) => set({ snippetCurrentTime: time }),
  setUpcomingSnippets: (snippets) => set({ upcomingSnippets: snippets }),
  addToHistory: (snippet) => set((s) => ({
    history: [...s.history.slice(-19), snippet],
  })),
  setSeedDescriptor: (descriptor) => set({ seedDescriptor: descriptor }),
  setPoolInfo: (poolSize, poolCollapsed) => set({ poolSize, poolCollapsed }),
  setError: (error) => set({ error, status: error ? 'error' : get().status }),
  updateControls: (updates) => set((s) => ({
    controls: { ...s.controls, ...updates },
  })),
  reset: () => set({
    status: 'idle',
    controls: { ...DEFAULT_CONTROLS },
    currentSnippet: null,
    snippetCurrentTime: 0,
    upcomingSnippets: [],
    history: [],
    seedDescriptor: null,
    poolSize: 0,
    poolCollapsed: false,
    error: null,
  }),
}));
