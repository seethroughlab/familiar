import { usePlaybackStore, _setPersistHook } from './playbackStore';
import { debouncedSavePlayerState } from './persistence';

// Late-bound import to avoid circular dependency (queueStore imports playbackStore)
interface PersistableQueueState {
  queue: import('../types').QueueItem[];
  queueIndex: number;
  shuffleOrder: number[];
  shuffleIndex: number;
  queueSource: import('../db').PersistedQueueSource | null;
  lazyQueueIds: string[] | null;
  lazyQueueIndex: number;
  logicalTrackIds: string[] | null;
  logicalIndex: number;
}

let getQueueState: (() => PersistableQueueState) | null = null;

const EMPTY_QUEUE_STATE: PersistableQueueState = {
  queue: [],
  queueIndex: -1,
  shuffleOrder: [],
  shuffleIndex: -1,
  queueSource: null,
  lazyQueueIds: null,
  lazyQueueIndex: -1,
  logicalTrackIds: null,
  logicalIndex: -1,
};

export function _setQueueStateGetter(fn: typeof getQueueState) {
  getQueueState = fn;
}

// Every caller persists through here, so widening the payload once covers all of them.
export function persistCombinedState() {
  const playback = usePlaybackStore.getState();
  const queue = getQueueState?.() ?? EMPTY_QUEUE_STATE;
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
    queueSource: queue.queueSource,
    lazyQueueIds: queue.lazyQueueIds,
    lazyQueueIndex: queue.lazyQueueIndex,
    logicalTrackIds: queue.logicalTrackIds,
    logicalIndex: queue.logicalIndex,
  });
}

// Wire playbackStore's persist calls through to persistCombinedState
_setPersistHook(persistCombinedState);
