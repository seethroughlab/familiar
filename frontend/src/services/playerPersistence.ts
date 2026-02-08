/**
 * Player state persistence service.
 * Saves and loads player state from IndexedDB per profile.
 * All operations silently fail if IndexedDB isn't available (iOS private browsing).
 */
import { db, isIndexedDBAvailable, type PersistedPlayerState } from '../db';
import { getSelectedProfileId } from './profileService';
import type { Track, QueueItem } from '../types';
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
 * Fetch tracks by IDs from API.
 */
export async function fetchTracksByIds(trackIds: string[]): Promise<Track[]> {
  if (trackIds.length === 0) return [];

  try {
    // Fetch each track individually (could be optimized with a batch endpoint)
    const tracks: Track[] = [];
    for (const id of trackIds) {
      try {
        const response = await fetch(`/api/v1/tracks/${id}`);
        if (response.ok) {
          const track = await response.json();
          tracks.push(track);
        }
      } catch {
        // Skip tracks that can't be fetched
        log.warn(`Failed to fetch track ${id}`);
      }
    }
    return tracks;
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
 * Debounced save function to avoid too many writes.
 */
let saveTimeout: ReturnType<typeof setTimeout> | null = null;

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
  if (saveTimeout) {
    clearTimeout(saveTimeout);
  }

  saveTimeout = setTimeout(() => {
    savePlayerState(state).catch(log.error);
    saveTimeout = null;
  }, 500); // Debounce by 500ms
}
