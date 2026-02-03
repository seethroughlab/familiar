import { create } from 'zustand';
import type { Track, QueueItem } from '../types';
import {
  debouncedSavePlayerState,
  loadPlayerState,
  fetchTracksByIds,
  migrateOldPlayerState,
} from '../services/playerPersistence';
import { tracksApi } from '../api/client';

type RepeatMode = 'off' | 'all' | 'one';
type CrossfadeState = 'idle' | 'preloading' | 'crossfading';

// Queue source tracking - where the current queue originated from
export type QueueSourceType = 'library' | 'album' | 'playlist' | 'artist' | 'other';

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

// Preview track for external/missing tracks
export interface PreviewTrack {
  id: string;
  title: string;
  artist: string;
  previewUrl: string;
}

interface PlayerState {
  // Current playback
  currentTrack: Track | null;
  isPlaying: boolean;
  currentTime: number;
  duration: number;
  volume: number;

  // Preview mode (for external tracks)
  isPreviewMode: boolean;
  previewTrack: PreviewTrack | null;

  // Playback modes
  shuffle: boolean;
  repeat: RepeatMode;

  // Queue
  queue: QueueItem[];
  queueIndex: number;
  history: Track[];

  // Shuffle state
  shuffleOrder: number[];  // Randomized queue indices when shuffle is on
  shuffleIndex: number;    // Current position in shuffleOrder (-1 when off)

  // Lazy queue state (for shuffle-all with large libraries)
  lazyQueueIds: string[] | null;  // Track IDs only, null when not in lazy mode
  lazyQueueIndex: number;         // Current position in lazy queue
  prefetchedTracks: Map<string, Track>;  // Cache of fetched track metadata
  isFetchingTrack: boolean;       // Loading state for track fetches

  // Queue source tracking
  queueSource: QueueSource | null;  // Where the current queue originated from

  // Crossfade state
  crossfadeState: CrossfadeState;
  nextTrackPreloaded: boolean;

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

  // Queue actions
  addToQueue: (track: Track) => void;
  removeFromQueue: (queueId: string) => void;
  clearQueue: () => void;
  playTrack: (track: Track) => void;
  playNext: () => void;
  playPrevious: () => void;
  setQueue: (tracks: Track[], startIndex?: number, source?: QueueSource) => void;
  reorderQueue: (fromIndex: number, toIndex: number) => void;
  jumpToQueueIndex: (index: number) => void;

  // Lazy queue actions
  setLazyQueue: (ids: string[], source?: QueueSource) => Promise<void>;
  exitLazyMode: () => void;

  // Crossfade actions
  setCrossfadeState: (state: CrossfadeState) => void;
  setNextTrackPreloaded: (preloaded: boolean) => void;
  getNextTrack: () => Track | null;
  advanceToNextTrack: (track: Track) => void;

  // Hydration
  hydrate: () => Promise<void>;
  resetForProfileSwitch: () => void;

  // Preview playback (for external tracks)
  playPreview: (track: PreviewTrack) => void;
  stopPreview: () => void;
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
    queue: state.queue,
    queueIndex: state.queueIndex,
    currentTrack: state.currentTrack,
    shuffleOrder: state.shuffleOrder,
    shuffleIndex: state.shuffleIndex,
  });
};

