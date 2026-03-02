/**
 * Library cache service for offline browsing.
 */
import { db, type CachedTrack } from '../db';
import { getApiUrl } from '../api/base';

/**
 * Cache the entire library from the API.
 */
export async function cacheLibrary(): Promise<{
  cached: number;
}> {
  // Fetch all tracks from API
  const response = await fetch(getApiUrl('/tracks?limit=10000'));
  if (!response.ok) {
    throw new Error(`Failed to fetch library: ${response.statusText}`);
  }

  const data = await response.json();
  const tracks = data.items || data.tracks || data;

  if (!Array.isArray(tracks)) {
    throw new Error('Invalid response format');
  }

  const now = new Date();
  const cachedTracks: CachedTrack[] = tracks.map((track: Record<string, unknown>) => ({
    id: track.id as string,
    title: (track.title as string) || '',
    artist: (track.artist as string) || '',
    album: (track.album as string) || '',
    albumArtist: (track.album_artist as string) || null,
    genre: (track.genre as string) || null,
    year: (track.year as number) || null,
    durationSeconds: (track.duration_seconds as number) || null,
    trackNumber: (track.track_number as number) || null,
    discNumber: (track.disc_number as number) || null,
    cachedAt: now,
  }));

  // Clear existing cache and add new tracks
  await db.transaction('rw', db.cachedTracks, async () => {
    await db.cachedTracks.clear();
    await db.cachedTracks.bulkPut(cachedTracks);
  });

  return { cached: cachedTracks.length };
}

/**
 * Get all cached tracks.
 */
export async function getCachedTracks(): Promise<CachedTrack[]> {
  return db.cachedTracks.toArray();
}

/**
 * Search cached tracks by query.
 */
export async function searchCachedTracks(query: string): Promise<CachedTrack[]> {
  const lowerQuery = query.toLowerCase();

  const tracks = await db.cachedTracks.toArray();

  return tracks.filter(
    (track) =>
      track.title.toLowerCase().includes(lowerQuery) ||
      track.artist.toLowerCase().includes(lowerQuery) ||
      track.album.toLowerCase().includes(lowerQuery) ||
      (track.genre && track.genre.toLowerCase().includes(lowerQuery))
  );
}

/**
 * Get cached tracks by artist.
 */
export async function getCachedTracksByArtist(artist: string): Promise<CachedTrack[]> {
  return db.cachedTracks.where('artist').equals(artist).toArray();
}

/**
 * Get cached tracks by album.
 */
export async function getCachedTracksByAlbum(album: string): Promise<CachedTrack[]> {
  return db.cachedTracks.where('album').equals(album).toArray();
}

/**
 * Get unique artists from cache.
 */
export async function getCachedArtists(): Promise<string[]> {
  const tracks = await db.cachedTracks.toArray();
  const artists = new Set(tracks.map((t) => t.artist).filter(Boolean));
  return Array.from(artists).sort();
}

/**
 * Get unique albums from cache.
 */
export async function getCachedAlbums(): Promise<
  Array<{ album: string; artist: string }>
> {
  const tracks = await db.cachedTracks.toArray();
  const albumMap = new Map<string, string>();

  for (const track of tracks) {
    if (track.album && !albumMap.has(track.album)) {
      albumMap.set(track.album, track.albumArtist || track.artist);
    }
  }

  return Array.from(albumMap.entries())
    .map(([album, artist]) => ({ album, artist }))
    .sort((a, b) => a.album.localeCompare(b.album));
}

/**
 * Check if library cache exists.
 */
export async function hasCachedLibrary(): Promise<boolean> {
  const count = await db.cachedTracks.count();
  return count > 0;
}

/**
 * Get cache info.
 */
export async function getCacheInfo(): Promise<{
  count: number;
  lastCached: Date | null;
}> {
  const count = await db.cachedTracks.count();

  if (count === 0) {
    return { count: 0, lastCached: null };
  }

  // Get the most recent cachedAt date
  const track = await db.cachedTracks.orderBy('cachedAt').reverse().first();

  return {
    count,
    lastCached: track?.cachedAt || null,
  };
}

/**
 * Check if cache is stale (older than specified hours).
 */
export async function isCacheStale(maxAgeHours: number = 24): Promise<boolean> {
  const info = await getCacheInfo();

  if (!info.lastCached) {
    return true; // No cache is considered stale
  }

  const ageMs = Date.now() - info.lastCached.getTime();
  const maxAgeMs = maxAgeHours * 60 * 60 * 1000;

  return ageMs > maxAgeMs;
}

/**
 * Clear the library cache.
 */
export async function clearLibraryCache(): Promise<void> {
  await db.cachedTracks.clear();
}

/**
 * Get a single cached track by ID.
 */
export async function getCachedTrack(
  trackId: string
): Promise<CachedTrack | undefined> {
  return db.cachedTracks.get(trackId);
}
