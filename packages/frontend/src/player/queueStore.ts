import { create } from 'zustand';
import type { Track, QueueItem } from '../types';
import { usePlaybackStore, normalizeAdvanceReason } from './playbackStore';
import type { AdvanceReason } from './playbackStore';
import { persistCombinedState, _setQueueStateGetter } from './persistenceAdapter';
import {
  loadPlayerState,
  fetchTracksBatched,
  migrateOldPlayerState,
} from './persistence';
import { tracksApi } from '../api';
import { getEngine } from './audio/engineInstance';
import { createLogger } from '../utils/logger';
import { useConnectivityStore } from '../stores/connectivityStore';
import { useShuffleWeightStore } from '../stores/shuffleWeightStore';

import type { QueueSource } from './playerStore.types';

const log = createLogger('Player', { forceVerbose: true });

// --- Module-level helpers ---

let queueIdCounter = 0;
const generateQueueId = () => `queue-${++queueIdCounter}`;

function enforceOfflineQueueInvariant(tracks: Track[]): Track[] {
  const connectivity = useConnectivityStore.getState();
  if (!connectivity.offlineModeActive) return tracks;
  return tracks.filter((track) => connectivity.offlineTrackIds.has(track.id));
}

function generateShuffleOrder(queueLength: number, currentIndex: number): number[] {
  if (queueLength <= 1) return queueLength === 1 ? [0] : [];
  const indices = Array.from({ length: queueLength }, (_, i) => i);
  const rest = indices.filter(i => i !== currentIndex);
  for (let i = rest.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [rest[i], rest[j]] = [rest[j], rest[i]];
  }
  return currentIndex >= 0 ? [currentIndex, ...rest] : rest;
}

// Lazy reservoir constants
const WINDOW_SIZE = 50;
const REFILL_THRESHOLD = 10;
const REFILL_BATCH = 20;

let isRefilling = false;
let hydrationVersion = 0;

const refillFromReservoir = async () => {
  if (isRefilling) return;

  const { lazyQueueIds, lazyQueueIndex, queue, queueIndex } = useQueueStore.getState();
  if (!lazyQueueIds || lazyQueueIndex >= lazyQueueIds.length) return;

  const remaining = queue.length - 1 - queueIndex;
  if (remaining > REFILL_THRESHOLD) return;

  isRefilling = true;
  try {
    const batchIds = lazyQueueIds.slice(lazyQueueIndex, lazyQueueIndex + REFILL_BATCH);
    if (batchIds.length === 0) return;

    const rawTracks = await tracksApi.getBatch(batchIds);
    const tracks = enforceOfflineQueueInvariant(rawTracks);
    if (tracks.length === 0) return;

    const newItems: QueueItem[] = tracks.map(track => ({
      track,
      queueId: generateQueueId(),
    }));

    const currentState = useQueueStore.getState();
    const newQueue = [...currentState.queue, ...newItems];

    let newShuffleOrder = currentState.shuffleOrder;
    if (usePlaybackStore.getState().shuffle && newShuffleOrder.length > 0) {
      newShuffleOrder = [...newShuffleOrder];
      const startIdx = currentState.queue.length;
      for (let i = 0; i < newItems.length; i++) {
        const insertPos = currentState.shuffleIndex + 1 + Math.floor(Math.random() * (newShuffleOrder.length - currentState.shuffleIndex));
        newShuffleOrder.splice(insertPos, 0, startIdx + i);
      }
    }

    useQueueStore.setState({
      queue: newQueue,
      lazyQueueIndex: currentState.lazyQueueIndex + batchIds.length,
      shuffleOrder: newShuffleOrder,
    });
    persistCombinedState();
  } catch (error) {
    log.error('Failed to refill from reservoir:', error);
  } finally {
    isRefilling = false;
  }
};

// --- Store types ---

export interface QueueState {
  queue: QueueItem[];
  queueIndex: number;
  history: Track[];
  shuffleOrder: number[];
  shuffleIndex: number;
  lazyQueueIds: string[] | null;
  lazyQueueIndex: number;
  queueSource: QueueSource | null;
  isQueueHydrating: boolean;
}

