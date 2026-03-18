/**
 * playerStore — backward-compatible facade over playbackStore + queueStore.
 *
 * All 44+ consumer files import `usePlayerStore` with field selectors like
 * `usePlayerStore(s => s.isPlaying)`. This facade merges both stores into a
 * single combined snapshot so existing selectors continue to work with zero
 * consumer migration.
 */
import { useSyncExternalStore } from 'react';
import { usePlaybackStore } from './playbackStore';
import type { PlaybackState, PlaybackActions } from './playbackStore';
import { useQueueStore } from './queueStore';
import type { QueueState, QueueActions } from './queueStore';

// Re-export shared types so existing `import { QueueSource } from './playerStore'` works
export type { QueueSourceType, QueueSource, LibraryFilters } from './playerStore.types';
export type { RepeatMode, CrossfadeState } from './playbackStore';

type PlayerState = PlaybackState & PlaybackActions & QueueState & QueueActions;

function getSnapshot(): PlayerState {
  return { ...usePlaybackStore.getState(), ...useQueueStore.getState() };
}

function subscribe(listener: () => void) {
  const u1 = usePlaybackStore.subscribe(listener);
  const u2 = useQueueStore.subscribe(listener);
  return () => { u1(); u2(); };
}

// The facade hook — drop-in replacement for the old Zustand `usePlayerStore`
function usePlayerStoreFacade<T>(selector: (s: PlayerState) => T): T {
  return useSyncExternalStore(subscribe, () => selector(getSnapshot()));
}

// Non-React access (used by useAudioEngine, prefetchService, etc.)
usePlayerStoreFacade.getState = getSnapshot;
usePlayerStoreFacade.setState = (partial: Partial<PlayerState>) => {
  // Route each key to the correct underlying store.
  // Keys that exist on playbackStore go there; everything else goes to queueStore.
  const playbackKeys = new Set<string>([
    'currentTrack', 'isPlaying', 'currentTime', 'duration', 'volume',
    'shuffle', 'repeat', 'consume', 'crossfadeState', 'nextTrackPreloaded',
    'isLoadingAudio', 'isHydrated', '_circuitBreakerTimestamps',
  ]);
  const playbackPartial: Record<string, unknown> = {};
  const queuePartial: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(partial)) {
    if (playbackKeys.has(key)) {
      playbackPartial[key] = value;
    } else {
      queuePartial[key] = value;
    }
  }
  if (Object.keys(playbackPartial).length > 0) {
    usePlaybackStore.setState(playbackPartial as Partial<PlaybackState>);
  }
  if (Object.keys(queuePartial).length > 0) {
    useQueueStore.setState(queuePartial as Partial<QueueState>);
  }
};
usePlayerStoreFacade.subscribe = subscribe;

export const usePlayerStore = usePlayerStoreFacade;
