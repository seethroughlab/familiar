/**
 * Tests for libraryCache - caches library tracks in IndexedDB for offline browsing.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

/* eslint-disable @typescript-eslint/no-explicit-any */
const { mockCachedTracks } = vi.hoisted(() => ({
  mockCachedTracks: {
    get: vi.fn() as any,
    put: vi.fn(() => Promise.resolve()) as any,
    bulkPut: vi.fn(() => Promise.resolve()) as any,
    clear: vi.fn(() => Promise.resolve()) as any,
    toArray: vi.fn(() => Promise.resolve([])) as any,
    where: vi.fn() as any,
    count: vi.fn(() => Promise.resolve(0)) as any,
    orderBy: vi.fn() as any,
  },
}));

vi.mock('../../db', () => ({
  db: {
    cachedTracks: mockCachedTracks,
    offlineTracks: {
      toArray: vi.fn(() => Promise.resolve([])),
    },
    transaction: vi.fn(
      (_mode: string, _table: unknown, fn: () => Promise<void>) => fn()
    ),
  },
  isIndexedDBAvailable: vi.fn(() => Promise.resolve(true)),
}));

const mockApiGet = vi.fn();
vi.mock('../../api/base', () => ({
  default: {
    get: (...args: unknown[]) => mockApiGet(...args),
  },
}));

vi.mock('../../utils/logger', () => ({
  createLogger: () => ({
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  }),
}));

import {
  cacheLibrary,
  getCachedTracks,
  searchCachedTracks,
  getCachedTracksByArtist,
  getCachedTracksByAlbum,
  getCachedArtists,
  getCachedAlbums,
  hasCachedLibrary,
  getCacheInfo,
  isCacheStale,
  clearLibraryCache,
  getCachedTrack,
} from '../libraryCache';

// Sample tracks used across tests
const sampleTracks = [
  {
    id: 't1',
    title: 'Song One',
    artist: 'Artist A',
    album: 'Album X',
    albumArtist: null,
    genre: 'Rock',
    year: 2020,
    durationSeconds: 180,
    trackNumber: 1,
    discNumber: 1,
    cachedAt: new Date('2025-01-01'),
  },
  {
    id: 't2',
    title: 'Song Two',
    artist: 'Artist B',
    album: 'Album Y',
    albumArtist: 'Artist B',
    genre: 'Jazz',
    year: 2021,
    durationSeconds: 240,
    trackNumber: 2,
    discNumber: 1,
    cachedAt: new Date('2025-01-01'),
  },
  {
    id: 't3',
    title: 'Song Three',
    artist: 'Artist A',
    album: 'Album Z',
    albumArtist: null,
    genre: null,
    year: null,
    durationSeconds: null,
    trackNumber: null,
    discNumber: null,
    cachedAt: new Date('2025-01-01'),
  },
];