export interface QueueActions {
  addToQueue: (track: Track, insertIndex?: number, shuffleInsertPosition?: number) => void;
  removeFromQueue: (queueId: string) => void;
  clearQueue: () => void;
  playTrack: (track: Track, options?: { reason?: AdvanceReason }) => void;
  playNext: (options?: { reason?: AdvanceReason }) => void | Promise<void>;
  playPrevious: (options?: { reason?: AdvanceReason }) => void;
  setQueue: (tracks: Track[], startIndex?: number, source?: QueueSource, options?: { preservePlaybackState?: boolean; reason?: AdvanceReason }) => void;
  setQueueByTrackId: (tracks: Track[], trackId: string, source?: QueueSource, options?: { reason?: AdvanceReason }) => void;
  reorderQueue: (fromIndex: number, toIndex: number) => void;
  reorderShuffleOrder: (fromIndex: number, toIndex: number) => void;
  jumpToQueueIndex: (index: number, options?: { reason?: AdvanceReason }) => void;
  setLazyQueue: (ids: string[], source?: QueueSource, options?: { initialTrack?: Track }) => Promise<void>;
  exitLazyMode: () => void;
  getNextTrack: () => Track | null;
  getUpcomingTrackIds: (count: number) => string[];
  advanceToNextTrack: (track: Track, options?: { reason?: AdvanceReason }) => void;
  toggleShuffle: () => void | Promise<void>;
  hydrate: () => Promise<void>;
  resetForProfileSwitch: () => void;
}

