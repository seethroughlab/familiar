import { create } from 'zustand';
import type { Track, QueueItem } from '../types';
import {
  debouncedSavePlayerState,
  loadPlayerState,
  fetchTracksByIds,
  migrateOldPlayerState,
} from '../services/playerPersistence';
import { tracksApi } from '../api/client';
import { createLogger } from '../utils/logger';

const log = createLogger('Player', { forceVerbose: true });

type RepeatMode = 'off' | 'all' | 'one';
type CrossfadeState = 'idle' | 'preloading' | 'crossfading';

// Queue source tracking - where the current queue originated from
export type QueueSourceType = 'library' | 'album' | 'playlist' | 'artist' | 'ephemeral' | 'other';

export interface LibraryFilters {
  search?: string;
  artist?: string;
  album?: string;
  genre?: string;
  year_from?: number;
  year_to?: number;
  energy_min?: number;
  energy_max?: number;
  valence_min?: number;
  valence_max?: number;
}

export interface QueueSource {
  type: QueueSourceType;
  id?: string;  // Playlist ID, album hash, artist name, etc.
  filters?: LibraryFilters;  // For library context, to re-fetch with new shuffle state
}

interface PlayerState {
  // Current playback
  currentTrack: Track | null;
  isPlaying: boolean;
  currentTime: number;
  duration: number;
  volume: number;

  // Playback modes
  shuffle: boolean;
  repeat: RepeatMode;
  consume: boolean;

  // Queue
  queue: QueueItem[];
  queueIndex: number;
  history: Track[];

  // Shuffle state
  shuffleOrder: number[];  // Randomized queue indices when shuffle is on
  shuffleIndex: number;    // Current position in shuffleOrder (-1 when off)

  // Lazy queue state (for shuffle-all with large libraries)
  lazyQueueIds: string[] | null;  // Track IDs only, null when not in lazy mode
  lazyQueueIndex: number;         // Current position in lazy queue (next ID to materialize)

  // Queue source tracking
  queueSource: QueueSource | null;  // Where the current queue originated from

  // Crossfade state
  crossfadeState: CrossfadeState;
  nextTrackPreloaded: boolean;

  // Audio loading state (for play button spinner)
  isLoadingAudio: boolean;

  // Hydration
  isHydrated: boolean;

  // Actions
  setCurrentTrack: (track: Track | null) => void;
  setIsPlaying: (playing: boolean) => void;
  setCurrentTime: (time: number) => void;
  setDuration: (duration: number) => void;
  setVolume: (volume: number) => void;
  toggleShuffle: () => void | Promise<void>;
  toggleRepeat: () => void;
  toggleConsume: () => void;

  // Queue actions
  addToQueue: (track: Track, insertIndex?: number, shuffleInsertPosition?: number) => void;
  removeFromQueue: (queueId: string) => void;
  clearQueue: () => void;
  playTrack: (track: Track) => void;
  playNext: () => void;
  playPrevious: () => void;
  setQueue: (tracks: Track[], startIndex?: number, source?: QueueSource) => void;
  reorderQueue: (fromIndex: number, toIndex: number) => void;
  reorderShuffleOrder: (fromIndex: number, toIndex: number) => void;
  jumpToQueueIndex: (index: number) => void;

  // Lazy queue actions
  setLazyQueue: (ids: string[], source?: QueueSource) => Promise<void>;
  exitLazyMode: () => void;

  // Crossfade actions
  setCrossfadeState: (state: CrossfadeState) => void;
  setNextTrackPreloaded: (preloaded: boolean) => void;
  getNextTrack: () => Track | null;
  advanceToNextTrack: (track: Track) => void;

  // Audio loading actions
  setIsLoadingAudio: (loading: boolean) => void;

  // Hydration
  hydrate: () => Promise<void>;
  resetForProfileSwitch: () => void;
}

let queueIdCounter = 0;
const generateQueueId = () => `queue-${++queueIdCounter}`;

// Generate a shuffled order of queue indices, with current track first
function generateShuffleOrder(queueLength: number, currentIndex: number): number[] {
  if (queueLength <= 1) return queueLength === 1 ? [0] : [];

  const indices = Array.from({ length: queueLength }, (_, i) => i);
  const rest = indices.filter(i => i !== currentIndex);

  // Fisher-Yates shuffle
  for (let i = rest.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [rest[i], rest[j]] = [rest[j], rest[i]];
  }

  // Current track first, then shuffled rest
  return currentIndex >= 0 ? [currentIndex, ...rest] : rest;
}

