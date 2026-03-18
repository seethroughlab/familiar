import { usePlaybackStore, _setPersistHook } from './playbackStore';
import { debouncedSavePlayerState } from './persistence';

// Late-bound import to avoid circular dependency (queueStore imports playbackStore)
let getQueueState: (() => { queue: import('../types').QueueItem[]; queueIndex: number; shuffleOrder: number[]; shuffleIndex: number }) | null = null;

export function _setQueueStateGetter(fn: typeof getQueueState) {
  getQueueState = fn;
}

export function persistCombinedState() {
  const playback = usePlaybackStore.getState();
  const queue = getQueueState?.() ?? { queue: [], queueIndex: -1, shuffleOrder: [], shuffleIndex: -1 };
  debouncedSavePlayerState({
    volume: playback.volume,
    shuffle: playback.shuffle,
    repeat: playback.repeat,
    consume: playback.consume,
    currentTime: playback.currentTime,
    currentTrack: playback.currentTrack,
    queue: queue.queue,
    queueIndex: queue.queueIndex,
    shuffleOrder: queue.shuffleOrder,
    shuffleIndex: queue.shuffleIndex,
  });
}

// Wire playbackStore's persist calls through to persistCombinedState
_setPersistHook(persistCombinedState);
