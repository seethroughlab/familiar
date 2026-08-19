import { create } from 'zustand';

export type RepeatMode = 'off' | 'all' | 'one';
export type CrossfadeState = 'idle' | 'preloading' | 'crossfading';

/**
 * Why the current track was replaced (ADR-0004).
 *
 * Without this, a natural end and a hard skip are indistinguishable — the only
 * observable signal is `currentTrack.id` changing. Completion ratio alone is not a
 * substitute: crossfade advances at `duration - crossfadeDuration`, so a fully played
 * track reads ~0.9 and would look like a skip.
 *
 *   ended | crossfade | native-auto  →  backend `natural`
 *   user                             →  backend `user`   (ratio decides the outcome)
 *   error                            →  backend `error`  (never a taste signal)
 *   system                           →  emits nothing
 *
 * `system` covers changes the listener did not cause — offline queue rebuilds, hydrate,
 * profile switches. Emitting those would log phantom skips on every reconnect.
 */
export type AdvanceReason =
  | 'ended'
  | 'crossfade'
  | 'native-auto'
  | 'user'
  | 'error'
  | 'system';

const ADVANCE_REASONS: ReadonlySet<string> = new Set<AdvanceReason>([
  'ended', 'crossfade', 'native-auto', 'user', 'error', 'system',
]);

/**
 * Coerce an untrusted value to a valid reason, defaulting to 'user'.
 *
 * Guards the `onClick={playNext}` shape, where React passes a MouseEvent as the first
 * argument — without this, every UI skip would report a MouseEvent as its reason and
 * look like it worked.
 */
export function normalizeAdvanceReason(value: unknown): AdvanceReason {
  return typeof value === 'string' && ADVANCE_REASONS.has(value)
    ? (value as AdvanceReason)
    : 'user';
}

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
  /**
   * Why `currentTrack` was last replaced. Written in the same `setState` as the track
   * change so it is atomically tied to a real advance and cannot leak into the next one
   * (several `playNext` branches return without changing the track).
   */
  _advanceReason: AdvanceReason;
  /**
   * Where to seek once the current track is loaded, or null.
   *
   * Setting `currentTime` alone only moves the transport display — the audio element
   * still starts at 0 and the next `timeUpdate` overwrites the number, so a restored
   * position reads as "shows 5:34, plays from 0:00". Loading is asynchronous, so the
   * seek cannot happen at the moment the position is known; it is applied on `canplay`
   * and cleared. Used when adopting another device's session (ADR-0003).
   */
  _pendingSeekSeconds: number | null;
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

// Persistence is gone (ADR-0071 deleted the Dexie store), so this is a no-op rather than a hook
// nothing sets. Kept as one call site so the places that used to persist still read the same.
const persist = () => {};

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
  _advanceReason: 'user',
  _pendingSeekSeconds: null,

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
