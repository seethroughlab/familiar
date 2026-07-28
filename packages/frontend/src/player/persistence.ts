/**
 * Player state persistence service.
 * Saves and loads player state from IndexedDB per profile.
 * All operations silently fail if IndexedDB isn't available (iOS private browsing).
 */
import {
  db,
  isIndexedDBAvailable,
  type PersistedPlayerState,
  type PersistedQueueSource,
} from '../db';
import { getSelectedProfileId } from '../services/profileService';
import type { Track, QueueItem } from '../types';
import { tracksApi } from '../api';
import { createLogger } from '../utils/logger';

const log = createLogger('PlayerPersistence');

/** The shape both `savePlayerState` and its throttled wrapper accept. */
export interface PersistablePlayerState {
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
  queueSource?: PersistedQueueSource | null;
  lazyQueueIds?: string[] | null;
  lazyQueueIndex?: number;
  logicalTrackIds?: string[] | null;
  logicalIndex?: number;
}

/**
 * Keys for the two large ID lists that hang off a profile's player state, each stored as
 * its own row in the same table.
 *
 * Both are large and rarely changing. The reservoir for a full library is ~26k UUIDs
 * (~1 MB) and only changes on `setLazyQueue`, `toggleShuffle` and a refill; the logical
 * queue changes only when connectivity flips. Meanwhile `setCurrentTime` persists on every
 * tick, throttled to 500ms — so keeping either in the main record would rewrite that bulk
 * twice a second for the whole of playback. The clone cost is negligible (~0.9ms measured),
 * but the sustained ~2 MB/s of flash writes is not, particularly on iOS.
 *
 * `playerState` is keyed on `id` alone, so extra rows cost no schema change.
 */
const reservoirKey = (profileId: string) => `${profileId}::reservoir`;
const logicalQueueKey = (profileId: string) => `${profileId}::logical`;

interface ReservoirRecord {
  id: string;
  lazyQueueIds: string[] | null;
  lazyQueueIndex: number;
  updatedAt: Date;
}

interface LogicalQueueRecord {
  id: string;
  logicalTrackIds: string[] | null;
  logicalIndex: number;
  updatedAt: Date;
}

// Last list written per row key, so unchanged ones can be skipped. Compared by reference:
// the store replaces these arrays wholesale whenever they change.
const lastWrittenSideList = new Map<string, string[] | null>();

/**
 * Write one of the side rows, skipping the write when the list has not been replaced.
 *
 * `buildRow` keeps each row's field names as they are on disk rather than normalising them,
 * so records written before this helper existed still load.
 */
async function saveSideList(
  key: string,
  ids: string[] | null,
  buildRow: (ids: string[]) => Record<string, unknown>
): Promise<void> {
  if (lastWrittenSideList.get(key) === ids) return;
  lastWrittenSideList.set(key, ids);

  if (!ids || ids.length === 0) {
    await db.playerState.delete(key);
    return;
  }
  await db.playerState.put({
    id: key,
    ...buildRow(ids),
    updatedAt: new Date(),
  } as unknown as PersistedPlayerState);
}

async function saveReservoir(
  profileId: string,
  ids: string[] | null,
  index: number
): Promise<void> {
  await saveSideList(reservoirKey(profileId), ids, (list) => ({
    lazyQueueIds: list,
    lazyQueueIndex: index,
  }));
}

async function saveLogicalQueue(
  profileId: string,
  ids: string[] | null,
  index: number
): Promise<void> {
  await saveSideList(logicalQueueKey(profileId), ids, (list) => ({
    logicalTrackIds: list,
    logicalIndex: index,
  }));
}

async function loadReservoir(profileId: string): Promise<ReservoirRecord | null> {
  const row = await db.playerState.get(reservoirKey(profileId));
  return (row as unknown as ReservoirRecord) ?? null;
}

async function loadLogicalQueue(profileId: string): Promise<LogicalQueueRecord | null> {
  const row = await db.playerState.get(logicalQueueKey(profileId));
  return (row as unknown as LogicalQueueRecord) ?? null;
}

/**
 * Save player state to IndexedDB for the current profile.
 */
export async function savePlayerState(state: PersistablePlayerState): Promise<void> {
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
      queueSource: state.queueSource ?? null,
      // The reservoir and logical-queue lists live in their own rows; the cursors into
      // them are small and change with the queue, so they stay here.
      lazyQueueIndex: state.lazyQueueIndex ?? -1,
      logicalIndex: state.logicalIndex ?? -1,
      updatedAt: new Date(),
    };

    await db.playerState.put(persistedState);
    await saveReservoir(profileId, state.lazyQueueIds ?? null, state.lazyQueueIndex ?? -1);
    await saveLogicalQueue(profileId, state.logicalTrackIds ?? null, state.logicalIndex ?? -1);
  } catch (error) {
    log.warn('Failed to save player state:', error);
  }
}

async function readPlayerState(profileId: string): Promise<PersistedPlayerState | null> {
  const state = await db.playerState.get(profileId);
  if (!state) return null;
  // In parallel: this is on the hydration path, and first paint waits on it.
  const [reservoir, logical] = await Promise.all([
    loadReservoir(profileId),
    loadLogicalQueue(profileId),
  ]);
  return {
    ...state,
    lazyQueueIds: reservoir?.lazyQueueIds ?? null,
    logicalTrackIds: logical?.logicalTrackIds ?? null,
  };
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
    return await readPlayerState(profileId);
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
    return await readPlayerState(profileId);
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
    // Every row, or a side list outlives the state that referenced it.
    const reservoir = reservoirKey(profileId);
    const logical = logicalQueueKey(profileId);
    await db.playerState.bulkDelete([profileId, reservoir, logical]);
    lastWrittenSideList.delete(reservoir);
    lastWrittenSideList.delete(logical);
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

export function debouncedSavePlayerState(state: PersistablePlayerState): void {
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
