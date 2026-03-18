import { create } from 'zustand';

export type RepeatMode = 'off' | 'all' | 'one';
export type CrossfadeState = 'idle' | 'preloading' | 'crossfading';

export interface PlaybackState {
  currentTrack: import('../types').Track | null;
  isPlaying: boolean;
  currentTime: number;
  duration: number;
  volume: number;
  shuffle: boolean;
  repeat: RepeatMode;
  consume: boolean;
  crossfadeState: CrossfadeState;
  nextTrackPreloaded: boolean;
  isLoadingAudio: boolean;
  isHydrated: boolean;
  _circuitBreakerTimestamps: number[];
}

export interface PlaybackActions {
  setCurrentTrack: (track: import('../types').Track | null) => void;
  setIsPlaying: (playing: boolean) => void;
  setCurrentTime: (time: number) => void;
  setDuration: (duration: number) => void;
  setVolume: (volume: number) => void;
  toggleRepeat: () => void;
  toggleConsume: () => void;
  setCrossfadeState: (state: CrossfadeState) => void;
  setNextTrackPreloaded: (preloaded: boolean) => void;
  setIsLoadingAudio: (loading: boolean) => void;
  registerFailureAdvance: () => boolean;
}

// Lazy persistence hook — set by persistenceAdapter to avoid circular imports
let persistHook: (() => void) | null = null;
export function _setPersistHook(fn: () => void) { persistHook = fn; }
const persist = () => { persistHook?.(); };

export const usePlaybackStore = create<PlaybackState & PlaybackActions>((set, get) => ({
  currentTrack: null,
  isPlaying: false,
  currentTime: 0,
  duration: 0,
  volume: 1,
  shuffle: false,
  repeat: 'off',
  consume: false,
  crossfadeState: 'idle',
  nextTrackPreloaded: false,
  isLoadingAudio: false,
  isHydrated: false,
  _circuitBreakerTimestamps: [],

  setCurrentTrack: (track) => {
    set({ currentTrack: track });
    persist();
  },
  setIsPlaying: (playing) => set({ isPlaying: playing }),
  setCurrentTime: (time) => {
    set({ currentTime: time });
    persist();
  },
  setDuration: (duration) => set({ duration }),
  setVolume: (volume) => {
    set({ volume: Math.max(0, Math.min(1, volume)) });
    persist();
  },
  toggleRepeat: () => {
    set((state) => ({
      repeat: state.repeat === 'off' ? 'all' : state.repeat === 'all' ? 'one' : 'off',
    }));
    persist();
  },
  toggleConsume: () => {
    set((state) => ({ consume: !state.consume }));
    persist();
  },
  setCrossfadeState: (crossfadeState) => set({ crossfadeState }),
  setNextTrackPreloaded: (nextTrackPreloaded) => set({ nextTrackPreloaded }),
  setIsLoadingAudio: (isLoadingAudio) => set({ isLoadingAudio }),
  registerFailureAdvance: () => {
    const MAX_AUTO_ADVANCES = 8;
    const WINDOW_MS = 15000;
    const now = Date.now();
    const timestamps = get()._circuitBreakerTimestamps.filter(t => now - t <= WINDOW_MS);
    timestamps.push(now);
    set({ _circuitBreakerTimestamps: timestamps });
    return timestamps.length <= MAX_AUTO_ADVANCES;
  },
}));
