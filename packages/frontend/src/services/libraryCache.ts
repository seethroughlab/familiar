/**
 * Library cache service for offline browsing.
 */
import { db, isIndexedDBAvailable, type CachedTrack } from '../db';
import api from '../api/base';
import type { Track, TrackListResponse } from '../types';

/**
 * Cache the entire library from the API.
 */
export async function cacheLibrary(): Promise<{
  cached: number;
}> {
  // Fetch all tracks from API
  const { data } = await api.get('/tracks', { params: { limit: 10000 } });
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

export interface OfflineArtistSummary {
  name: string;
  track_count: number;
  album_count: number;
  first_track_id: string;
  first_album: string | null;
}

export interface OfflineArtistListResponse {
  items: OfflineArtistSummary[];
  total: number;
  page: number;
  page_size: number;
}

/**
 * Build artist summaries from downloaded tracks only.
 * Uses cached track metadata joined against offline track IDs.
 */
export async function getDownloadedArtistsPage(params: {
  search?: string;
  sort_by?: 'name' | 'track_count' | 'album_count';
  page?: number;
  page_size?: number;
}): Promise<OfflineArtistListResponse> {
  const available = await isIndexedDBAvailable();
  if (!available) {
    return {
      items: [],
      total: 0,
      page: params.page ?? 1,
      page_size: params.page_size ?? 50,
    };
  }

  const page = params.page ?? 1;
  const pageSize = params.page_size ?? 50;
  const sortBy = params.sort_by ?? 'name';
  const search = params.search?.trim().toLowerCase();

  const offlineTracks = await db.offlineTracks.toArray();
  const offlineIds = offlineTracks.map((t) => t.id);
  if (offlineIds.length === 0) {
    return { items: [], total: 0, page, page_size: pageSize };
  }

  const cachedTracks = await db.cachedTracks.where('id').anyOf(offlineIds).toArray();

  const byArtist = new Map<
    string,
    {
      trackIds: Set<string>;
      albums: Set<string>;
      firstTrackId: string;
      firstAlbum: string | null;
    }
  >();

  for (const track of cachedTracks) {
    const artistName = track.artist?.trim();
    if (!artistName) continue;
    if (search && !artistName.toLowerCase().includes(search)) continue;

    const existing = byArtist.get(artistName);
    if (!existing) {
      byArtist.set(artistName, {
        trackIds: new Set([track.id]),
        albums: new Set(track.album ? [track.album] : []),
        firstTrackId: track.id,
        firstAlbum: track.album || null,
      });
      continue;
    }

    existing.trackIds.add(track.id);
    if (track.album) existing.albums.add(track.album);
  }

  const artists: OfflineArtistSummary[] = Array.from(byArtist.entries()).map(([name, data]) => ({
    name,
    track_count: data.trackIds.size,
    album_count: data.albums.size,
    first_track_id: data.firstTrackId,
    first_album: data.firstAlbum,
  }));

  artists.sort((a, b) => {
    if (sortBy === 'track_count') return b.track_count - a.track_count || a.name.localeCompare(b.name);
    if (sortBy === 'album_count') return b.album_count - a.album_count || a.name.localeCompare(b.name);
    return a.name.localeCompare(b.name);
  });

  const total = artists.length;
  const start = (page - 1) * pageSize;
  const items = artists.slice(start, start + pageSize);

  return { items, total, page, page_size: pageSize };
}

/**
 * Build track list response from downloaded tracks only.
 */
export async function getDownloadedTracksPage(params?: {
  page?: number;
  page_size?: number;
  search?: string;
  artist?: string;
  album?: string;
  genre?: string;
  year_from?: number;
  year_to?: number;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
}): Promise<TrackListResponse> {
  const available = await isIndexedDBAvailable();
  const page = params?.page ?? 1;
  const pageSize = params?.page_size ?? 50;
  if (!available) {
    return { items: [], total: 0, page, page_size: pageSize };
  }

  const offlineTracks = await db.offlineTracks.toArray();
  const offlineIds = offlineTracks.map((t) => t.id);
  if (offlineIds.length === 0) {
    return { items: [], total: 0, page, page_size: pageSize };
  }

  const cachedTracks = await db.cachedTracks.where('id').anyOf(offlineIds).toArray();
  const q = params?.search?.trim().toLowerCase();

  let items = cachedTracks.filter((track) => {
    if (params?.artist && track.artist !== params.artist) return false;
    if (params?.album && track.album !== params.album) return false;
    if (params?.genre && track.genre !== params.genre) return false;
    if (params?.year_from !== undefined && (track.year ?? -Infinity) < params.year_from) return false;
    if (params?.year_to !== undefined && (track.year ?? Infinity) > params.year_to) return false;
    if (q) {
      const haystack = `${track.title} ${track.artist} ${track.album} ${track.genre ?? ''}`.toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  });

  const sortBy = params?.sort_by ?? 'artist';
  const sortOrder = params?.sort_order ?? 'asc';
  items.sort((a, b) => {
    const dir = sortOrder === 'desc' ? -1 : 1;
    const sval = (v: string | null | undefined) => (v ?? '').toLowerCase();
    const nval = (v: number | null | undefined) => v ?? -Infinity;

    if (sortBy === 'year') return (nval(a.year) - nval(b.year)) * dir;
    if (sortBy === 'duration_seconds') return (nval(a.durationSeconds) - nval(b.durationSeconds)) * dir;
    if (sortBy === 'album') return sval(a.album).localeCompare(sval(b.album)) * dir;
    if (sortBy === 'title') return sval(a.title).localeCompare(sval(b.title)) * dir;
    return sval(a.artist).localeCompare(sval(b.artist)) * dir;
  });

  const total = items.length;
  items = items.slice((page - 1) * pageSize, page * pageSize);

  return {
    items: items.map((t): Track => ({
      id: t.id,
      file_path: '',
      title: t.title || null,
      artist: t.artist || null,
      album: t.album || null,
      album_artist: t.albumArtist || null,
      album_type: 'album',
      track_number: t.trackNumber ?? null,
      disc_number: t.discNumber ?? null,
      year: t.year ?? null,
      genre: t.genre ?? null,
      duration_seconds: t.durationSeconds ?? null,
      format: null,
      analysis_version: 0,
    })),
    total,
    page,
    page_size: pageSize,
  };
}

export interface OfflineAlbumSummary {
  name: string;
  artist: string;
  year: number | null;
  track_count: number;
  first_track_id: string;
}

export interface OfflineAlbumListResponse {
  items: OfflineAlbumSummary[];
  total: number;
  page: number;
  page_size: number;
}

/**
 * Build album summaries from downloaded tracks only.
 */
export async function getDownloadedAlbumsPage(params: {
  search?: string;
  artist?: string;
  sort_by?: 'name' | 'artist' | 'year' | 'track_count';
  page?: number;
  page_size?: number;
}): Promise<OfflineAlbumListResponse> {
  const page = params.page ?? 1;
  const pageSize = params.page_size ?? 50;
  const tracks = await getDownloadedTracksPage({
    page: 1,
    page_size: 100000,
    search: params.search,
    artist: params.artist,
  });

  const byAlbum = new Map<string, OfflineAlbumSummary>();
  for (const t of tracks.items) {
    const album = t.album?.trim();
    const artist = t.artist?.trim();
    if (!album || !artist) continue;
    const key = `${artist}::${album}`;
    const existing = byAlbum.get(key);
    if (!existing) {
      byAlbum.set(key, {
        name: album,
        artist,
        year: t.year ?? null,
        track_count: 1,
        first_track_id: t.id,
      });
    } else {
      existing.track_count += 1;
      if (existing.year == null && t.year != null) existing.year = t.year;
    }
  }

  const sortBy = params.sort_by ?? 'name';
  const items = Array.from(byAlbum.values());
  items.sort((a, b) => {
    if (sortBy === 'track_count') return b.track_count - a.track_count || a.name.localeCompare(b.name);
    if (sortBy === 'year') return (b.year ?? -Infinity) - (a.year ?? -Infinity) || a.name.localeCompare(b.name);
    if (sortBy === 'artist') return a.artist.localeCompare(b.artist) || a.name.localeCompare(b.name);
    return a.name.localeCompare(b.name);
  });

  const total = items.length;
  return {
    items: items.slice((page - 1) * pageSize, page * pageSize),
    total,
    page,
    page_size: pageSize,
  };
}

export interface OfflineArtistDetail {
  name: string;
  track_count: number;
  album_count: number;
  total_duration_seconds: number;
  bio_summary: string | null;
  bio_content: string | null;
  image_url: string | null;
  lastfm_url: string | null;
  listeners: number | null;
  playcount: number | null;
  tags: string[];
  similar_artists: Array<{
    name: string;
    match_score: number;
    in_library: boolean;
    track_count: number | null;
    image_url: string | null;
    lastfm_url: string | null;
    bandcamp_url: string | null;
  }>;
  albums: Array<{
    name: string;
    year: number | null;
    track_count: number;
    first_track_id: string;
  }>;
  tracks: Array<{
    id: string;
    title: string | null;
    album: string | null;
    track_number: number | null;
    duration_seconds: number | null;
    year: number | null;
  }>;
  first_track_id: string;
  lastfm_fetched: boolean;
  lastfm_error: string | null;
}

export async function getDownloadedArtistDetail(artistName: string): Promise<OfflineArtistDetail | null> {
  const tracks = await getDownloadedTracksPage({ page: 1, page_size: 100000, artist: artistName });
  if (tracks.total === 0) return null;

  const albumsMap = new Map<string, { name: string; year: number | null; track_count: number; first_track_id: string }>();
  let totalDuration = 0;
  for (const t of tracks.items) {
    if (t.duration_seconds) totalDuration += t.duration_seconds;
    const albumName = t.album || 'Unknown Album';
    const existing = albumsMap.get(albumName);
    if (!existing) {
      albumsMap.set(albumName, {
        name: albumName,
        year: t.year ?? null,
        track_count: 1,
        first_track_id: t.id,
      });
    } else {
      existing.track_count += 1;
    }
  }

  return {
    name: artistName,
    track_count: tracks.total,
    album_count: albumsMap.size,
    total_duration_seconds: totalDuration,
    bio_summary: null,
    bio_content: null,
    image_url: null,
    lastfm_url: null,
    listeners: null,
    playcount: null,
    tags: [],
    similar_artists: [],
    albums: Array.from(albumsMap.values()),
    tracks: tracks.items.map((t) => ({
      id: t.id,
      title: t.title ?? null,
      album: t.album ?? null,
      track_number: t.track_number ?? null,
      duration_seconds: t.duration_seconds ?? null,
      year: t.year ?? null,
    })),
    first_track_id: tracks.items[0].id,
    lastfm_fetched: false,
    lastfm_error: null,
  };
}

export interface OfflineAlbumDetail {
  name: string;
  artist: string;
  album_artist: string | null;
  year: number | null;
  genre: string | null;
  track_count: number;
  total_duration_seconds: number;
  first_track_id: string;
  tracks: Array<{
    id: string;
    title: string | null;
    track_number: number | null;
    disc_number: number | null;
    duration_seconds: number | null;
  }>;
  similar_albums: Array<{
    name: string;
    artist: string;
    year: number | null;
    track_count: number;
    first_track_id: string;
    similarity_score: number;
  }>;
  discover_albums: Array<{
    name: string;
    artist: string;
    image_url: string | null;
    lastfm_url: string | null;
    bandcamp_url: string | null;
  }>;
  other_albums_by_artist: Array<{
    name: string;
    artist: string;
    year: number | null;
    track_count: number;
    first_track_id: string;
    similarity_score: number;
  }>;
}

export async function getDownloadedAlbumDetail(artistName: string, albumName: string): Promise<OfflineAlbumDetail | null> {
  const tracks = await getDownloadedTracksPage({
    page: 1,
    page_size: 100000,
    artist: artistName,
    album: albumName,
  });
  if (tracks.total === 0) return null;

  const totalDuration = tracks.items.reduce((sum, t) => sum + (t.duration_seconds ?? 0), 0);
  const year = tracks.items.find((t) => t.year != null)?.year ?? null;
  const genre = tracks.items.find((t) => t.genre != null)?.genre ?? null;
  const albumArtist = tracks.items.find((t) => t.album_artist != null)?.album_artist ?? null;

  return {
    name: albumName,
    artist: artistName,
    album_artist: albumArtist,
    year,
    genre,
    track_count: tracks.total,
    total_duration_seconds: totalDuration,
    first_track_id: tracks.items[0].id,
    tracks: tracks.items.map((t) => ({
      id: t.id,
      title: t.title ?? null,
      track_number: t.track_number ?? null,
      disc_number: t.disc_number ?? null,
      duration_seconds: t.duration_seconds ?? null,
    })),
    similar_albums: [],
    discover_albums: [],
    other_albums_by_artist: [],
  };
}
