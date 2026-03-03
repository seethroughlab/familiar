/**
 * Tests for offlineService - manages track downloads and offline playback.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

/* eslint-disable @typescript-eslint/no-explicit-any */
const {
  mockOfflineTracks,
  mockOfflineArtwork,
  mockCachedTracks,
  mockPartialDownloads,
} = vi.hoisted(() => ({
  mockOfflineTracks: {
    get: vi.fn() as any,
    put: vi.fn(() => Promise.resolve()) as any,
    delete: vi.fn(() => Promise.resolve()) as any,
    toArray: vi.fn(() => Promise.resolve([] as any[])) as any,
    clear: vi.fn(() => Promise.resolve()) as any,
    where: vi.fn(() => ({
      equals: vi.fn(() => ({
        count: vi.fn(() => Promise.resolve(0)),
      })),
    })) as any,
  },
  mockOfflineArtwork: {
    get: vi.fn() as any,
    put: vi.fn(() => Promise.resolve()) as any,
    delete: vi.fn(() => Promise.resolve()) as any,
    toArray: vi.fn(() => Promise.resolve([] as any[])) as any,
    clear: vi.fn(() => Promise.resolve()) as any,
    where: vi.fn(() => ({
      equals: vi.fn(() => ({
        count: vi.fn(() => Promise.resolve(0)),
      })),
    })) as any,
  },
  mockCachedTracks: {
    get: vi.fn() as any,
    put: vi.fn(() => Promise.resolve()) as any,
    toArray: vi.fn(() => Promise.resolve([] as any[])) as any,
  },
  mockPartialDownloads: {
    get: vi.fn() as any,
    put: vi.fn(() => Promise.resolve()) as any,
    delete: vi.fn(() => Promise.resolve()) as any,
  },
}));