// Helper to persist state after changes
const persistState = () => {
  const state = usePlayerStore.getState();
  debouncedSavePlayerState({
    volume: state.volume,
    shuffle: state.shuffle,
    repeat: state.repeat,
    consume: state.consume,
    queue: state.queue,
    queueIndex: state.queueIndex,
    currentTrack: state.currentTrack,
    shuffleOrder: state.shuffleOrder,
    shuffleIndex: state.shuffleIndex,
    currentTime: state.currentTime,
  });
};

// Lazy reservoir constants
const WINDOW_SIZE = 50;        // Initial materialization from reservoir
const REFILL_THRESHOLD = 10;   // Refill when this many tracks remain ahead
const REFILL_BATCH = 20;       // How many to fetch per refill

// Concurrency guard for reservoir refills
let isRefilling = false;

// Helper to refill queue from the lazy reservoir.
// Self-contained: checks threshold internally, so callers can call unconditionally.
const refillFromReservoir = async () => {
  if (isRefilling) return;

  const { lazyQueueIds, lazyQueueIndex, queue, queueIndex } = usePlayerStore.getState();
  if (!lazyQueueIds || lazyQueueIndex >= lazyQueueIds.length) return;

  // Check if refill is actually needed
  const remaining = queue.length - 1 - queueIndex;
  if (remaining > REFILL_THRESHOLD) return;

  isRefilling = true;
  try {
    const batchIds = lazyQueueIds.slice(lazyQueueIndex, lazyQueueIndex + REFILL_BATCH);
    if (batchIds.length === 0) return;

    const tracks = await tracksApi.getBatch(batchIds);
    if (tracks.length === 0) return;

    const newItems: QueueItem[] = tracks.map(track => ({
      track,
      queueId: generateQueueId(),
      // Attach externalInfo for external tracks so audio engine uses preview URLs
      externalInfo: track.track_type === 'external' ? {
        type: 'external' as const,
        previewUrl: track.preview_url || null,
        matchedTrackId: track.matched_track_id || null,
        originalId: track.id,
      } : undefined,
    }));

    // Re-read state after async gap
    const currentState = usePlayerStore.getState();
    const newQueue = [...currentState.queue, ...newItems];

    // If shuffle is on, insert new queue indices at random positions after current shuffleIndex
    let newShuffleOrder = currentState.shuffleOrder;
    if (currentState.shuffle && newShuffleOrder.length > 0) {
      newShuffleOrder = [...newShuffleOrder];
      const startIdx = currentState.queue.length;
      for (let i = 0; i < newItems.length; i++) {
        // Insert at random position after current shuffleIndex
        const insertPos = currentState.shuffleIndex + 1 + Math.floor(Math.random() * (newShuffleOrder.length - currentState.shuffleIndex));
        newShuffleOrder.splice(insertPos, 0, startIdx + i);
      }
    }

    usePlayerStore.setState({
      queue: newQueue,
      lazyQueueIndex: currentState.lazyQueueIndex + batchIds.length,
      shuffleOrder: newShuffleOrder,
    });
    persistState();
  } catch (error) {
    log.error('Failed to refill from reservoir:', error);
  } finally {
    isRefilling = false;
  }
};

