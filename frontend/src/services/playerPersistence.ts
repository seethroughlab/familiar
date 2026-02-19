/**
 * Player state persistence service.
 * Saves and loads player state from IndexedDB per profile.
 * All operations silently fail if IndexedDB isn't available (iOS private browsing).
 */
import { db, isIndexedDBAvailable, type PersistedPlayerState } from '../db';
import { getSelectedProfileId } from './profileService';
import type { Track, QueueItem } from '../types';
import { tracksApi } from '../api/client';
import { createLogger } from '../utils/logger';

const log = createLogger('PlayerPersistence');

/**
 * Save player state to IndexedDB for the current profile.
 */
export async function savePlayerState(state: {
  volume: number;
  shuffle: boolean;
  repeat: 'off' | 'all' | 'one';
  consume: boolean;
  queue: QueueItem[];
  queueIndex: number;
  currentTrack: Track | null;
  shuffleOrder: number[];
  shuffleIndex: number;
  currentTime: number;
}): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return;

  const profileId = await getSelectedProfileId();
  if (!profileId) {
    return; // No profile selected, don't save
  }

  try {
    const persistedState: PersistedPlayerState = {
      id: profileId, // Use profile ID as record key
      volume: state.volume,
      shuffle: state.shuffle,
      repeat: state.repeat,
      consume: state.consume,
      queueTrackIds: state.queue.map((item) => item.track.id),
      queueIndex: state.queueIndex,
      currentTrackId: state.currentTrack?.id || null,
      shuffleOrder: state.shuffleOrder,
      shuffleIndex: state.shuffleIndex,
      currentTime: state.currentTime,
      updatedAt: new Date(),
    };

    await db.playerState.put(persistedState);
  } catch (error) {
    log.warn('Failed to save player state:', error);
  }
}

/**
 * Load player state from IndexedDB for the current profile.
 */
export async function loadPlayerState(): Promise<PersistedPlayerState | null> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return null;

  const profileId = await getSelectedProfileId();
  if (!profileId) {
    return null;
  }

  try {
    const state = await db.playerState.get(profileId);
    return state || null;
  } catch (error) {
    log.warn('Failed to load player state:', error);
    return null;
  }
}

/**
 * Load player state for a specific profile (used when switching profiles).
 */
export async function loadPlayerStateForProfile(profileId: string): Promise<PersistedPlayerState | null> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return null;

  try {
    const state = await db.playerState.get(profileId);
    return state || null;
  } catch (error) {
    log.warn('Failed to load player state for profile:', error);
    return null;
  }
}

/**
 * Fetch tracks by IDs from API using batch endpoint.
 * Chunks into groups of 50 (the batch endpoint limit) and fetches with limited
 * concurrency (3 at a time) to avoid saturating the browser's connection pool
 * — leaving connections free for audio streaming.
 * Returns tracks in the original ID order, skipping any that couldn't be fetched.
 */
const BATCH_CONCURRENCY = 3;

export async function fetchTracksBatched(trackIds: string[]): Promise<Track[]> {
  if (trackIds.length === 0) return [];

  try {
    // Chunk into groups of 50
    const chunks: string[][] = [];
    for (let i = 0; i < trackIds.length; i += 50) {
      chunks.push(trackIds.slice(i, i + 50));
    }

    // Fetch chunks with limited concurrency to leave connections free for audio
    const results: Track[][] = [];
    for (let i = 0; i < chunks.length; i += BATCH_CONCURRENCY) {
      const batch = chunks.slice(i, i + BATCH_CONCURRENCY);
      const batchResults = await Promise.all(
        batch.map(chunk => tracksApi.getBatch(chunk).catch((error) => {
          log.warn('Failed to fetch track batch:', error);
          return [] as Track[];
        }))
      );
      results.push(...batchResults);
    }

    // Build a map for O(1) lookup, then return in original ID order
    const trackMap = new Map<string, Track>();
    for (const batch of results) {
      for (const track of batch) {
        trackMap.set(track.id, track);
      }
    }

    return trackIds
      .map(id => trackMap.get(id))
      .filter((t): t is Track => t !== undefined);
  } catch (error) {
    log.error('Failed to fetch tracks:', error);
    return [];
  }
}

/**
 * Clear persisted player state for the current profile.
 */
export async function clearPlayerState(): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return;

  const profileId = await getSelectedProfileId();
  if (!profileId) {
    return;
  }

  try {
    await db.playerState.delete(profileId);
  } catch (error) {
    log.warn('Failed to clear player state:', error);
  }
}

/**
 * Migrate old player state from fixed ID to current profile.
 * Call this once on app startup to handle upgrade from v4 to v5.
 */
export async function migrateOldPlayerState(): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return;

  const profileId = await getSelectedProfileId();
  if (!profileId) {
    return;
  }

  try {
    // Check if old fixed-ID state exists
    const oldState = await db.playerState.get('player-state');
    if (oldState) {
      // Migrate to current profile if they don't already have state
      const existingState = await db.playerState.get(profileId);
      if (!existingState) {
        await db.playerState.put({
          ...oldState,
          id: profileId,
        });
      }
      // Delete old state
      await db.playerState.delete('player-state');
    }
  } catch (error) {
    log.warn('Failed to migrate old player state:', error);
  }
}

/**
 * Throttled save function to avoid too many writes.
 * Uses leading+trailing throttle: saves immediately if 500ms has elapsed
 * since the last save, and schedules a trailing save to capture final state.
 * This ensures state changes (shuffle, repeat, volume) persist even while
 * setCurrentTime fires every ~16ms during playback.
 */
let saveTimeout: ReturnType<typeof setTimeout> | null = null;
let lastSaveTime = 0;

export function debouncedSavePlayerState(state: {
  volume: number;
  shuffle: boolean;
  repeat: 'off' | 'all' | 'one';
  consume: boolean;
  queue: QueueItem[];
  queueIndex: number;
  currentTrack: Track | null;
  shuffleOrder: number[];
  shuffleIndex: number;
  currentTime: number;
}): void {
  const now = Date.now();

  if (saveTimeout) {
    clearTimeout(saveTimeout);
  }

  // If enough time has passed, save immediately
  if (now - lastSaveTime >= 500) {
    lastSaveTime = now;
    savePlayerState(state).catch(log.error);
    return;
  }

  // Otherwise schedule a trailing save
  saveTimeout = setTimeout(() => {
    lastSaveTime = Date.now();
    savePlayerState(state).catch(log.error);
    saveTimeout = null;
  }, 500);
}
