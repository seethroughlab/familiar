/**
 * Playlist cache service for offline support.
 * Caches playlists, smart playlists, and favorites for offline access.
 * All operations silently fail if IndexedDB isn't available (iOS private browsing).
 */
import {
  db,
  isIndexedDBAvailable,
  type CachedPlaylist,
  type CachedSmartPlaylist,
  type CachedFavorites,
  type CachedTrack,
} from '../db';
import type { PlaylistDetail, SmartPlaylist } from '../api/client';
import { createLogger } from '../utils/logger';

const log = createLogger('PlaylistCache');

// =====================
// Regular Playlists
// =====================

/**
 * Cache a playlist with its track IDs.
 */
export async function cachePlaylist(playlist: PlaylistDetail): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return;

  try {
    const cached: CachedPlaylist = {
      id: playlist.id,
      name: playlist.name,
      description: playlist.description,
      is_auto_generated: playlist.is_auto_generated,
      generation_prompt: playlist.generation_prompt,
      track_ids: playlist.tracks.map((t) => t.id),
      track_count: playlist.tracks.length,
      cachedAt: new Date(),
    };

    await db.cachedPlaylists.put(cached);
  } catch (error) {
    log.warn('Failed to cache playlist:', error);
  }
}

/**
 * Get a cached playlist by ID.
 */
export async function getCachedPlaylist(
  id: string
): Promise<CachedPlaylist | undefined> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return undefined;

  try {
    return await db.cachedPlaylists.get(id);
  } catch (error) {
    log.warn('Failed to get cached playlist:', error);
    return undefined;
  }
}

/**
 * Get all cached playlists.
 */
export async function getCachedPlaylists(): Promise<CachedPlaylist[]> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return [];

  try {
    return await db.cachedPlaylists.toArray();
  } catch (error) {
    log.warn('Failed to get cached playlists:', error);
    return [];
  }
}

/**
 * Delete a cached playlist.
 */
export async function deleteCachedPlaylist(id: string): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return;

  try {
    await db.cachedPlaylists.delete(id);
  } catch (error) {
    log.warn('Failed to delete cached playlist:', error);
  }
}

/**
 * Clear all cached playlists.
 */
export async function clearPlaylistCache(): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return;

  try {
    await db.cachedPlaylists.clear();
  } catch (error) {
    log.warn('Failed to clear playlist cache:', error);
  }
}

/**
 * Get playlist cache info.
 */
export async function getPlaylistCacheInfo(): Promise<{
  count: number;
  lastCached: Date | null;
}> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return { count: 0, lastCached: null };

  try {
    const count = await db.cachedPlaylists.count();

    if (count === 0) {
      return { count: 0, lastCached: null };
    }

    const playlist = await db.cachedPlaylists.orderBy('cachedAt').reverse().first();

    return {
      count,
      lastCached: playlist?.cachedAt || null,
    };
  } catch (error) {
    log.warn('Failed to get playlist cache info:', error);
    return { count: 0, lastCached: null };
  }
}

// =====================
// Smart Playlists
// =====================

/**
 * Cache a smart playlist with its resolved track IDs.
 */
export async function cacheSmartPlaylist(
  playlist: SmartPlaylist,
  trackIds: string[]
): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return;

  try {
    const cached: CachedSmartPlaylist = {
      id: playlist.id,
      name: playlist.name,
      description: playlist.description,
      rules: playlist.rules,
      match_mode: playlist.match_mode,
      order_by: playlist.order_by,
      order_direction: playlist.order_direction,
      max_tracks: playlist.max_tracks,
      track_ids: trackIds,
      cached_track_count: trackIds.length,
      last_refreshed_at: playlist.last_refreshed_at,
      cachedAt: new Date(),
    };

    await db.cachedSmartPlaylists.put(cached);
  } catch (error) {
    log.warn('Failed to cache smart playlist:', error);
  }
}

/**
 * Get a cached smart playlist by ID.
 */
export async function getCachedSmartPlaylist(
  id: string
): Promise<CachedSmartPlaylist | undefined> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return undefined;

  try {
    return await db.cachedSmartPlaylists.get(id);
  } catch (error) {
    log.warn('Failed to get cached smart playlist:', error);
    return undefined;
  }
}

/**
 * Get all cached smart playlists.
 */
export async function getCachedSmartPlaylists(): Promise<CachedSmartPlaylist[]> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return [];

  try {
    return await db.cachedSmartPlaylists.toArray();
  } catch (error) {
    log.warn('Failed to get cached smart playlists:', error);
    return [];
  }
}

/**
 * Delete a cached smart playlist.
 */
export async function deleteCachedSmartPlaylist(id: string): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return;

  try {
    await db.cachedSmartPlaylists.delete(id);
  } catch (error) {
    log.warn('Failed to delete cached smart playlist:', error);
  }
}