vi.mock('../../db', () => ({
  db: {
    offlineTracks: mockOfflineTracks,
    offlineArtwork: mockOfflineArtwork,
    cachedTracks: mockCachedTracks,
    partialDownloads: mockPartialDownloads,
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

vi.mock('../../utils/albumHash', () => ({
  computeAlbumHash: vi.fn((artist: string, album: string) =>
    Promise.resolve(`hash-${artist}-${album}`)
  ),
}));

import type { OfflineTrack, OfflineArtwork, PartialDownload } from '../../db';
import {
  downloadTrackForOffline,
  getOfflineTrack,
  isTrackOffline,
  removeOfflineTrack,
  getOfflineTrackIds,
  getOfflineStorageUsage,
  clearAllOfflineTracks,
  createOfflineTrackUrl,
  revokeOfflineTrackUrl,
  formatBytes,
  getPartialDownload,
  downloadTracksForOffline,
  downloadArtworkForOffline,
  getOfflineArtwork,
  createOfflineArtworkUrl,
} from '../offlineService';

describe('offlineService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('formatBytes', () => {
    it('should format 0 bytes', () => {
      expect(formatBytes(0)).toBe('0 Bytes');
    });

    it('should format bytes', () => {
      expect(formatBytes(500)).toBe('500 Bytes');
    });

    it('should format kilobytes', () => {
      expect(formatBytes(1024)).toBe('1 KB');
    });

    it('should format megabytes', () => {
      expect(formatBytes(1048576)).toBe('1 MB');
    });

    it('should format gigabytes with decimals', () => {
      expect(formatBytes(1610612736)).toBe('1.5 GB');
    });
  });

  describe('getOfflineTrack', () => {
    it('should return audio blob when track exists', async () => {
      const audioBlob = new Blob(['audio data'], { type: 'audio/mpeg' });
      mockOfflineTracks.get.mockResolvedValueOnce({
        id: 'track-1',
        audio: audioBlob,
        cachedAt: new Date(),
      });

      const result = await getOfflineTrack('track-1');
      expect(result).toBe(audioBlob);
      expect(mockOfflineTracks.get).toHaveBeenCalledWith('track-1');
    });

    it('should return null when track does not exist', async () => {
      mockOfflineTracks.get.mockResolvedValueOnce(undefined);

      const result = await getOfflineTrack('non-existent');
      expect(result).toBeNull();
    });
  });

  describe('isTrackOffline', () => {
    it('should return true when track exists', async () => {
      const mockCount = vi.fn(() => Promise.resolve(1));
      const mockEquals = vi.fn(() => ({ count: mockCount }));
      mockOfflineTracks.where.mockReturnValueOnce({ equals: mockEquals });

      const result = await isTrackOffline('track-1');
      expect(result).toBe(true);
      expect(mockOfflineTracks.where).toHaveBeenCalledWith('id');
      expect(mockEquals).toHaveBeenCalledWith('track-1');
    });

    it('should return false when track does not exist', async () => {
      const mockCount = vi.fn(() => Promise.resolve(0));
      const mockEquals = vi.fn(() => ({ count: mockCount }));
      mockOfflineTracks.where.mockReturnValueOnce({ equals: mockEquals });

      const result = await isTrackOffline('non-existent');
      expect(result).toBe(false);
    });
  });

  describe('removeOfflineTrack', () => {
    it('should delete track from IndexedDB', async () => {
      await removeOfflineTrack('track-1');
      expect(mockOfflineTracks.delete).toHaveBeenCalledWith('track-1');
    });
  });

  describe('getOfflineTrackIds', () => {
    it('should return array of track IDs', async () => {
      mockOfflineTracks.toArray.mockResolvedValueOnce([
        { id: 'track-1', audio: new Blob(), cachedAt: new Date() } as OfflineTrack,
        { id: 'track-2', audio: new Blob(), cachedAt: new Date() } as OfflineTrack,
        { id: 'track-3', audio: new Blob(), cachedAt: new Date() } as OfflineTrack,
      ]);

      const result = await getOfflineTrackIds();
      expect(result).toEqual(['track-1', 'track-2', 'track-3']);
    });

    it('should return empty array when no offline tracks', async () => {
      mockOfflineTracks.toArray.mockResolvedValueOnce([]);

      const result = await getOfflineTrackIds();
      expect(result).toEqual([]);
    });
  });

  describe('getOfflineStorageUsage', () => {
    it('should calculate total storage usage', async () => {
      const blob1 = new Blob(['a'.repeat(1024)]);
      const blob2 = new Blob(['b'.repeat(2048)]);
      const artBlob = new Blob(['img'.repeat(512)]);

      mockOfflineTracks.toArray.mockResolvedValueOnce([
        { id: 't1', audio: blob1, cachedAt: new Date() } as OfflineTrack,
        { id: 't2', audio: blob2, cachedAt: new Date() } as OfflineTrack,
      ]);
      mockOfflineArtwork.toArray.mockResolvedValueOnce([
        { hash: 'h1', artwork: artBlob, cachedAt: new Date() } as OfflineArtwork,
      ]);

      const usage = await getOfflineStorageUsage();
      expect(usage.count).toBe(2);
      expect(usage.artworkCount).toBe(1);
      expect(usage.sizeBytes).toBe(blob1.size + blob2.size + artBlob.size);
      expect(usage.artworkSizeBytes).toBe(artBlob.size);
      expect(usage.sizeFormatted).toBeDefined();
    });

    it('should return zero counts when no data stored', async () => {
      mockOfflineTracks.toArray.mockResolvedValueOnce([]);
      mockOfflineArtwork.toArray.mockResolvedValueOnce([]);

      const usage = await getOfflineStorageUsage();
      expect(usage.count).toBe(0);
      expect(usage.sizeBytes).toBe(0);
      expect(usage.artworkCount).toBe(0);
      expect(usage.sizeFormatted).toBe('0 Bytes');
    });
  });

  describe('clearAllOfflineTracks', () => {
    it('should clear both tracks and artwork', async () => {
      await clearAllOfflineTracks();
      expect(mockOfflineTracks.clear).toHaveBeenCalled();
      expect(mockOfflineArtwork.clear).toHaveBeenCalled();
    });
  });

  describe('createOfflineTrackUrl', () => {
    it('should create object URL from blob', () => {
      const mockUrl = 'blob:http://localhost/fake-uuid';
      URL.createObjectURL = vi.fn(() => mockUrl);

      const blob = new Blob(['audio data'], { type: 'audio/mpeg' });
      const url = createOfflineTrackUrl(blob);

      expect(url).toBe(mockUrl);
      expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
    });
  });

  describe('revokeOfflineTrackUrl', () => {
    it('should revoke object URL', () => {
      URL.revokeObjectURL = vi.fn();

      revokeOfflineTrackUrl('blob:http://localhost/fake-uuid');
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:http://localhost/fake-uuid');
    });
  });

  describe('createOfflineArtworkUrl', () => {
    it('should create object URL for artwork blob', () => {
      const mockUrl = 'blob:http://localhost/artwork-uuid';
      URL.createObjectURL = vi.fn(() => mockUrl);

      const blob = new Blob(['image data'], { type: 'image/jpeg' });
      const url = createOfflineArtworkUrl(blob);

      expect(url).toBe(mockUrl);
    });
  });

  describe('getPartialDownload', () => {
    it('should return partial download when exists', async () => {
      const partial: PartialDownload = {
        trackId: 'track-1',
        bytesDownloaded: 1024,
        totalBytes: 5120,
        chunks: [new Blob(['chunk1'])],
        updatedAt: new Date(),
      };
      mockPartialDownloads.get.mockResolvedValueOnce(partial);

      const result = await getPartialDownload('track-1');
      expect(result).toEqual(partial);
    });

    it('should return undefined when no partial download', async () => {
      mockPartialDownloads.get.mockResolvedValueOnce(undefined);

      const result = await getPartialDownload('non-existent');
      expect(result).toBeUndefined();
    });
  });

  describe('downloadTrackForOffline', () => {
    it('should skip download if track already exists', async () => {
      mockOfflineTracks.get.mockResolvedValueOnce({
        id: 'track-1',
        audio: new Blob(),
        cachedAt: new Date(),
      });

      const onProgress = vi.fn();
      await downloadTrackForOffline('track-1', onProgress);

      expect(onProgress).toHaveBeenCalledWith({
        loaded: 1,
        total: 1,
        percentage: 100,
      });
      expect(global.fetch).not.toHaveBeenCalled();
    });

    it('should download and store track when not cached', async () => {
      mockOfflineTracks.get.mockResolvedValueOnce(undefined);
      mockPartialDownloads.get.mockResolvedValueOnce(undefined);
      mockCachedTracks.get.mockResolvedValueOnce(undefined);

      const audioData = new Uint8Array([1, 2, 3, 4, 5]);
      const mockResponse = {
        ok: true,
        status: 200,
        headers: new Headers({
          'content-length': '5',
          'content-type': 'audio/mpeg',
        }),
        body: null,
        blob: vi.fn(() => Promise.resolve(new Blob([audioData], { type: 'audio/mpeg' }))),
      };

      // First call: stream request, second call: metadata fetch (ensureTrackMetadataCached)
      (global.fetch as ReturnType<typeof vi.fn>)
        .mockResolvedValueOnce(mockResponse)
        .mockResolvedValueOnce({ ok: false }); // metadata fetch fails (ok for test)

      await downloadTrackForOffline('track-1');

      expect(global.fetch).toHaveBeenCalledWith(
        '/api/v1/tracks/track-1/stream',
        expect.objectContaining({
          headers: {},
        })
      );
      expect(mockOfflineTracks.put).toHaveBeenCalled();
      expect(mockPartialDownloads.delete).toHaveBeenCalledWith('track-1');
    });

    it('should throw on failed HTTP response', async () => {
      mockOfflineTracks.get.mockResolvedValueOnce(undefined);
      mockPartialDownloads.get.mockResolvedValueOnce(undefined);

      const mockResponse = {
        ok: false,
        status: 404,
        statusText: 'Not Found',
        headers: new Headers(),
      };

      (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(mockResponse);

      await expect(downloadTrackForOffline('missing-track')).rejects.toThrow(
        'Failed to download track: Not Found'
      );
    });

    it('should handle quota exceeded error', async () => {
      mockOfflineTracks.get.mockResolvedValueOnce(undefined);
      mockPartialDownloads.get.mockResolvedValueOnce(undefined);

      const audioData = new Uint8Array([1, 2, 3]);
      const mockResponse = {
        ok: true,
        status: 200,
        headers: new Headers({
          'content-length': '3',
          'content-type': 'audio/mpeg',
        }),
        body: null,
        blob: vi.fn(() => Promise.resolve(new Blob([audioData]))),
      };

      (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(mockResponse);

      const quotaError = new DOMException('Quota exceeded', 'QuotaExceededError');
      mockOfflineTracks.put.mockRejectedValueOnce(quotaError);

      const dispatchSpy = vi.spyOn(window, 'dispatchEvent');

      await expect(downloadTrackForOffline('big-track')).rejects.toThrow(
        'Storage quota exceeded'
      );

      expect(dispatchSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'offline-storage-full',
        })
      );
      // Should clear partial download on quota error
      expect(mockPartialDownloads.delete).toHaveBeenCalledWith('big-track');
    });

    it('should resume from partial download using Range header', async () => {
      mockOfflineTracks.get.mockResolvedValueOnce(undefined);
      const partial: PartialDownload = {
        trackId: 'track-1',
        bytesDownloaded: 1000,
        totalBytes: 5000,
        chunks: [new Blob(['existing-data'])],
        updatedAt: new Date(),
      };
      mockPartialDownloads.get.mockResolvedValueOnce(partial);

      const newData = new Uint8Array([5, 6, 7, 8]);
      const mockResponse = {
        ok: false,
        status: 206,
        headers: new Headers({
          'content-range': 'bytes 1000-4999/5000',
          'content-type': 'audio/mpeg',
        }),
        body: null,
        blob: vi.fn(() => Promise.resolve(new Blob([newData], { type: 'audio/mpeg' }))),
      };

      (global.fetch as ReturnType<typeof vi.fn>)
        .mockResolvedValueOnce(mockResponse)
        .mockResolvedValueOnce({ ok: false }); // metadata fetch

      await downloadTrackForOffline('track-1');

      // Should have sent Range header
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/v1/tracks/track-1/stream',
        expect.objectContaining({
          headers: { Range: 'bytes=1000-' },
        })
      );
      expect(mockOfflineTracks.put).toHaveBeenCalled();
    });
  });

  describe('downloadTracksForOffline', () => {
    it('should download multiple tracks and report progress', async () => {
      // Mock each track as not existing yet
      mockOfflineTracks.get
        .mockResolvedValueOnce(undefined)
        .mockResolvedValueOnce(undefined);

      mockPartialDownloads.get
        .mockResolvedValueOnce(undefined)
        .mockResolvedValueOnce(undefined);

      mockCachedTracks.get
        .mockResolvedValueOnce(undefined)
        .mockResolvedValueOnce(undefined);

      const mockResponse = {
        ok: true,
        status: 200,
        headers: new Headers({
          'content-length': '100',
          'content-type': 'audio/mpeg',
        }),
        body: null,
        blob: vi.fn(() => Promise.resolve(new Blob(['data']))),
      };

      (global.fetch as ReturnType<typeof vi.fn>)
        .mockResolvedValueOnce(mockResponse) // track 1 stream
        .mockResolvedValueOnce({ ok: false }) // track 1 metadata
        .mockResolvedValueOnce(mockResponse) // track 2 stream
        .mockResolvedValueOnce({ ok: false }); // track 2 metadata

      const onProgress = vi.fn();
      const result = await downloadTracksForOffline(['t1', 't2'], onProgress);

      expect(result.succeeded).toBe(2);
      expect(result.failed).toBe(0);
    });

    it('should count failed downloads', async () => {
      mockOfflineTracks.get.mockResolvedValueOnce(undefined);
      mockPartialDownloads.get.mockResolvedValueOnce(undefined);

      (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Server Error',
        headers: new Headers(),
      });

      const result = await downloadTracksForOffline(['t1']);

      expect(result.succeeded).toBe(0);
      expect(result.failed).toBe(1);
    });

    it('should return zeros for empty track list', async () => {
      const result = await downloadTracksForOffline([]);
      expect(result.succeeded).toBe(0);
      expect(result.failed).toBe(0);
    });
  });

  describe('downloadArtworkForOffline', () => {
    it('should skip if artwork already downloaded', async () => {
      mockOfflineArtwork.get.mockResolvedValueOnce({
        hash: 'hash-Artist-Album',
        artwork: new Blob(),
        cachedAt: new Date(),
      });

      const result = await downloadArtworkForOffline('Artist', 'Album');
      expect(result).toBe('hash-Artist-Album');
      expect(global.fetch).not.toHaveBeenCalled();
    });

    it('should download and store artwork', async () => {
      mockOfflineArtwork.get.mockResolvedValueOnce(undefined);

      const artworkBlob = new Blob(['image'], { type: 'image/jpeg' });
      (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: true,
        blob: () => Promise.resolve(artworkBlob),
      });

      const result = await downloadArtworkForOffline('Artist', 'Album');
      expect(result).toBe('hash-Artist-Album');
      expect(mockOfflineArtwork.put).toHaveBeenCalled();
    });

    it('should return null when artwork not available', async () => {
      mockOfflineArtwork.get.mockResolvedValueOnce(undefined);

      (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: false,
        status: 404,
      });

      const result = await downloadArtworkForOffline('Artist', 'Album');
      expect(result).toBeNull();
    });
  });

  describe('getOfflineArtwork', () => {
    it('should return artwork blob when exists', async () => {
      const artBlob = new Blob(['image data'], { type: 'image/jpeg' });
      mockOfflineArtwork.get.mockResolvedValueOnce({
        hash: 'hash-1',
        artwork: artBlob,
        cachedAt: new Date(),
      });

      const result = await getOfflineArtwork('hash-1');
      expect(result).toBe(artBlob);
    });

    it('should return null when artwork not found', async () => {
      mockOfflineArtwork.get.mockResolvedValueOnce(undefined);

      const result = await getOfflineArtwork('no-hash');
      expect(result).toBeNull();
    });
  });
});