describe('libraryCache', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('cacheLibrary', () => {
    it('should fetch tracks from API and cache them in IndexedDB', async () => {
      const apiTracks = [
        {
          id: 't1',
          title: 'Song One',
          artist: 'Artist A',
          album: 'Album X',
          album_artist: null,
          genre: 'Rock',
          year: 2020,
          duration_seconds: 180,
          track_number: 1,
          disc_number: 1,
        },
      ];

      mockApiGet.mockResolvedValueOnce({ data: { items: apiTracks } });

      const result = await cacheLibrary();

      expect(result).toEqual({ cached: 1 });
      expect(mockCachedTracks.clear).toHaveBeenCalled();
      expect(mockCachedTracks.bulkPut).toHaveBeenCalledWith(
        expect.arrayContaining([
          expect.objectContaining({
            id: 't1',
            title: 'Song One',
            artist: 'Artist A',
            album: 'Album X',
          }),
        ])
      );
    });

    it('should throw when API request fails', async () => {
      mockApiGet.mockRejectedValueOnce(new Error('Request failed with status code 500'));

      await expect(cacheLibrary()).rejects.toThrow();
    });

    it('should throw when response format is invalid', async () => {
      mockApiGet.mockResolvedValueOnce({ data: { something: 'else' } });

      await expect(cacheLibrary()).rejects.toThrow('Invalid response format');
    });
  });

  describe('getCachedTracks', () => {
    it('should return all cached tracks from IndexedDB', async () => {
      mockCachedTracks.toArray.mockResolvedValueOnce(sampleTracks);

      const result = await getCachedTracks();

      expect(result).toEqual(sampleTracks);
      expect(mockCachedTracks.toArray).toHaveBeenCalled();
    });
  });

  describe('searchCachedTracks', () => {
    it('should filter tracks by query matching title, artist, album, or genre', async () => {
      mockCachedTracks.toArray.mockResolvedValueOnce(sampleTracks);

      const result = await searchCachedTracks('jazz');

      expect(result).toHaveLength(1);
      expect(result[0].id).toBe('t2');
    });

    it('should be case-insensitive', async () => {
      mockCachedTracks.toArray.mockResolvedValueOnce(sampleTracks);

      const result = await searchCachedTracks('ARTIST A');

      expect(result).toHaveLength(2);
    });

    it('should match against title', async () => {
      mockCachedTracks.toArray.mockResolvedValueOnce(sampleTracks);

      const result = await searchCachedTracks('Song Three');

      expect(result).toHaveLength(1);
      expect(result[0].id).toBe('t3');
    });
  });

  describe('getCachedTracksByArtist and getCachedTracksByAlbum', () => {
    it('should query by artist using where/equals', async () => {
      const mockChain = {
        equals: vi.fn().mockReturnThis(),
        toArray: vi.fn().mockResolvedValueOnce([sampleTracks[0]]),
      };
      mockCachedTracks.where.mockReturnValueOnce(mockChain);

      const result = await getCachedTracksByArtist('Artist A');

      expect(mockCachedTracks.where).toHaveBeenCalledWith('artist');
      expect(mockChain.equals).toHaveBeenCalledWith('Artist A');
      expect(result).toHaveLength(1);
    });

    it('should query by album using where/equals', async () => {
      const mockChain = {
        equals: vi.fn().mockReturnThis(),
        toArray: vi.fn().mockResolvedValueOnce([sampleTracks[1]]),
      };
      mockCachedTracks.where.mockReturnValueOnce(mockChain);

      const result = await getCachedTracksByAlbum('Album Y');

      expect(mockCachedTracks.where).toHaveBeenCalledWith('album');
      expect(mockChain.equals).toHaveBeenCalledWith('Album Y');
      expect(result).toHaveLength(1);
    });
  });

  describe('getCachedArtists', () => {
    it('should return unique sorted artist names', async () => {
      mockCachedTracks.toArray.mockResolvedValueOnce(sampleTracks);

      const result = await getCachedArtists();

      expect(result).toEqual(['Artist A', 'Artist B']);
    });
  });

  describe('getCachedAlbums', () => {
    it('should return unique albums sorted by name with artist info', async () => {
      mockCachedTracks.toArray.mockResolvedValueOnce(sampleTracks);

      const result = await getCachedAlbums();

      expect(result).toEqual([
        { album: 'Album X', artist: 'Artist A' },
        { album: 'Album Y', artist: 'Artist B' },
        { album: 'Album Z', artist: 'Artist A' },
      ]);
    });

    it('should prefer albumArtist over artist when available', async () => {
      const tracks = [
        {
          id: 't1',
          title: 'Track',
          artist: 'Feat Artist',
          album: 'Collab Album',
          albumArtist: 'Main Artist',
          genre: null,
          year: null,
          durationSeconds: null,
          trackNumber: null,
          discNumber: null,
          cachedAt: new Date(),
        },
      ];
      mockCachedTracks.toArray.mockResolvedValueOnce(tracks);

      const result = await getCachedAlbums();

      expect(result).toEqual([{ album: 'Collab Album', artist: 'Main Artist' }]);
    });
  });

  describe('hasCachedLibrary', () => {
    it('should return true when tracks exist in cache', async () => {
      mockCachedTracks.count.mockResolvedValueOnce(42);

      const result = await hasCachedLibrary();

      expect(result).toBe(true);
    });

    it('should return false when cache is empty', async () => {
      mockCachedTracks.count.mockResolvedValueOnce(0);

      const result = await hasCachedLibrary();

      expect(result).toBe(false);
    });
  });

  describe('getCacheInfo', () => {
    it('should return count and lastCached date', async () => {
      const cachedDate = new Date('2025-06-01');
      mockCachedTracks.count.mockResolvedValueOnce(10);
      mockCachedTracks.orderBy.mockReturnValueOnce({
        reverse: vi.fn().mockReturnThis(),
        first: vi.fn().mockResolvedValueOnce({ cachedAt: cachedDate }),
      });

      const result = await getCacheInfo();

      expect(result).toEqual({ count: 10, lastCached: cachedDate });
    });

    it('should return null lastCached when cache is empty', async () => {
      mockCachedTracks.count.mockResolvedValueOnce(0);

      const result = await getCacheInfo();

      expect(result).toEqual({ count: 0, lastCached: null });
    });
  });

  describe('isCacheStale', () => {
    it('should return true when cache is empty (no lastCached)', async () => {
      mockCachedTracks.count.mockResolvedValueOnce(0);

      const result = await isCacheStale();

      expect(result).toBe(true);
    });

    it('should return true when cache is older than maxAgeHours', async () => {
      const oldDate = new Date(Date.now() - 25 * 60 * 60 * 1000); // 25 hours ago
      mockCachedTracks.count.mockResolvedValueOnce(5);
      mockCachedTracks.orderBy.mockReturnValueOnce({
        reverse: vi.fn().mockReturnThis(),
        first: vi.fn().mockResolvedValueOnce({ cachedAt: oldDate }),
      });

      const result = await isCacheStale(24);

      expect(result).toBe(true);
    });

    it('should return false when cache is fresh', async () => {
      const recentDate = new Date(Date.now() - 1 * 60 * 60 * 1000); // 1 hour ago
      mockCachedTracks.count.mockResolvedValueOnce(5);
      mockCachedTracks.orderBy.mockReturnValueOnce({
        reverse: vi.fn().mockReturnThis(),
        first: vi.fn().mockResolvedValueOnce({ cachedAt: recentDate }),
      });

      const result = await isCacheStale(24);

      expect(result).toBe(false);
    });
  });

  describe('clearLibraryCache', () => {
    it('should clear all cached tracks', async () => {
      await clearLibraryCache();

      expect(mockCachedTracks.clear).toHaveBeenCalled();
    });
  });

  describe('getCachedTrack', () => {
    it('should return a single track by ID', async () => {
      mockCachedTracks.get.mockResolvedValueOnce(sampleTracks[0]);

      const result = await getCachedTrack('t1');

      expect(result).toEqual(sampleTracks[0]);
      expect(mockCachedTracks.get).toHaveBeenCalledWith('t1');
    });

    it('should return undefined when track not found', async () => {
      mockCachedTracks.get.mockResolvedValueOnce(undefined);

      const result = await getCachedTrack('nonexistent');

      expect(result).toBeUndefined();
    });
  });
});