/**
 * Clear all cached smart playlists.
 */
export async function clearSmartPlaylistCache(): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return;

  try {
    await db.cachedSmartPlaylists.clear();
  } catch (error) {
    log.warn('Failed to clear smart playlist cache:', error);
  }
}

/**
 * Get smart playlist cache info.
 */
export async function getSmartPlaylistCacheInfo(): Promise<{
  count: number;
  lastCached: Date | null;
}> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return { count: 0, lastCached: null };

  try {
    const count = await db.cachedSmartPlaylists.count();

    if (count === 0) {
      return { count: 0, lastCached: null };
    }

    const playlist = await db.cachedSmartPlaylists.orderBy('cachedAt').reverse().first();

    return {
      count,
      lastCached: playlist?.cachedAt || null,
    };
  } catch (error) {
    log.warn('Failed to get smart playlist cache info:', error);
    return { count: 0, lastCached: null };
  }
}

// =====================
// Favorites
// =====================

/**
 * Cache favorites for a profile.
 */
export async function cacheFavorites(
  profileId: string,
  trackIds: string[]
): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return;

  try {
    const cached: CachedFavorites = {
      profileId,
      trackIds,
      cachedAt: new Date(),
    };

    await db.cachedFavorites.put(cached);
  } catch (error) {
    log.warn('Failed to cache favorites:', error);
  }
}

/**
 * Get cached favorites for a profile.
 */
export async function getCachedFavorites(
  profileId: string
): Promise<CachedFavorites | undefined> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return undefined;

  try {
    return await db.cachedFavorites.get(profileId);
  } catch (error) {
    log.warn('Failed to get cached favorites:', error);
    return undefined;
  }
}

/**
 * Delete cached favorites for a profile.
 */
export async function deleteCachedFavorites(profileId: string): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return;

  try {
    await db.cachedFavorites.delete(profileId);
  } catch (error) {
    log.warn('Failed to delete cached favorites:', error);
  }
}

/**
 * Clear all cached favorites.
 */
export async function clearFavoritesCache(): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return;

  try {
    await db.cachedFavorites.clear();
  } catch (error) {
    log.warn('Failed to clear favorites cache:', error);
  }
}

/**
 * Get favorites cache info.
 */
export async function getFavoritesCacheInfo(): Promise<{
  count: number;
  lastCached: Date | null;
}> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return { count: 0, lastCached: null };

  try {
    const count = await db.cachedFavorites.count();

    if (count === 0) {
      return { count: 0, lastCached: null };
    }

    const favorites = await db.cachedFavorites.orderBy('cachedAt').reverse().first();

    return {
      count,
      lastCached: favorites?.cachedAt || null,
    };
  } catch (error) {
    log.warn('Failed to get favorites cache info:', error);
    return { count: 0, lastCached: null };
  }
}

// =====================
// Track Resolution
// =====================

/**
 * Resolve track IDs to cached track metadata.
 * Returns tracks in the same order as the input IDs.
 */
export async function resolveTrackIds(
  trackIds: string[]
): Promise<CachedTrack[]> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return [];

  try {
    const tracksMap = new Map<string, CachedTrack>();

    // Fetch all tracks at once
    const tracks = await db.cachedTracks.where('id').anyOf(trackIds).toArray();

    for (const track of tracks) {
      tracksMap.set(track.id, track);
    }

    // Return in original order, filtering out any not found
    return trackIds
      .map((id) => tracksMap.get(id))
      .filter((t): t is CachedTrack => t !== undefined);
  } catch (error) {
    log.warn('Failed to resolve track IDs:', error);
    return [];
  }
}

/**
 * Check which track IDs are cached.
 */
export async function getAvailableTrackIds(
  trackIds: string[]
): Promise<Set<string>> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return new Set();

  try {
    const tracks = await db.cachedTracks.where('id').anyOf(trackIds).toArray();
    return new Set(tracks.map((t) => t.id));
  } catch (error) {
    log.warn('Failed to get available track IDs:', error);
    return new Set();
  }
}

// =====================
// Combined Cache Stats
// =====================

/**
 * Get combined cache stats for all offline data types.
 */
export async function getAllCacheStats(): Promise<{
  playlists: { count: number; lastCached: Date | null };
  smartPlaylists: { count: number; lastCached: Date | null };
  favorites: { count: number; lastCached: Date | null };
}> {
  const [playlists, smartPlaylists, favorites] = await Promise.all([
    getPlaylistCacheInfo(),
    getSmartPlaylistCacheInfo(),
    getFavoritesCacheInfo(),
  ]);

  return { playlists, smartPlaylists, favorites };
}

/**
 * Clear all playlist-related caches.
 */
export async function clearAllPlaylistCaches(): Promise<void> {
  await Promise.all([
    clearPlaylistCache(),
    clearSmartPlaylistCache(),
    clearFavoritesCache(),
  ]);
}