// Helper to prefetch upcoming tracks in lazy mode
const prefetchUpcomingTracks = async (
  ids: string[],
  currentIndex: number,
  prefetchedTracks: Map<string, Track>,
  count: number = 3
) => {
  const idsToFetch: string[] = [];
  for (let i = 1; i <= count && currentIndex + i < ids.length; i++) {
    const id = ids[currentIndex + i];
    if (id && !prefetchedTracks.has(id)) {
      idsToFetch.push(id);
    }
  }

  if (idsToFetch.length > 0) {
    try {
      const tracks = await tracksApi.getBatch(idsToFetch);
      const newPrefetched = new Map(prefetchedTracks);
      tracks.forEach(track => {
        newPrefetched.set(track.id, track);
      });
      return newPrefetched;
    } catch (error) {
      console.error('Failed to prefetch tracks:', error);
    }
  }
  return prefetchedTracks;
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
  queue: [],
  queueIndex: -1,
  history: [],
  shuffleOrder: [],
  shuffleIndex: -1,
  lazyQueueIds: null,
  lazyQueueIndex: -1,
  prefetchedTracks: new Map(),
  isFetchingTrack: false,
  queueSource: null,
  crossfadeState: 'idle',
  nextTrackPreloaded: false,
  isHydrated: false,
  isPreviewMode: false,
  previewTrack: null,

  // Setters
  setCurrentTrack: (track) => {
    set({ currentTrack: track });
    persistState();
  },
  setIsPlaying: (playing) => set({ isPlaying: playing }),
  setCurrentTime: (time) => set({ currentTime: time }),
  setDuration: (duration) => set({ duration: duration }),
  setVolume: (volume) => {
    set({ volume: Math.max(0, Math.min(1, volume)) });
    persistState();
  },
  toggleShuffle: async () => {
    const { shuffle, queue, queueIndex, lazyQueueIds, queueSource, currentTrack } = get();
    const newShuffle = !shuffle;

    // Handle lazy queue mode with library source - re-fetch IDs from server
    if (lazyQueueIds && lazyQueueIds.length > 0 && queueSource?.type === 'library') {
      set({ shuffle: newShuffle });

      try {
        // Re-fetch IDs with new shuffle state, keeping current track first
        const response = await tracksApi.getIds({
          shuffle: newShuffle,
          start_with: currentTrack?.id,
          ...queueSource.filters,
        });

        if (response.ids.length > 0) {
          // Find current track's position in new order (should be 0 due to start_with)
          const newIndex = currentTrack
            ? response.ids.findIndex(id => id === currentTrack.id)
            : 0;

          set({
            lazyQueueIds: response.ids,
            lazyQueueIndex: newIndex >= 0 ? newIndex : 0,
          });
        }
      } catch (error) {
        console.error('Failed to refresh lazy queue with new shuffle state:', error);
      }

      persistState();
      return;
    }

    // Standard queue mode
    if (newShuffle && queue.length > 1) {
      // Enabling shuffle: generate order starting from current track
      const shuffleOrder = generateShuffleOrder(queue.length, queueIndex);
      set({ shuffle: true, shuffleOrder, shuffleIndex: 0 });
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

  // Queue actions
  addToQueue: (track) => {
    const { queue, shuffle, shuffleOrder } = get();
    const newIndex = queue.length; // Index of new track in queue

    set((state) => ({
      queue: [...state.queue, { track, queueId: generateQueueId() }],
      // Append new track to shuffle order if shuffle is on
      shuffleOrder: shuffle ? [...shuffleOrder, newIndex] : state.shuffleOrder,
    }));
    persistState();
  },

  removeFromQueue: (queueId) => {
    set((state) => ({
      queue: state.queue.filter((item) => item.queueId !== queueId),
    }));
    persistState();
  },

  clearQueue: () => {
    set({ queue: [], queueIndex: -1 });
    persistState();
  },

  playTrack: (track) => {
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
    });
    persistState();
  },

  playNext: async () => {
    const { queue, queueIndex, shuffle, shuffleOrder, shuffleIndex, repeat, currentTrack, lazyQueueIds, lazyQueueIndex, prefetchedTracks, isFetchingTrack } = get();

    // Handle lazy queue mode
    if (lazyQueueIds && lazyQueueIds.length > 0) {
      if (isFetchingTrack) return; // Prevent concurrent fetches

      // Add current track to history
      if (currentTrack) {
        set((s) => ({
          history: [...s.history.slice(-49), s.currentTrack!],
        }));
      }

      let nextLazyIndex = lazyQueueIndex + 1;
      if (nextLazyIndex >= lazyQueueIds.length) {
        if (repeat === 'all') {
          nextLazyIndex = 0;
        } else {
          set({ isPlaying: false });
          return;
        }
      }

      const nextTrackId = lazyQueueIds[nextLazyIndex];
      let nextTrack = prefetchedTracks.get(nextTrackId);

      // Fetch track if not prefetched
      if (!nextTrack) {
        set({ isFetchingTrack: true });
        try {
          const tracks = await tracksApi.getBatch([nextTrackId]);
          if (tracks.length > 0) {
            nextTrack = tracks[0];
            const newPrefetched = new Map(prefetchedTracks);
            newPrefetched.set(nextTrackId, nextTrack);
            set({ prefetchedTracks: newPrefetched });
          }
        } catch (error) {
          console.error('Failed to fetch next track:', error);
          set({ isFetchingTrack: false });
          return;
        }
        set({ isFetchingTrack: false });
      }

      if (nextTrack) {
        set({
          lazyQueueIndex: nextLazyIndex,
          currentTrack: nextTrack,
          isPlaying: true,
          currentTime: 0,
        });

        // Prefetch upcoming tracks in background
        prefetchUpcomingTracks(lazyQueueIds, nextLazyIndex, get().prefetchedTracks, 3)
          .then(newPrefetched => {
            if (newPrefetched !== get().prefetchedTracks) {
              set({ prefetchedTracks: newPrefetched });
            }
          });
      }
      return;
    }

    // Standard queue mode
    if (queue.length === 0) {
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
          set({ isPlaying: false });
          return;
        }
      }
    }

    set({
      queueIndex: nextQueueIndex,
      currentTrack: queue[nextQueueIndex].track,
      isPlaying: true,
      currentTime: 0,
      shuffleIndex: newShuffleIndex,
      shuffleOrder: newShuffleOrder,
    });
    persistState();
  },

  playPrevious: () => {
    const state = get();
    // If we're more than 3 seconds in, restart current track
    if (state.currentTime > 3) {
      set({ currentTime: 0 });
      return;
    }

    // Otherwise go to previous in history
    if (state.history.length > 0) {
      const prevTrack = state.history[state.history.length - 1];
      set((s) => ({
        currentTrack: prevTrack,
        history: s.history.slice(0, -1),
        isPlaying: true,
        currentTime: 0,
        queueIndex: Math.max(-1, s.queueIndex - 1),
      }));
      persistState();
    }
  },

  setQueue: (tracks, startIndex = 0, source?: QueueSource) => {
    const { shuffle } = get();
    const queueItems = tracks.map((track) => ({
      track,
      queueId: generateQueueId(),
    }));

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
      shuffleOrder,
      shuffleIndex,
      // Exit lazy mode when setting a regular queue
      lazyQueueIds: null,
      lazyQueueIndex: -1,
      prefetchedTracks: new Map(),
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

  jumpToQueueIndex: (index: number) => {
    const { queue, currentTrack } = get();
    if (index < 0 || index >= queue.length) {
      return;
    }

    const targetItem = queue[index];
    if (!targetItem) return;

    // Add current track to history if exists
    if (currentTrack) {
      set((s) => ({
        history: [...s.history.slice(-49), s.currentTrack!],
      }));
    }

    set({
      queueIndex: index,
      currentTrack: targetItem.track,
      isPlaying: true,
      currentTime: 0,
    });
    persistState();
  },

  // Lazy queue actions (for shuffle-all with large libraries)
  setLazyQueue: async (ids: string[], source?: QueueSource) => {
    if (ids.length === 0) return;

    // Clear regular queue state and enter lazy mode
    set({
      queue: [],
      queueIndex: -1,
      shuffleOrder: [],
      shuffleIndex: -1,
      lazyQueueIds: ids,
      lazyQueueIndex: 0,
      prefetchedTracks: new Map(),
      isFetchingTrack: true,
      queueSource: source || null,
    });

    // Fetch the first track and start playback
    try {
      const firstTrackId = ids[0];
      const tracks = await tracksApi.getBatch([firstTrackId]);
      if (tracks.length > 0) {
        const firstTrack = tracks[0];
        const prefetched = new Map<string, Track>();
        prefetched.set(firstTrackId, firstTrack);

        // Fetch next few tracks for prefetching
        const prefetchIds = ids.slice(1, 4);
        if (prefetchIds.length > 0) {
          const prefetchTracks = await tracksApi.getBatch(prefetchIds);
          prefetchTracks.forEach(t => prefetched.set(t.id, t));
        }

        set({
          currentTrack: firstTrack,
          isPlaying: true,
          currentTime: 0,
          prefetchedTracks: prefetched,
          isFetchingTrack: false,
        });
      } else {
        set({ isFetchingTrack: false });
      }
    } catch (error) {
      console.error('Failed to start lazy queue:', error);
      set({
        lazyQueueIds: null,
        lazyQueueIndex: -1,
        isFetchingTrack: false,
      });
    }
  },

  exitLazyMode: () => {
    set({
      lazyQueueIds: null,
      lazyQueueIndex: -1,
      prefetchedTracks: new Map(),
      isFetchingTrack: false,
      queueSource: null,
    });
  },

  // Crossfade actions
  setCrossfadeState: (crossfadeState) => set({ crossfadeState }),

  setNextTrackPreloaded: (nextTrackPreloaded) => set({ nextTrackPreloaded }),

  getNextTrack: () => {
    const { queue, queueIndex, shuffle, shuffleOrder, shuffleIndex, repeat, lazyQueueIds, lazyQueueIndex, prefetchedTracks } = get();

    // Handle lazy queue mode
    if (lazyQueueIds && lazyQueueIds.length > 0) {
      let nextLazyIndex = lazyQueueIndex + 1;
      if (nextLazyIndex >= lazyQueueIds.length) {
        if (repeat === 'all') {
          nextLazyIndex = 0;
        } else {
          return null;
        }
      }
      const nextTrackId = lazyQueueIds[nextLazyIndex];
      return prefetchedTracks.get(nextTrackId) || null;
    }

    // Standard queue mode
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
    const { queueIndex, shuffle, shuffleIndex, currentTrack, queue } = get();

    // Add current track to history
    if (currentTrack) {
      set((s) => ({
        history: [...s.history.slice(-49), s.currentTrack!],
      }));
    }

    // Find the queue index for the advanced track
    const trackIndex = queue.findIndex(item => item.track.id === track.id);
    const newQueueIndex = trackIndex >= 0 ? trackIndex : queueIndex + 1;

    set({
      currentTrack: track,
      queueIndex: newQueueIndex,
      currentTime: 0,
      crossfadeState: 'idle',
      nextTrackPreloaded: false,
      shuffleIndex: shuffle ? shuffleIndex + 1 : shuffleIndex,
    });
    persistState();
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
        queue,
        queueIndex: persisted.queueIndex,
        currentTrack,
        isPlaying: false, // Don't auto-play on hydration
        isHydrated: true,
        shuffleOrder: persisted.shuffleOrder || [],
        shuffleIndex: persisted.shuffleIndex ?? -1,
      });
    } catch (error) {
      console.error('Failed to hydrate player state:', error);
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
      queue: [],
      queueIndex: -1,
      history: [],
      shuffleOrder: [],
      shuffleIndex: -1,
      lazyQueueIds: null,
      lazyQueueIndex: -1,
      prefetchedTracks: new Map(),
      isFetchingTrack: false,
      queueSource: null,
      crossfadeState: 'idle',
      nextTrackPreloaded: false,
      isHydrated: false,
      isPreviewMode: false,
      previewTrack: null,
    });
  },

  // Preview playback for external tracks (30-sec previews)
  playPreview: (track: PreviewTrack) => {
    // Stop regular playback first
    set({
      isPlaying: false,
      isPreviewMode: true,
      previewTrack: track,
    });
  },

  stopPreview: () => {
    set({
      isPreviewMode: false,
      previewTrack: null,
    });
  },
}));