export const usePlayerStore = create<PlayerState>((set, get) => ({
  // Initial state
  currentTrack: null,
  isPlaying: false,
  currentTime: 0,
  duration: 0,
  volume: 1,
  shuffle: false,
  repeat: 'off',
  consume: false,
  queue: [],
  queueIndex: -1,
  history: [],
  shuffleOrder: [],
  shuffleIndex: -1,
  lazyQueueIds: null,
  lazyQueueIndex: -1,
  queueSource: null,
  crossfadeState: 'idle',
  nextTrackPreloaded: false,
  isLoadingAudio: false,
  isHydrated: false,

  // Setters
  setCurrentTrack: (track) => {
    set({ currentTrack: track });
    persistState();
  },
  setIsPlaying: (playing) => set({ isPlaying: playing }),
  setCurrentTime: (time) => {
    set({ currentTime: time });
    persistState(); // Debounced - will save at most every 500ms
  },
  setDuration: (duration) => set({ duration: duration }),
  setVolume: (volume) => {
    set({ volume: Math.max(0, Math.min(1, volume)) });
    persistState();
  },
  toggleShuffle: async () => {
    const { shuffle, queue, queueIndex, lazyQueueIds, queueSource, currentTrack } = get();
    const newShuffle = !shuffle;
    const previousShuffle = shuffle;

    // Handle lazy queue mode with library source - re-fetch IDs from server and re-materialize
    if (lazyQueueIds && lazyQueueIds.length > 0 && queueSource?.type === 'library') {
      // Optimistic update - show new shuffle state immediately
      set({ shuffle: newShuffle });

      try {
        // Re-fetch IDs with new shuffle state, keeping current track first
        const response = await tracksApi.getIds({
          shuffle: newShuffle,
          start_with: currentTrack?.id,
          ...queueSource.filters,
        });

        if (response.ids.length > 0) {
          // Materialize a new window of tracks from the new ID order
          const windowIds = response.ids.slice(0, WINDOW_SIZE);
          const tracks = await tracksApi.getBatch(windowIds);

          if (tracks.length > 0) {
            const queueItems: QueueItem[] = tracks.map(track => ({
              track,
              queueId: generateQueueId(),
              externalInfo: track.track_type === 'external' ? {
                type: 'external' as const,
                previewUrl: track.preview_url || null,
                matchedTrackId: track.matched_track_id || null,
                originalId: track.id,
              } : undefined,
            }));

            // Keep current track at position 0 if present
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
              currentTrack: queueItems[0].track,
              shuffleOrder,
              shuffleIndex,
            });
          }
        }
        persistState();
      } catch (error) {
        log.error('Failed to refresh lazy queue with new shuffle state:', error);
        // Rollback shuffle state on failure
        set({ shuffle: previousShuffle });
        persistState();
      }

      return;
    }

    // Standard queue mode
    if (newShuffle) {
      // Enabling shuffle: generate order starting from current track (if queue has tracks)
      const shuffleOrder = queue.length > 1
        ? generateShuffleOrder(queue.length, queueIndex)
        : [];
      set({ shuffle: true, shuffleOrder, shuffleIndex: shuffleOrder.length > 0 ? 0 : -1 });
    } else {
      // Disabling shuffle: clear shuffle state, keep current track playing
      set({ shuffle: false, shuffleOrder: [], shuffleIndex: -1 });
    }
    persistState();
  },
  toggleRepeat: () => {
    set((state) => ({
      repeat: state.repeat === 'off' ? 'all' : state.repeat === 'all' ? 'one' : 'off'
    }));
    persistState();
  },
  toggleConsume: () => {
    set((state) => ({ consume: !state.consume }));
    persistState();
  },

  // Queue actions
  addToQueue: (track, insertIndex, shuffleInsertPosition) => {
    const { queue, queueIndex, shuffle, shuffleOrder } = get();

    const insertAt = insertIndex ?? queue.length;
    const newQueue = [...queue];
    newQueue.splice(insertAt, 0, { track, queueId: generateQueueId() });

    // Adjust queueIndex if inserting before or at current track
    const newQueueIndex = insertAt <= queueIndex ? queueIndex + 1 : queueIndex;

    // Rebuild shuffle order if shuffle is on
    let newShuffleOrder = shuffleOrder;
    if (shuffle) {
      newShuffleOrder = shuffleOrder.map(i => i >= insertAt ? i + 1 : i);
      if (shuffleInsertPosition !== undefined) {
        // Insert at specific display position (e.g. external drop in shuffle mode)
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
    persistState();
  },

  removeFromQueue: (queueId) => {
    const { queue, queueIndex, shuffle, shuffleOrder, shuffleIndex } = get();
    const removedIndex = queue.findIndex((item) => item.queueId === queueId);
    if (removedIndex === -1) return;

    const newQueue = queue.filter((item) => item.queueId !== queueId);
    let newQueueIndex = queueIndex;
    if (removedIndex < queueIndex) {
      newQueueIndex = queueIndex - 1;
    }

    // Adjust shuffle order if shuffle is on
    let newShuffleOrder = shuffleOrder;
    let newShuffleIndex = shuffleIndex;
    if (shuffle && shuffleOrder.length > 0) {
      newShuffleOrder = shuffleOrder
        .filter(i => i !== removedIndex)
        .map(i => i > removedIndex ? i - 1 : i);
      // Find current position in the new shuffle order
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
    persistState();
  },

  clearQueue: () => {
    log.info('clearQueue');
    set({ queue: [], queueIndex: -1, lazyQueueIds: null, lazyQueueIndex: -1, queueSource: null });
    persistState();
  },

  playTrack: (track) => {
    log.info('playTrack', { id: track.id, title: track.title });
    const state = get();
    // Add current track to history
    if (state.currentTrack) {
      set((s) => ({
        history: [...s.history.slice(-49), s.currentTrack!],
      }));
    }
    set({
      currentTrack: track,
      isPlaying: true,
      currentTime: 0,
      isLoadingAudio: true,
    });
    persistState();
  },

  playNext: async () => {
    const { queue, queueIndex, shuffle, shuffleOrder, shuffleIndex, repeat, consume, currentTrack } = get();

    if (queue.length === 0) {
      log.info('playNext — empty queue, stopping');
      set({ isPlaying: false });
      return;
    }

    // Add current track to history
    if (currentTrack) {
      set((s) => ({
        history: [...s.history.slice(-49), s.currentTrack!],
      }));
    }

    let nextQueueIndex: number;
    let newShuffleIndex = shuffleIndex;
    let newShuffleOrder = shuffleOrder;

    if (shuffle && shuffleOrder.length > 0) {
      // Shuffle mode: advance through shuffleOrder
      newShuffleIndex = shuffleIndex + 1;
      if (newShuffleIndex >= shuffleOrder.length) {
        // End of shuffled list
        if (repeat === 'all') {
          // Reshuffle and start over (keep current track position for reference)
          newShuffleOrder = generateShuffleOrder(queue.length, queueIndex);
          newShuffleIndex = 0;
          nextQueueIndex = newShuffleOrder[0];
        } else {
          log.info('playNext — end of shuffle order, stopping', { repeat, consume });
          set({ isPlaying: false });
          return;
        }
      } else {
        nextQueueIndex = shuffleOrder[newShuffleIndex];
      }
    } else {
      // Normal mode: sequential
      nextQueueIndex = queueIndex + 1;
      if (nextQueueIndex >= queue.length) {
        if (repeat === 'all') {
          nextQueueIndex = 0;
        } else {
          log.info('playNext — end of queue, stopping', { queueIndex, queueLength: queue.length, repeat, consume });
          set({ isPlaying: false });
          return;
        }
      }
    }

    // Consume mode: remove the finished track from the queue
    // Skip when repeat-one is active (repeat-one wins)
    if (consume && repeat !== 'one') {
      const removedIndex = queueIndex;
      const newQueue = [...queue];
      newQueue.splice(removedIndex, 1);

      if (newQueue.length === 0) {
        set({ queue: [], queueIndex: -1, isPlaying: false, shuffleOrder: [], shuffleIndex: -1 });
        persistState();
        return;
      }

      // Adjust nextQueueIndex since we removed an item
      if (nextQueueIndex > removedIndex) {
        nextQueueIndex -= 1;
      } else if (nextQueueIndex === removedIndex && nextQueueIndex >= newQueue.length) {
        // Wrapped around or was at end
        nextQueueIndex = 0;
      }

      // Adjust shuffle order: remove the old index and shift down
      if (shuffle) {
        newShuffleOrder = newShuffleOrder
          .filter(i => i !== removedIndex)
          .map(i => i > removedIndex ? i - 1 : i);
        // Re-find shuffleIndex pointing to our next track
        const posInShuffle = newShuffleOrder.indexOf(nextQueueIndex);
        newShuffleIndex = posInShuffle >= 0 ? posInShuffle : 0;
      }

      set({
        queue: newQueue,
        queueIndex: nextQueueIndex,
        currentTrack: newQueue[nextQueueIndex].track,
        isPlaying: true,
        currentTime: 0,
        isLoadingAudio: true,
        shuffleIndex: newShuffleIndex,
        shuffleOrder: newShuffleOrder,
      });
      persistState();
      refillFromReservoir();
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
      currentTrack: nextTrack,
      isPlaying: true,
      currentTime: 0,
      isLoadingAudio: true,
      shuffleIndex: newShuffleIndex,
      shuffleOrder: newShuffleOrder,
    });
    persistState();
    refillFromReservoir();
  },

  playPrevious: () => {
    const state = get();
    // If we're more than 3 seconds in, restart current track
    if (state.currentTime > 3) {
      log.info('playPrevious — restarting current track', { title: state.currentTrack?.title, currentTime: state.currentTime });
      set({ currentTime: 0 });
      return;
    }

    // Otherwise go to previous in history
    if (state.history.length > 0) {
      const prevTrack = state.history[state.history.length - 1];
      log.info('playPrevious — going to history track', { title: prevTrack.title, id: prevTrack.id });
      set((s) => ({
        currentTrack: prevTrack,
        history: s.history.slice(0, -1),
        isPlaying: true,
        currentTime: 0,
        isLoadingAudio: true,
        queueIndex: Math.max(-1, s.queueIndex - 1),
      }));
      persistState();
    }
  },

  setQueue: (tracks, startIndex = 0, source?: QueueSource) => {
    log.info('setQueue', { trackCount: tracks.length, startIndex, source: source?.type, sourceId: source?.id, shuffle: get().shuffle });
    const { shuffle } = get();
    // Support tracks with _externalInfo metadata from playlist views
    const queueItems = tracks.map((track) => {
      // Extract _externalInfo if present (added by playlist handlePlay)
      const trackWithMeta = track as Track & {
        _externalInfo?: {
          type: 'external';
          previewUrl: string | null;
          matchedTrackId: string | null;
          originalId?: string;
        };
      };
      const externalInfo = trackWithMeta._externalInfo;

      return {
        track,
        queueId: generateQueueId(),
        // Preserve external info for the audio engine to handle
        externalInfo: externalInfo ? {
          type: externalInfo.type,
          previewUrl: externalInfo.previewUrl,
          matchedTrackId: externalInfo.matchedTrackId,
          originalId: externalInfo.originalId,
        } : undefined,
      };
    });

    // Generate shuffle order if shuffle is enabled
    let shuffleOrder: number[] = [];
    let shuffleIndex = -1;
    if (shuffle && tracks.length > 1) {
      shuffleOrder = generateShuffleOrder(tracks.length, startIndex);
      shuffleIndex = 0;
    }

    set({
      queue: queueItems,
      queueIndex: startIndex,
      currentTrack: tracks[startIndex] || null,
      isPlaying: tracks.length > 0,
      currentTime: 0,
      isLoadingAudio: tracks.length > 0,
      shuffleOrder,
      shuffleIndex,
      // Exit lazy mode when setting a regular queue
      lazyQueueIds: null,
      lazyQueueIndex: -1,
      queueSource: source || null,
    });
    persistState();
  },

  reorderQueue: (fromIndex: number, toIndex: number) => {
    const { queue, queueIndex, currentTrack } = get();
    if (fromIndex < 0 || fromIndex >= queue.length || toIndex < 0 || toIndex >= queue.length) {
      return;
    }

    const newQueue = [...queue];
    const [removed] = newQueue.splice(fromIndex, 1);
    newQueue.splice(toIndex, 0, removed);

    // Adjust queueIndex to keep current track selected
    let newQueueIndex = queueIndex;
    if (currentTrack) {
      newQueueIndex = newQueue.findIndex(item => item.track.id === currentTrack.id);
    }

    set({
      queue: newQueue,
      queueIndex: newQueueIndex,
    });
    persistState();
  },

  reorderShuffleOrder: (fromIndex: number, toIndex: number) => {
    const { shuffleOrder, shuffleIndex } = get();
    if (fromIndex < 0 || fromIndex >= shuffleOrder.length || toIndex < 0 || toIndex >= shuffleOrder.length) {
      return;
    }

    const newOrder = [...shuffleOrder];
    const [removed] = newOrder.splice(fromIndex, 1);
    newOrder.splice(toIndex, 0, removed);

    // Adjust shuffleIndex to keep pointing at the currently playing track
    let newShuffleIndex = shuffleIndex;
    if (fromIndex === shuffleIndex) {
      newShuffleIndex = toIndex;
    } else if (fromIndex < shuffleIndex && toIndex >= shuffleIndex) {
      newShuffleIndex = shuffleIndex - 1;
    } else if (fromIndex > shuffleIndex && toIndex <= shuffleIndex) {
      newShuffleIndex = shuffleIndex + 1;
    }

    set({ shuffleOrder: newOrder, shuffleIndex: newShuffleIndex });
    persistState();
  },

  jumpToQueueIndex: (index: number) => {
    const { queue, currentTrack, shuffle, shuffleOrder } = get();
    if (index < 0 || index >= queue.length) {
      return;
    }

    const targetItem = queue[index];
    if (!targetItem) return;
    log.info('jumpToQueueIndex', { index, title: targetItem.track.title, id: targetItem.track.id });

    // Add current track to history if exists
    if (currentTrack) {
      set((s) => ({
        history: [...s.history.slice(-49), s.currentTrack!],
      }));
    }

    // Update shuffleIndex to match the jumped-to track
    let newShuffleIndex = get().shuffleIndex;
    if (shuffle && shuffleOrder.length > 0) {
      const pos = shuffleOrder.indexOf(index);
      if (pos >= 0) newShuffleIndex = pos;
    }

    set({
      queueIndex: index,
      currentTrack: targetItem.track,
      isPlaying: true,
      currentTime: 0,
      isLoadingAudio: true,
      shuffleIndex: newShuffleIndex,
    });
    persistState();
  },

  // Lazy queue actions (for shuffle-all with large libraries)
  setLazyQueue: async (ids: string[], source?: QueueSource) => {
    if (ids.length === 0) return;

    const { shuffle } = get();
    const windowIds = ids.slice(0, WINDOW_SIZE);

    // Set up lazy state immediately (loading state)
    set({
      queue: [],
      queueIndex: -1,
      shuffleOrder: [],
      shuffleIndex: -1,
      lazyQueueIds: ids,
      lazyQueueIndex: windowIds.length,
      queueSource: source || null,
    });

    // Fetch the initial window of tracks
    try {
      const tracks = await tracksApi.getBatch(windowIds);
      if (tracks.length > 0) {
        const queueItems: QueueItem[] = tracks.map(track => ({
          track,
          queueId: generateQueueId(),
          externalInfo: track.track_type === 'external' ? {
            type: 'external' as const,
            previewUrl: track.preview_url || null,
            matchedTrackId: track.matched_track_id || null,
            originalId: track.id,
          } : undefined,
        }));

        // Generate shuffle order if shuffle is enabled
        let shuffleOrder: number[] = [];
        let shuffleIndex = -1;
        if (shuffle && queueItems.length > 1) {
          shuffleOrder = generateShuffleOrder(queueItems.length, 0);
          shuffleIndex = 0;
        }

        set({
          queue: queueItems,
          queueIndex: 0,
          currentTrack: queueItems[0].track,
          isPlaying: true,
          currentTime: 0,
          isLoadingAudio: true,
          shuffleOrder,
          shuffleIndex,
        });
        persistState();
      }
    } catch (error) {
      log.error('Failed to start lazy queue:', error);
      set({
        lazyQueueIds: null,
        lazyQueueIndex: -1,
      });
    }
  },

  exitLazyMode: () => {
    set({ lazyQueueIds: null, lazyQueueIndex: -1, queueSource: null });
  },

  // Crossfade actions
  setCrossfadeState: (crossfadeState) => set({ crossfadeState }),

  setNextTrackPreloaded: (nextTrackPreloaded) => set({ nextTrackPreloaded }),

  setIsLoadingAudio: (isLoadingAudio) => set({ isLoadingAudio }),

  getNextTrack: () => {
    const { queue, queueIndex, shuffle, shuffleOrder, shuffleIndex, repeat } = get();

    if (queue.length === 0) return null;

    let nextQueueIndex: number;

    if (shuffle && shuffleOrder.length > 0) {
      const nextShuffleIndex = shuffleIndex + 1;
      if (nextShuffleIndex >= shuffleOrder.length) {
        // End of shuffled list - if repeat is on, we'd reshuffle but can't predict
        // Just return null for preloading purposes
        if (repeat === 'all') {
          return queue[0]?.track || null; // Approximate - actual will reshuffle
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

  advanceToNextTrack: (track) => {
    const { queueIndex, shuffle, shuffleIndex, shuffleOrder, repeat, consume, currentTrack, queue } = get();
    log.info('advanceToNextTrack (crossfade)', { from: currentTrack?.title, to: track.title, toId: track.id });

    // Add current track to history
    if (currentTrack) {
      set((s) => ({
        history: [...s.history.slice(-49), s.currentTrack!],
      }));
    }

    // Find the queue index for the advanced track
    const trackIndex = queue.findIndex(item => item.track.id === track.id);
    let newQueueIndex = trackIndex >= 0 ? trackIndex : queueIndex + 1;

    // Consume mode: remove the finished track (skip for repeat-one)
    if (consume && repeat !== 'one' && queueIndex >= 0 && queueIndex < queue.length) {
      const removedIndex = queueIndex;
      const newQueue = [...queue];
      newQueue.splice(removedIndex, 1);

      if (newQueue.length === 0) {
        set({ queue: [], queueIndex: -1, isPlaying: false, crossfadeState: 'idle', nextTrackPreloaded: false, shuffleOrder: [], shuffleIndex: -1 });
        persistState();
        return;
      }

      // Re-find the new track in the modified queue
      const newTrackIndex = newQueue.findIndex(item => item.track.id === track.id);
      newQueueIndex = newTrackIndex >= 0 ? newTrackIndex : 0;

      // Adjust shuffle order
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
        currentTrack: track,
        queueIndex: newQueueIndex,
        currentTime: 0,
        crossfadeState: 'idle',
        nextTrackPreloaded: false,
        shuffleIndex: newShuffleIndex,
        shuffleOrder: newShuffleOrder,
      });
      persistState();
      refillFromReservoir();
      return;
    }

    set({
      currentTrack: track,
      queueIndex: newQueueIndex,
      currentTime: 0,
      crossfadeState: 'idle',
      nextTrackPreloaded: false,
      shuffleIndex: shuffle ? shuffleIndex + 1 : shuffleIndex,
    });
    persistState();
    refillFromReservoir();
  },

  // Hydrate state from IndexedDB
  hydrate: async () => {
    try {
      // Migrate old player state from fixed ID to profile-based
      await migrateOldPlayerState();

      const persisted = await loadPlayerState();
      if (!persisted) {
        set({ isHydrated: true });
        return;
      }

      // Fetch tracks if we have queue track IDs
      let queue: QueueItem[] = [];
      let currentTrack: Track | null = null;

      if (persisted.queueTrackIds.length > 0) {
        const tracks = await fetchTracksByIds(persisted.queueTrackIds);
        queue = tracks.map((track) => ({
          track,
          queueId: generateQueueId(),
        }));

        // Find current track in queue
        if (persisted.currentTrackId && persisted.queueIndex >= 0) {
          currentTrack = queue[persisted.queueIndex]?.track || null;
        }
      }

      set({
        volume: persisted.volume,
        shuffle: persisted.shuffle,
        repeat: persisted.repeat,
        consume: persisted.consume ?? false,
        queue,
        queueIndex: persisted.queueIndex,
        currentTrack,
        currentTime: persisted.currentTime ?? 0,
        isPlaying: false, // Don't auto-play on hydration
        isHydrated: true,
        shuffleOrder: persisted.shuffleOrder || [],
        shuffleIndex: persisted.shuffleIndex ?? -1,
      });
    } catch (error) {
      log.error('Failed to hydrate player state:', error);
      set({ isHydrated: true });
    }
  },

  // Reset player state for profile switch (call before hydrate)
  resetForProfileSwitch: () => {
    set({
      currentTrack: null,
      isPlaying: false,
      currentTime: 0,
      duration: 0,
      volume: 1,
      shuffle: false,
      repeat: 'off',
      consume: false,
      queue: [],
      queueIndex: -1,
      history: [],
      shuffleOrder: [],
      shuffleIndex: -1,
      lazyQueueIds: null,
      lazyQueueIndex: -1,
      queueSource: null,
      crossfadeState: 'idle',
      nextTrackPreloaded: false,
      isHydrated: false,
    });
  },
}));
