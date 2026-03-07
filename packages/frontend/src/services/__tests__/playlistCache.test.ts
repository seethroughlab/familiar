/**
 * Tests for playlistCache - offline caching for playlists, smart playlists, favorites, and track resolution.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock db tables
const mockPlaylistsGet = vi.fn();
const mockPlaylistsPut = vi.fn();
const mockPlaylistsDelete = vi.fn();
const mockPlaylistsClear = vi.fn();
const mockPlaylistsCount = vi.fn();
const mockPlaylistsToArray = vi.fn();
const mockPlaylistsOrderBy = vi.fn();

const mockSmartPlaylistsGet = vi.fn();
const mockSmartPlaylistsPut = vi.fn();
const mockSmartPlaylistsDelete = vi.fn();
const mockSmartPlaylistsClear = vi.fn();
const mockSmartPlaylistsCount = vi.fn();
const mockSmartPlaylistsToArray = vi.fn();
const mockSmartPlaylistsOrderBy = vi.fn();

const mockFavoritesGet = vi.fn();
const mockFavoritesPut = vi.fn();
const mockFavoritesDelete = vi.fn();
const mockFavoritesClear = vi.fn();
const mockFavoritesCount = vi.fn();
const mockFavoritesOrderBy = vi.fn();

const mockCachedTracksWhere = vi.fn();

vi.mock('../../db', () => ({
  db: {
    cachedPlaylists: {
      get: (...args: unknown[]) => mockPlaylistsGet(...args),
      put: (...args: unknown[]) => mockPlaylistsPut(...args),
      delete: (...args: unknown[]) => mockPlaylistsDelete(...args),
      clear: () => mockPlaylistsClear(),
      count: () => mockPlaylistsCount(),
      toArray: () => mockPlaylistsToArray(),
      orderBy: (...args: unknown[]) => mockPlaylistsOrderBy(...args),
    },
    cachedSmartPlaylists: {
      get: (...args: unknown[]) => mockSmartPlaylistsGet(...args),
      put: (...args: unknown[]) => mockSmartPlaylistsPut(...args),
      delete: (...args: unknown[]) => mockSmartPlaylistsDelete(...args),
      clear: () => mockSmartPlaylistsClear(),
      count: () => mockSmartPlaylistsCount(),
      toArray: () => mockSmartPlaylistsToArray(),
      orderBy: (...args: unknown[]) => mockSmartPlaylistsOrderBy(...args),
    },
    cachedFavorites: {
      get: (...args: unknown[]) => mockFavoritesGet(...args),
      put: (...args: unknown[]) => mockFavoritesPut(...args),
      delete: (...args: unknown[]) => mockFavoritesDelete(...args),
      clear: () => mockFavoritesClear(),
      count: () => mockFavoritesCount(),
      orderBy: (...args: unknown[]) => mockFavoritesOrderBy(...args),
    },
    cachedTracks: {
      where: (...args: unknown[]) => mockCachedTracksWhere(...args),
    },
  },
  isIndexedDBAvailable: vi.fn(() => Promise.resolve(true)),
}));

vi.mock('../../utils/logger', () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
}));

const getModule = async () => await import('../playlistCache');
const getDbModule = async () => await import('../../db');

describe('playlistCache', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPlaylistsPut.mockResolvedValue(undefined);
    mockPlaylistsGet.mockResolvedValue(undefined);
    mockPlaylistsDelete.mockResolvedValue(undefined);
    mockPlaylistsClear.mockResolvedValue(undefined);
    mockPlaylistsCount.mockResolvedValue(0);
    mockPlaylistsToArray.mockResolvedValue([]);
    mockSmartPlaylistsPut.mockResolvedValue(undefined);
    mockSmartPlaylistsGet.mockResolvedValue(undefined);
    mockSmartPlaylistsDelete.mockResolvedValue(undefined);
    mockSmartPlaylistsClear.mockResolvedValue(undefined);
    mockSmartPlaylistsCount.mockResolvedValue(0);
    mockSmartPlaylistsToArray.mockResolvedValue([]);
    mockFavoritesPut.mockResolvedValue(undefined);
    mockFavoritesGet.mockResolvedValue(undefined);
    mockFavoritesDelete.mockResolvedValue(undefined);
    mockFavoritesClear.mockResolvedValue(undefined);
    mockFavoritesCount.mockResolvedValue(0);
  });

  // ========== Regular Playlists ==========
  describe('cachePlaylist', () => {
    it('should cache a playlist with track IDs extracted from tracks', async () => {
      const playlistDetail = {
        id: 'playlist-1',
        name: 'My Playlist',
        description: 'A test playlist',
        is_auto_generated: false,
        generation_prompt: null,
        tracks: [
          { id: 'track-1', playlist_track_id: 'pt-1', type: 'local' as const, title: 'Song 1', artist: 'Artist 1', album: null, duration_seconds: 180, position: 0 },
          { id: 'track-2', playlist_track_id: 'pt-2', type: 'local' as const, title: 'Song 2', artist: 'Artist 2', album: null, duration_seconds: 200, position: 1 },
        ],
        auto_download: false,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      };

      const { cachePlaylist } = await getModule();
      await cachePlaylist(playlistDetail);

      expect(mockPlaylistsPut).toHaveBeenCalledWith(
        expect.objectContaining({
          id: 'playlist-1',
          name: 'My Playlist',
          track_ids: ['track-1', 'track-2'],
          track_count: 2,
          cachedAt: expect.any(Date),
        })
      );
    });

    it('should skip when IndexedDB is unavailable', async () => {
      const dbModule = await getDbModule();
      vi.mocked(dbModule.isIndexedDBAvailable).mockResolvedValueOnce(false);

      const { cachePlaylist } = await getModule();
      await cachePlaylist({
        id: 'p1', name: 'P', description: null, is_auto_generated: false,
        generation_prompt: null, tracks: [],
        auto_download: false, created_at: '', updated_at: '',
      });

      expect(mockPlaylistsPut).not.toHaveBeenCalled();
    });
  });

  describe('getCachedPlaylist', () => {
    it('should return cached playlist by ID', async () => {
      const cached = { id: 'playlist-1', name: 'Test', cachedAt: new Date() };
      mockPlaylistsGet.mockResolvedValueOnce(cached);

      const { getCachedPlaylist } = await getModule();
      const result = await getCachedPlaylist('playlist-1');

      expect(result).toEqual(cached);
    });

    it('should return undefined when IndexedDB is unavailable', async () => {
      const dbModule = await getDbModule();
      vi.mocked(dbModule.isIndexedDBAvailable).mockResolvedValueOnce(false);

      const { getCachedPlaylist } = await getModule();
      const result = await getCachedPlaylist('playlist-1');

      expect(result).toBeUndefined();
    });
  });

  describe('getCachedPlaylists', () => {
    it('should return all cached playlists', async () => {
      mockPlaylistsToArray.mockResolvedValueOnce([
        { id: 'p1', name: 'Playlist 1' },
        { id: 'p2', name: 'Playlist 2' },
      ]);

      const { getCachedPlaylists } = await getModule();
      const result = await getCachedPlaylists();

      expect(result).toHaveLength(2);
    });
  });

  describe('deleteCachedPlaylist', () => {
    it('should delete cached playlist by ID', async () => {
      const { deleteCachedPlaylist } = await getModule();
      await deleteCachedPlaylist('playlist-1');

      expect(mockPlaylistsDelete).toHaveBeenCalledWith('playlist-1');
    });
  });

  // ========== Smart Playlists ==========
  describe('cacheSmartPlaylist', () => {
    it('should cache a smart playlist with track IDs', async () => {
      const smartPlaylist = {
        id: 'smart-1',
        name: 'Recent Favorites',
        description: 'Recently favorited',
        rules: [{ field: 'is_favorite', operator: 'equals', value: true }],
        match_mode: 'all' as const,
        order_by: 'favorited_at',
        order_direction: 'desc' as const,
        max_tracks: 50,
        cached_track_count: 2,
        last_refreshed_at: '2024-01-01T00:00:00Z',
        auto_download: false,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      };

      const { cacheSmartPlaylist } = await getModule();
      await cacheSmartPlaylist(smartPlaylist, ['track-1', 'track-2']);

      expect(mockSmartPlaylistsPut).toHaveBeenCalledWith(
        expect.objectContaining({
          id: 'smart-1',
          name: 'Recent Favorites',
          track_ids: ['track-1', 'track-2'],
          cached_track_count: 2,
        })
      );
    });
  });

  describe('getCachedSmartPlaylist', () => {
    it('should return cached smart playlist by ID', async () => {
      const cached = { id: 'smart-1', name: 'Smart', cachedAt: new Date() };
      mockSmartPlaylistsGet.mockResolvedValueOnce(cached);

      const { getCachedSmartPlaylist } = await getModule();
      const result = await getCachedSmartPlaylist('smart-1');

      expect(result).toEqual(cached);
    });
  });

  // ========== Favorites ==========
  describe('cacheFavorites', () => {
    it('should cache favorites for a profile', async () => {
      const { cacheFavorites } = await getModule();
      await cacheFavorites('profile-123', ['track-1', 'track-2', 'track-3']);

      expect(mockFavoritesPut).toHaveBeenCalledWith(
        expect.objectContaining({
          profileId: 'profile-123',
          trackIds: ['track-1', 'track-2', 'track-3'],
          cachedAt: expect.any(Date),
        })
      );
    });
  });

  describe('getCachedFavorites', () => {
    it('should return cached favorites for a profile', async () => {
      const cached = { profileId: 'profile-123', trackIds: ['track-1'], cachedAt: new Date() };
      mockFavoritesGet.mockResolvedValueOnce(cached);

      const { getCachedFavorites } = await getModule();
      const result = await getCachedFavorites('profile-123');

      expect(result?.trackIds).toEqual(['track-1']);
    });

    it('should return undefined when IndexedDB is unavailable', async () => {
      const dbModule = await getDbModule();
      vi.mocked(dbModule.isIndexedDBAvailable).mockResolvedValueOnce(false);

      const { getCachedFavorites } = await getModule();
      const result = await getCachedFavorites('profile-123');

      expect(result).toBeUndefined();
    });
  });

  // ========== Track Resolution ==========
  describe('resolveTrackIds', () => {
    it('should resolve track IDs to cached track metadata in order', async () => {
      const tracks = [
        { id: 'track-2', title: 'Song 2', artist: 'Artist 2', album: 'Album 2', albumArtist: null, genre: null, year: null, durationSeconds: 200, trackNumber: null, discNumber: null, cachedAt: new Date() },
        { id: 'track-1', title: 'Song 1', artist: 'Artist 1', album: 'Album 1', albumArtist: null, genre: null, year: null, durationSeconds: 180, trackNumber: null, discNumber: null, cachedAt: new Date() },
      ];
      const mockAnyOf = vi.fn().mockReturnValue({ toArray: vi.fn().mockResolvedValue(tracks) });
      mockCachedTracksWhere.mockReturnValue({ anyOf: mockAnyOf });

      const { resolveTrackIds } = await getModule();
      const result = await resolveTrackIds(['track-1', 'track-2']);

      // Should return in the order of input IDs
      expect(result[0].id).toBe('track-1');
      expect(result[1].id).toBe('track-2');
    });

    it('should filter out tracks not found in cache', async () => {
      const tracks = [
        { id: 'track-1', title: 'Song 1', artist: 'Artist 1', album: 'Album 1', albumArtist: null, genre: null, year: null, durationSeconds: 180, trackNumber: null, discNumber: null, cachedAt: new Date() },
      ];
      const mockAnyOf = vi.fn().mockReturnValue({ toArray: vi.fn().mockResolvedValue(tracks) });
      mockCachedTracksWhere.mockReturnValue({ anyOf: mockAnyOf });

      const { resolveTrackIds } = await getModule();
      const result = await resolveTrackIds(['track-1', 'track-missing']);

      expect(result).toHaveLength(1);
      expect(result[0].id).toBe('track-1');
    });

    it('should return empty array when IndexedDB is unavailable', async () => {
      const dbModule = await getDbModule();
      vi.mocked(dbModule.isIndexedDBAvailable).mockResolvedValueOnce(false);

      const { resolveTrackIds } = await getModule();
      const result = await resolveTrackIds(['track-1']);

      expect(result).toEqual([]);
    });
  });

  describe('getAvailableTrackIds', () => {
    it('should return set of cached track IDs', async () => {
      const tracks = [
        { id: 'track-1' },
        { id: 'track-3' },
      ];
      const mockAnyOf = vi.fn().mockReturnValue({ toArray: vi.fn().mockResolvedValue(tracks) });
      mockCachedTracksWhere.mockReturnValue({ anyOf: mockAnyOf });

      const { getAvailableTrackIds } = await getModule();
      const result = await getAvailableTrackIds(['track-1', 'track-2', 'track-3']);

      expect(result.size).toBe(2);
      expect(result.has('track-1')).toBe(true);
      expect(result.has('track-2')).toBe(false);
      expect(result.has('track-3')).toBe(true);
    });
  });

  // ========== Combined Cache Operations ==========
  describe('clearAllPlaylistCaches', () => {
    it('should clear playlists, smart playlists, and favorites caches', async () => {
      mockPlaylistsClear.mockResolvedValue(undefined);
      mockSmartPlaylistsClear.mockResolvedValue(undefined);
      mockFavoritesClear.mockResolvedValue(undefined);

      const { clearAllPlaylistCaches } = await getModule();
      await clearAllPlaylistCaches();

      expect(mockPlaylistsClear).toHaveBeenCalled();
      expect(mockSmartPlaylistsClear).toHaveBeenCalled();
      expect(mockFavoritesClear).toHaveBeenCalled();
    });
  });

  describe('getPlaylistCacheInfo', () => {
    it('should return count and last cached date', async () => {
      const cachedDate = new Date('2024-06-15T12:00:00Z');
      mockPlaylistsCount.mockResolvedValueOnce(3);
      mockPlaylistsOrderBy.mockReturnValueOnce({
        reverse: () => ({
          first: () => Promise.resolve({ cachedAt: cachedDate }),
        }),
      });

      const { getPlaylistCacheInfo } = await getModule();
      const result = await getPlaylistCacheInfo();

      expect(result.count).toBe(3);
      expect(result.lastCached).toEqual(cachedDate);
    });

    it('should return zero count and null date when empty', async () => {
      mockPlaylistsCount.mockResolvedValueOnce(0);

      const { getPlaylistCacheInfo } = await getModule();
      const result = await getPlaylistCacheInfo();

      expect(result.count).toBe(0);
      expect(result.lastCached).toBeNull();
    });

    it('should return defaults when IndexedDB is unavailable', async () => {
      const dbModule = await getDbModule();
      vi.mocked(dbModule.isIndexedDBAvailable).mockResolvedValueOnce(false);

      const { getPlaylistCacheInfo } = await getModule();
      const result = await getPlaylistCacheInfo();

      expect(result).toEqual({ count: 0, lastCached: null });
    });
  });
});