export const useQueueStore = create<QueueState & QueueActions>((set, get) => ({
  queue: [],
  queueIndex: -1,
  history: [],
  shuffleOrder: [],
  shuffleIndex: -1,
  lazyQueueIds: null,
  lazyQueueIndex: -1,
  queueSource: null,
  isQueueHydrating: false,

  addToQueue: (track, insertIndex, shuffleInsertPosition) => {
    const connectivity = useConnectivityStore.getState();
    if (connectivity.offlineModeActive && !connectivity.offlineTrackIds.has(track.id)) {
      log.warn('addToQueue blocked by offline invariant', { trackId: track.id });
      return;
    }

    const { queue, queueIndex, shuffleOrder } = get();
    const shuffle = usePlaybackStore.getState().shuffle;

    const insertAt = insertIndex ?? queue.length;
    const newQueue = [...queue];
    newQueue.splice(insertAt, 0, { track, queueId: generateQueueId() });

    const newQueueIndex = insertAt <= queueIndex ? queueIndex + 1 : queueIndex;

    let newShuffleOrder = shuffleOrder;
    if (shuffle) {
      newShuffleOrder = shuffleOrder.map(i => i >= insertAt ? i + 1 : i);
      if (shuffleInsertPosition !== undefined) {
        newShuffleOrder.splice(shuffleInsertPosition, 0, insertAt);
      } else {
        newShuffleOrder.push(insertAt);
      }
    }

    set({
      queue: newQueue,
      queueIndex: newQueueIndex,
      shuffleOrder: newShuffleOrder,
    });
    persistCombinedState();
  },

  removeFromQueue: (queueId) => {
    const { queue, queueIndex, shuffleOrder, shuffleIndex } = get();
    const shuffle = usePlaybackStore.getState().shuffle;
    const removedIndex = queue.findIndex((item) => item.queueId === queueId);
    if (removedIndex === -1) return;

    const newQueue = queue.filter((item) => item.queueId !== queueId);
    let newQueueIndex = queueIndex;
    if (removedIndex < queueIndex) {
      newQueueIndex = queueIndex - 1;
    }

    let newShuffleOrder = shuffleOrder;
    let newShuffleIndex = shuffleIndex;
    if (shuffle && shuffleOrder.length > 0) {
      newShuffleOrder = shuffleOrder
        .filter(i => i !== removedIndex)
        .map(i => i > removedIndex ? i - 1 : i);
      const currentShufflePos = shuffleOrder.indexOf(queueIndex);
      if (currentShufflePos >= 0) {
        newShuffleIndex = newShuffleOrder.indexOf(newQueueIndex);
      }
    }

    set({
      queue: newQueue,
      queueIndex: newQueueIndex,
      shuffleOrder: newShuffleOrder,
      shuffleIndex: newShuffleIndex,
    });
    persistCombinedState();
  },

  clearQueue: () => {
    log.info('clearQueue');
    set({ queue: [], queueIndex: -1, lazyQueueIds: null, lazyQueueIndex: -1, queueSource: null });
    persistCombinedState();
  },

  playTrack: (track, options) => {
    const reason = normalizeAdvanceReason(options?.reason);
    log.info('playTrack', { id: track.id, title: track.title });
    const currentTrack = usePlaybackStore.getState().currentTrack;
    if (currentTrack) {
      set((s) => ({
        history: [...s.history.slice(-49), currentTrack],
      }));
    }
    usePlaybackStore.setState({
      currentTrack: track,
      _advanceReason: reason,
      isPlaying: true,
      currentTime: 0,
      isLoadingAudio: true,
    });
    persistCombinedState();
  },

  playNext: async (options) => {
    const reason = normalizeAdvanceReason(options?.reason);
    const { queue, queueIndex, shuffleOrder, shuffleIndex } = get();
    const { shuffle, repeat, consume, currentTrack } = usePlaybackStore.getState();

    if (queue.length === 0) {
      log.info('playNext — empty queue, stopping');
      usePlaybackStore.setState({ isPlaying: false });
      return;
    }

    if (currentTrack) {
      set((s) => ({
        history: [...s.history.slice(-49), currentTrack],
      }));
    }

    let nextQueueIndex: number;
    let newShuffleIndex = shuffleIndex;
    let newShuffleOrder = shuffleOrder;

    if (shuffle && shuffleOrder.length > 0) {
      newShuffleIndex = shuffleIndex + 1;
      if (newShuffleIndex >= shuffleOrder.length) {
        if (repeat === 'all') {
          newShuffleOrder = generateShuffleOrder(queue.length, queueIndex);
          newShuffleIndex = 0;
          nextQueueIndex = newShuffleOrder[0];
        } else {
          log.info('playNext — end of shuffle order, stopping', { repeat, consume });
          usePlaybackStore.setState({ isPlaying: false });
          return;
        }
      } else {
        nextQueueIndex = shuffleOrder[newShuffleIndex];
      }
    } else {
      nextQueueIndex = queueIndex + 1;
      if (nextQueueIndex >= queue.length) {
        if (repeat === 'all') {
          nextQueueIndex = 0;
        } else {
          log.info('playNext — end of queue, stopping', { queueIndex, queueLength: queue.length, repeat, consume });
          usePlaybackStore.setState({ isPlaying: false });
          return;
        }
      }
    }

    // Consume mode: remove the finished track from the queue (skip for repeat-one)
    if (consume && repeat !== 'one') {
      const removedIndex = queueIndex;
      const newQueue = [...queue];
      newQueue.splice(removedIndex, 1);

      if (newQueue.length === 0) {
        set({ queue: [], queueIndex: -1, shuffleOrder: [], shuffleIndex: -1 });
        usePlaybackStore.setState({ isPlaying: false });
        persistCombinedState();
        return;
      }

      if (nextQueueIndex > removedIndex) {
        nextQueueIndex -= 1;
      } else if (nextQueueIndex === removedIndex && nextQueueIndex >= newQueue.length) {
        nextQueueIndex = 0;
      }

      if (nextQueueIndex < 0 || nextQueueIndex >= newQueue.length) {
        nextQueueIndex = 0;
      }

      if (shuffle) {
        newShuffleOrder = newShuffleOrder
          .filter(i => i !== removedIndex)
          .map(i => i > removedIndex ? i - 1 : i);
        const posInShuffle = newShuffleOrder.indexOf(nextQueueIndex);
        newShuffleIndex = posInShuffle >= 0 ? posInShuffle : 0;
      }

      set({
        queue: newQueue,
        queueIndex: nextQueueIndex,
        shuffleIndex: newShuffleIndex,
        shuffleOrder: newShuffleOrder,
      });
      usePlaybackStore.setState({
        currentTrack: newQueue[nextQueueIndex].track,
        _advanceReason: reason,
        isPlaying: true,
        currentTime: 0,
        isLoadingAudio: true,
      });
      persistCombinedState();
      refillFromReservoir();
      return;
    }

    if (nextQueueIndex < 0 || nextQueueIndex >= queue.length) {
      log.warn('playNext — nextQueueIndex out of bounds, stopping', { nextQueueIndex, queueLength: queue.length });
      usePlaybackStore.setState({ isPlaying: false });
      return;
    }

    const nextTrack = queue[nextQueueIndex].track;
    log.info('playNext', {
      from: currentTrack?.title,
      to: nextTrack.title,
      nextId: nextTrack.id,
      mode: shuffle ? 'shuffle' : 'sequential',
      repeat,
      consume,
      nextQueueIndex,
    });

    set({
      queueIndex: nextQueueIndex,
      shuffleIndex: newShuffleIndex,
      shuffleOrder: newShuffleOrder,
    });
    usePlaybackStore.setState({
      currentTrack: nextTrack,
      _advanceReason: reason,
      isPlaying: true,
      currentTime: 0,
      isLoadingAudio: true,
    });
    persistCombinedState();
    refillFromReservoir();
  },

  playPrevious: (options) => {
    const reason = normalizeAdvanceReason(options?.reason);
    const { queue, shuffleOrder, shuffleIndex } = get();
    const { shuffle, currentTrack, currentTime } = usePlaybackStore.getState();

    // Step 1: If more than 3 seconds in, restart current track
    if (currentTime > 3) {
      log.info('playPrevious — restarting current track', { title: currentTrack?.title, currentTime });
      getEngine().seek(0);
      usePlaybackStore.setState({ currentTime: 0 });
      return;
    }

    // Step 2: Shuffle mode — go to previous track in shuffle order
    if (shuffle && shuffleOrder.length > 0 && shuffleIndex > 0) {
      const newShuffleIndex = shuffleIndex - 1;
      const prevQueueIndex = shuffleOrder[newShuffleIndex];
      const prevTrack = queue[prevQueueIndex]?.track;
      if (prevTrack) {
        log.info('playPrevious — going to previous in shuffle order', {
          from: currentTrack?.title,
          to: prevTrack.title,
          newShuffleIndex,
        });
        if (currentTrack) {
          set((s) => ({ history: [...s.history.slice(-49), currentTrack] }));
        }
        set({
          queueIndex: prevQueueIndex,
          shuffleIndex: newShuffleIndex,
        });
        usePlaybackStore.setState({
          currentTrack: prevTrack,
          _advanceReason: reason,
          isPlaying: true,
          currentTime: 0,
          isLoadingAudio: true,
        });
        persistCombinedState();
        return;
      }
    }

    // Step 3: Non-shuffle (or shuffle at start) — go to history
    const { history } = get();
    if (history.length > 0) {
      const prevTrack = history[history.length - 1];
      log.info('playPrevious — going to history track', { title: prevTrack.title, id: prevTrack.id });
      set((s) => ({
        history: s.history.slice(0, -1),
        queueIndex: Math.max(-1, s.queueIndex - 1),
      }));
      usePlaybackStore.setState({
        currentTrack: prevTrack,
        _advanceReason: reason,
        isPlaying: true,
        currentTime: 0,
        isLoadingAudio: true,
      });
      persistCombinedState();
    }
  },

  setQueue: (tracks, startIndex = 0, source?: QueueSource, options?: { preservePlaybackState?: boolean; reason?: AdvanceReason }) => {
    // Callers are queue rebuilds, hydration and profile switches — not listener actions.
    const reason = normalizeAdvanceReason(options?.reason ?? 'system');
    const requestedTrackId = tracks[startIndex]?.id;
    const queueTracks = enforceOfflineQueueInvariant(tracks);

    const safeStartIndex = queueTracks.length === 0
      ? -1
      : Math.max(0, Math.min(startIndex, queueTracks.length - 1));
    if (safeStartIndex !== startIndex) {
      log.warn('setQueue adjusted invalid startIndex', {
        trackCount: queueTracks.length,
        requested: startIndex,
        resolved: safeStartIndex,
      });
    }
    const resolvedStartIndex = requestedTrackId
      ? queueTracks.findIndex((track) => track.id === requestedTrackId)
      : safeStartIndex;
    const finalStartIndex = resolvedStartIndex >= 0 ? resolvedStartIndex : safeStartIndex;

    const shuffle = usePlaybackStore.getState().shuffle;
    log.info('setQueue', {
      trackCount: queueTracks.length,
      startIndex: finalStartIndex,
      source: source?.type,
      sourceId: source?.id,
      shuffle,
    });

    getEngine().cancelCrossfade?.();
    const queueItems = queueTracks.map((track) => ({
      track,
      queueId: generateQueueId(),
    }));

    let shuffleOrder: number[] = [];
    let shuffleIndex = -1;
    if (shuffle && queueTracks.length > 1) {
      shuffleOrder = generateShuffleOrder(queueTracks.length, finalStartIndex);
      shuffleIndex = 0;
    }

    set({
      queue: queueItems,
      queueIndex: finalStartIndex,
      shuffleOrder,
      shuffleIndex,
      lazyQueueIds: null,
      lazyQueueIndex: -1,
      queueSource: source || null,
    });
    usePlaybackStore.setState({
      currentTrack: finalStartIndex >= 0 ? queueTracks[finalStartIndex] : null,
      _advanceReason: reason,
      isPlaying: options?.preservePlaybackState ? usePlaybackStore.getState().isPlaying : finalStartIndex >= 0,
      currentTime: 0,
      isLoadingAudio: options?.preservePlaybackState ? usePlaybackStore.getState().isLoadingAudio : finalStartIndex >= 0,
    });
    persistCombinedState();
  },

  setQueueByTrackId: (tracks, trackId, source?: QueueSource, options?: { reason?: AdvanceReason }) => {
    const reason = normalizeAdvanceReason(options?.reason ?? 'system');
    const offlineModeActive = useConnectivityStore.getState().offlineModeActive;
    const queueTracks = enforceOfflineQueueInvariant(tracks);
    const resolvedIndex = queueTracks.findIndex((track) => track.id === trackId);
    if (resolvedIndex < 0 && queueTracks.length === 0) {
      log.warn('setQueueByTrackId ignored missing track id', {
        trackId,
        trackCount: queueTracks.length,
        source: source?.type,
        sourceId: source?.id,
      });
      return;
    }
    if (resolvedIndex < 0) {
      if (!offlineModeActive) {
        log.warn('setQueueByTrackId ignored missing track id', {
          trackId,
          trackCount: queueTracks.length,
          source: source?.type,
          sourceId: source?.id,
        });
        return;
      }
      get().setQueue(queueTracks, 0, source, { reason });
      return;
    }
    get().setQueue(queueTracks, resolvedIndex, source, { reason });
  },

  reorderQueue: (fromIndex: number, toIndex: number) => {
    const { queue, queueIndex } = get();
    const currentTrack = usePlaybackStore.getState().currentTrack;
    if (fromIndex < 0 || fromIndex >= queue.length || toIndex < 0 || toIndex >= queue.length) {
      return;
    }

    const newQueue = [...queue];
    const [removed] = newQueue.splice(fromIndex, 1);
    newQueue.splice(toIndex, 0, removed);

    let newQueueIndex = queueIndex;
    if (currentTrack) {
      newQueueIndex = newQueue.findIndex(item => item.track.id === currentTrack.id);
    }

    set({
      queue: newQueue,
      queueIndex: newQueueIndex,
    });
    persistCombinedState();
  },

  reorderShuffleOrder: (fromIndex: number, toIndex: number) => {
    const { shuffleOrder, shuffleIndex } = get();
    if (fromIndex < 0 || fromIndex >= shuffleOrder.length || toIndex < 0 || toIndex >= shuffleOrder.length) {
      return;
    }

    const newOrder = [...shuffleOrder];
    const [removed] = newOrder.splice(fromIndex, 1);
    newOrder.splice(toIndex, 0, removed);

    let newShuffleIndex = shuffleIndex;
    if (fromIndex === shuffleIndex) {
      newShuffleIndex = toIndex;
    } else if (fromIndex < shuffleIndex && toIndex >= shuffleIndex) {
      newShuffleIndex = shuffleIndex - 1;
    } else if (fromIndex > shuffleIndex && toIndex <= shuffleIndex) {
      newShuffleIndex = shuffleIndex + 1;
    }

    set({ shuffleOrder: newOrder, shuffleIndex: newShuffleIndex });
    persistCombinedState();
  },

  jumpToQueueIndex: (index: number, options?: { reason?: AdvanceReason }) => {
    const reason = normalizeAdvanceReason(options?.reason);
    const { queue, shuffleOrder } = get();
    const { shuffle, currentTrack } = usePlaybackStore.getState();
    if (index < 0 || index >= queue.length) {
      return;
    }

    const targetItem = queue[index];
    if (!targetItem) return;
    log.info('jumpToQueueIndex', { index, title: targetItem.track.title, id: targetItem.track.id });

    if (currentTrack) {
      set((s) => ({
        history: [...s.history.slice(-49), currentTrack],
      }));
    }

    let newShuffleIndex = get().shuffleIndex;
    if (shuffle && shuffleOrder.length > 0) {
      const pos = shuffleOrder.indexOf(index);
      if (pos >= 0) newShuffleIndex = pos;
    }

    set({
      queueIndex: index,
      shuffleIndex: newShuffleIndex,
    });
    usePlaybackStore.setState({
      currentTrack: targetItem.track,
      _advanceReason: reason,
      isPlaying: true,
      currentTime: 0,
      isLoadingAudio: true,
    });
    persistCombinedState();
  },

  setLazyQueue: async (ids: string[], source?: QueueSource, options?: { initialTrack?: Track }) => {
    let resolvedIds = ids;
    const connectivity = useConnectivityStore.getState();
    if (connectivity.offlineModeActive) {
      resolvedIds = ids.filter((id) => connectivity.offlineTrackIds.has(id));
    }

    if (resolvedIds.length === 0) {
      set({
        queue: [],
        queueIndex: -1,
        lazyQueueIds: null,
        lazyQueueIndex: -1,
      });
      usePlaybackStore.setState({
        currentTrack: null,
        isPlaying: false,
        isLoadingAudio: false,
      });
      persistCombinedState();
      return;
    }

    const shuffle = usePlaybackStore.getState().shuffle;
    const windowIds = resolvedIds.slice(0, WINDOW_SIZE);

    set({
      queue: [],
      queueIndex: -1,
      shuffleOrder: [],
      shuffleIndex: -1,
      lazyQueueIds: resolvedIds,
      lazyQueueIndex: windowIds.length,
      queueSource: source || null,
    });

    // Optimistic state: show loading indicator and start audio load immediately
    if (options?.initialTrack) {
      usePlaybackStore.setState({
        currentTrack: options.initialTrack,
        isPlaying: true,
        currentTime: 0,
        isLoadingAudio: true,
      });
    }

    try {
      const tracks = await tracksApi.getBatch(windowIds);
      if (tracks.length > 0) {
        const queueItems: QueueItem[] = tracks.map(track => ({
          track,
          queueId: generateQueueId(),
        }));

        let shuffleOrder: number[] = [];
        let shuffleIndex = -1;
        if (shuffle && queueItems.length > 1) {
          shuffleOrder = generateShuffleOrder(queueItems.length, 0);
          shuffleIndex = 0;
        }

        set({
          queue: queueItems,
          queueIndex: 0,
          shuffleOrder,
          shuffleIndex,
        });
        usePlaybackStore.setState({
          currentTrack: queueItems[0].track,
          isPlaying: true,
          currentTime: 0,
          isLoadingAudio: true,
        });
        persistCombinedState();
      } else if (options?.initialTrack) {
        // getBatch returned empty — clean up optimistic state
        usePlaybackStore.setState({ currentTrack: null, isPlaying: false, isLoadingAudio: false });
      }
    } catch (error) {
      log.error('Failed to start lazy queue:', error);
      set({
        lazyQueueIds: null,
        lazyQueueIndex: -1,
      });
      if (options?.initialTrack) {
        usePlaybackStore.setState({ currentTrack: null, isPlaying: false, isLoadingAudio: false });
      }
    }
  },

  exitLazyMode: () => {
    set({ lazyQueueIds: null, lazyQueueIndex: -1, queueSource: null });
  },

  getNextTrack: () => {
    const { queue, queueIndex, shuffleOrder, shuffleIndex } = get();
    const { shuffle, repeat } = usePlaybackStore.getState();

    if (queue.length === 0) return null;

    let nextQueueIndex: number;

    if (shuffle && shuffleOrder.length > 0) {
      const nextShuffleIndex = shuffleIndex + 1;
      if (nextShuffleIndex >= shuffleOrder.length) {
        if (repeat === 'all') {
          return queue[0]?.track || null;
        }
        return null;
      }
      nextQueueIndex = shuffleOrder[nextShuffleIndex];
    } else {
      nextQueueIndex = queueIndex + 1;
      if (nextQueueIndex >= queue.length) {
        if (repeat === 'all') {
          nextQueueIndex = 0;
        } else {
          return null;
        }
      }
    }

    return queue[nextQueueIndex]?.track || null;
  },

  getUpcomingTrackIds: (count: number): string[] => {
    const { queue, queueIndex, shuffleOrder, shuffleIndex } = get();
    const { shuffle, repeat } = usePlaybackStore.getState();
    if (queue.length === 0 || count <= 0) return [];
    if (repeat === 'one') return [];

    const result: string[] = [];

    for (let step = 1; step <= count; step++) {
      let idx: number;

      if (shuffle && shuffleOrder.length > 0) {
        const si = shuffleIndex + step;
        if (si >= shuffleOrder.length) {
          if (repeat === 'all') break;
          break;
        }
        idx = shuffleOrder[si];
      } else {
        idx = queueIndex + step;
        if (idx >= queue.length) {
          if (repeat === 'all') {
            idx = idx % queue.length;
          } else {
            break;
          }
        }
      }

      const trackId = queue[idx]?.track?.id;
      if (trackId && !result.includes(trackId)) {
        result.push(trackId);
      }
    }

    return result;
  },

  advanceToNextTrack: (track, options) => {
    // Only caller is the crossfade path in useAudioEngine.
    const reason = normalizeAdvanceReason(options?.reason ?? 'crossfade');
    const { queueIndex, shuffleOrder, shuffleIndex, queue } = get();
    const { shuffle, repeat, consume, currentTrack } = usePlaybackStore.getState();
    log.info('advanceToNextTrack (crossfade)', { from: currentTrack?.title, to: track.title, toId: track.id });

    if (currentTrack) {
      set((s) => ({
        history: [...s.history.slice(-49), currentTrack],
      }));
    }

    const trackIndex = queue.findIndex(item => item.track.id === track.id);
    let newQueueIndex = trackIndex >= 0 ? trackIndex : queueIndex + 1;

    // Consume mode: remove the finished track (skip for repeat-one)
    if (consume && repeat !== 'one' && queueIndex >= 0 && queueIndex < queue.length) {
      const removedIndex = queueIndex;
      const newQueue = [...queue];
      newQueue.splice(removedIndex, 1);

      if (newQueue.length === 0) {
        set({ queue: [], queueIndex: -1, shuffleOrder: [], shuffleIndex: -1 });
        usePlaybackStore.setState({ isPlaying: false, crossfadeState: 'idle', nextTrackPreloaded: false });
        persistCombinedState();
        return;
      }

      const newTrackIndex = newQueue.findIndex(item => item.track.id === track.id);
      newQueueIndex = newTrackIndex >= 0 ? newTrackIndex : 0;

      let newShuffleOrder = shuffleOrder;
      let newShuffleIndex = shuffleIndex;
      if (shuffle) {
        newShuffleOrder = shuffleOrder
          .filter(i => i !== removedIndex)
          .map(i => i > removedIndex ? i - 1 : i);
        const posInShuffle = newShuffleOrder.indexOf(newQueueIndex);
        newShuffleIndex = posInShuffle >= 0 ? posInShuffle : 0;
      }

      set({
        queue: newQueue,
        queueIndex: newQueueIndex,
        shuffleIndex: newShuffleIndex,
        shuffleOrder: newShuffleOrder,
      });
      usePlaybackStore.setState({
        currentTrack: track,
        currentTime: 0,
      });
      persistCombinedState();
      refillFromReservoir();
      return;
    }

    set({
      queueIndex: newQueueIndex,
      shuffleIndex: shuffle ? Math.min(shuffleIndex + 1, shuffleOrder.length) : shuffleIndex,
    });
    usePlaybackStore.setState({
      currentTrack: track,
      _advanceReason: reason,
      currentTime: 0,
    });
    persistCombinedState();
    refillFromReservoir();
  },

  toggleShuffle: async () => {
    const { queue, queueIndex, lazyQueueIds, queueSource } = get();
    const playback = usePlaybackStore.getState();
    const shuffle = playback.shuffle;
    const currentTrack = playback.currentTrack;
    const newShuffle = !shuffle;
    const previousShuffle = shuffle;

    // Handle lazy queue mode with library source
    if (lazyQueueIds && lazyQueueIds.length > 0 && queueSource?.type === 'library') {
      usePlaybackStore.setState({ shuffle: newShuffle });

      try {
        const weightState = useShuffleWeightStore.getState();
        const useWeighted = newShuffle && weightState.enabled && weightState.activePreset;
        const response = await tracksApi.getIds({
          shuffle: newShuffle && !useWeighted,
          shuffle_preset: useWeighted ? weightState.activePreset! : undefined,
          start_with: currentTrack?.id,
          ...queueSource.filters,
        });

        if (response.ids.length > 0) {
          const windowIds = response.ids.slice(0, WINDOW_SIZE);
          const tracks = await tracksApi.getBatch(windowIds);

          if (tracks.length > 0) {
            const queueItems: QueueItem[] = tracks.map(track => ({
              track,
              queueId: generateQueueId(),
            }));

            const currentIdx = currentTrack
              ? queueItems.findIndex(item => item.track.id === currentTrack.id)
              : -1;
            if (currentIdx > 0) {
              const [item] = queueItems.splice(currentIdx, 1);
              queueItems.unshift(item);
            }

            let shuffleOrder: number[] = [];
            let shuffleIndex = -1;
            if (newShuffle && queueItems.length > 1) {
              shuffleOrder = generateShuffleOrder(queueItems.length, 0);
              shuffleIndex = 0;
            }

            set({
              lazyQueueIds: response.ids,
              lazyQueueIndex: windowIds.length,
              queue: queueItems,
              queueIndex: 0,
              shuffleOrder,
              shuffleIndex,
            });
            usePlaybackStore.setState({
              currentTrack: queueItems[0].track,
            });
          }
        }
        persistCombinedState();
      } catch (error) {
        log.error('Failed to refresh lazy queue with new shuffle state:', error);
        usePlaybackStore.setState({ shuffle: previousShuffle });
        persistCombinedState();
      }

      return;
    }

    // Standard queue mode
    if (newShuffle) {
      const shuffleOrder = queue.length > 1
        ? generateShuffleOrder(queue.length, queueIndex)
        : [];
      usePlaybackStore.setState({ shuffle: true });
      set({ shuffleOrder, shuffleIndex: shuffleOrder.length > 0 ? 0 : -1 });
    } else {
      usePlaybackStore.setState({ shuffle: false });
      set({ shuffleOrder: [], shuffleIndex: -1 });
    }
    persistCombinedState();
  },

  hydrate: async () => {
    const myVersion = ++hydrationVersion;

    try {
      await migrateOldPlayerState();
      if (myVersion !== hydrationVersion) return;

      const persisted = await loadPlayerState();
      if (myVersion !== hydrationVersion) return;

      if (!persisted) {
        usePlaybackStore.setState({ isHydrated: true });
        return;
      }

      // Phase 1: Immediately set playback settings + mark hydrated
      usePlaybackStore.setState({
        volume: persisted.volume,
        shuffle: persisted.shuffle,
        repeat: persisted.repeat,
        consume: persisted.consume ?? false,
        currentTime: persisted.currentTime ?? 0,
        isPlaying: false,
        isHydrated: true,
      });
      set({
        isQueueHydrating: persisted.queueTrackIds.length > 0,
      });

      if (persisted.queueTrackIds.length === 0) return;

      // Phase 1b: Fetch just the current track
      if (persisted.currentTrackId) {
        try {
          const [currentTrack] = await tracksApi.getBatch([persisted.currentTrackId]);
          if (myVersion !== hydrationVersion) return;
          if (currentTrack) {
            usePlaybackStore.setState({ currentTrack });
          }
        } catch {
          // Non-fatal
        }
      }

      if (myVersion !== hydrationVersion) return;

      // Phase 2: Fetch the full queue
      const tracks = await fetchTracksBatched(persisted.queueTrackIds);
      if (myVersion !== hydrationVersion) return;

      const queue: QueueItem[] = tracks.map((track) => ({
        track,
        queueId: generateQueueId(),
      }));

      const clampedQueueIndex = queue.length > 0
        ? Math.min(persisted.queueIndex, queue.length - 1)
        : -1;
      const currentTrack = clampedQueueIndex >= 0 ? queue[clampedQueueIndex]?.track || null : null;
      const clampedShuffleOrder = (persisted.shuffleOrder || []).filter(i => i < queue.length);

      const existingTrackId = usePlaybackStore.getState().currentTrack?.id;
      set({
        queue,
        queueIndex: clampedQueueIndex,
        isQueueHydrating: false,
        shuffleOrder: clampedShuffleOrder,
        shuffleIndex: persisted.shuffleIndex ?? -1,
      });
      if (currentTrack?.id !== existingTrackId) {
        usePlaybackStore.setState({ currentTrack });
      }
    } catch (error) {
      log.error('Failed to hydrate player state:', error);
      usePlaybackStore.setState({ isHydrated: true });
      set({ isQueueHydrating: false });
    }
  },

  resetForProfileSwitch: () => {
    ++hydrationVersion;
    set({
      queue: [],
      queueIndex: -1,
      history: [],
      shuffleOrder: [],
      shuffleIndex: -1,
      lazyQueueIds: null,
      lazyQueueIndex: -1,
      queueSource: null,
      isQueueHydrating: false,
    });
    usePlaybackStore.setState({
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
      isHydrated: false,
      _circuitBreakerTimestamps: [],
      _advanceReason: 'system',
    });
  },
}));

// Wire the queue state getter for persistenceAdapter
_setQueueStateGetter(() => {
  const s = useQueueStore.getState();
  return { queue: s.queue, queueIndex: s.queueIndex, shuffleOrder: s.shuffleOrder, shuffleIndex: s.shuffleIndex };
});
