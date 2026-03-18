/**
 * Tests for artworkStore - artwork request batching, polling, URL management.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

vi.mock('../../utils/albumHash', () => ({
  computeAlbumHash: vi.fn(async (artist: string, album: string) =>
    `hash_${(artist || 'unknown').toLowerCase()}_${(album || 'unknown').toLowerCase()}`
  ),
}));

vi.mock('../../utils/logger', () => ({
  createLogger: () => ({
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  }),
}));

const { mockArtworkApi } = vi.hoisted(() => ({
  mockArtworkApi: {
    queueBatch: vi.fn(),
    statusBatch: vi.fn(),
  },
}));

vi.mock('../../api/metadata', () => ({
  artworkApi: mockArtworkApi,
}));

// artworkStore still uses getApiUrl for getArtworkUrl
vi.mock('../../api/base', () => ({
  getApiUrl: (path: string) => `/api/v1${path}`,
}));

import { useArtworkStore } from '../artworkStore';

describe('artworkStore', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.restoreAllMocks();

    // Reset store state
    useArtworkStore.setState({
      status: new Map(),
      hashes: new Map(),
      pendingHashes: new Set(),
      isPolling: false,
      pollIntervalId: null,
    });
  });

  afterEach(() => {
    // Stop any running polling
    const { pollIntervalId } = useArtworkStore.getState();
    if (pollIntervalId) clearInterval(pollIntervalId);
    vi.useRealTimers();
  });

  describe('getStatus', () => {
    it('should return unknown for unseen albums', () => {
      const { getStatus } = useArtworkStore.getState();
      expect(getStatus('Artist', 'Album')).toBe('unknown');
    });
  });

  describe('getHash', () => {
    it('should return undefined for unseen albums', () => {
      const { getHash } = useArtworkStore.getState();
      expect(getHash('Artist', 'Album')).toBeUndefined();
    });
  });

  describe('getArtworkUrl', () => {
    it('should return null when hash is not available', () => {
      const { getArtworkUrl } = useArtworkStore.getState();
      expect(getArtworkUrl('Artist', 'Album', 'thumb')).toBeNull();
    });

    it('should return null when status is not ready', () => {
      useArtworkStore.setState({
        hashes: new Map([['Artist::Album', 'abc123']]),
        status: new Map([['Artist::Album', 'pending']]),
      });
      const { getArtworkUrl } = useArtworkStore.getState();
      expect(getArtworkUrl('Artist', 'Album', 'thumb')).toBeNull();
    });

    it('should return URL when status is ready and hash exists', () => {
      useArtworkStore.setState({
        hashes: new Map([['Artist::Album', 'abc123']]),
        status: new Map([['Artist::Album', 'ready']]),
      });
      const { getArtworkUrl } = useArtworkStore.getState();
      expect(getArtworkUrl('Artist', 'Album', 'thumb')).toBe('/api/v1/artwork/abc123/thumb');
      expect(getArtworkUrl('Artist', 'Album', 'full')).toBe('/api/v1/artwork/abc123/full');
    });
  });

  describe('requestArtwork', () => {
    it('should do nothing for empty array', async () => {
      const { requestArtwork } = useArtworkStore.getState();
      await requestArtwork([]);
      expect(mockArtworkApi.queueBatch).not.toHaveBeenCalled();
    });

    it('should skip already-seen albums', async () => {
      // Mark album as already seen
      useArtworkStore.setState({
        status: new Map([['Artist::Album', 'ready']]),
      });

      const { requestArtwork } = useArtworkStore.getState();
      await requestArtwork([{ artist: 'Artist', album: 'Album' }]);
      expect(mockArtworkApi.queueBatch).not.toHaveBeenCalled();
    });

    it('should mark albums as ready when they already exist', async () => {
      mockArtworkApi.queueBatch.mockResolvedValueOnce({
        status: 'ok',
        queued_count: 0,
        existing_count: 1,
        queued_hashes: [],
        existing_hashes: ['hash_artist_album'],
        pending_hashes: [],
      });

      const { requestArtwork } = useArtworkStore.getState();
      await requestArtwork([{ artist: 'Artist', album: 'Album' }]);

      const { getStatus } = useArtworkStore.getState();
      expect(getStatus('Artist', 'Album')).toBe('ready');
    });

    it('should mark albums as pending when queued', async () => {
      mockArtworkApi.queueBatch.mockResolvedValueOnce({
        status: 'ok',
        queued_count: 1,
        existing_count: 0,
        queued_hashes: ['hash_artist_album'],
        existing_hashes: [],
        pending_hashes: [],
      });

      const { requestArtwork } = useArtworkStore.getState();
      await requestArtwork([{ artist: 'Artist', album: 'Album' }]);

      const { getStatus, pendingHashes } = useArtworkStore.getState();
      expect(getStatus('Artist', 'Album')).toBe('pending');
      expect(pendingHashes.has('hash_artist_album')).toBe(true);
    });

    it('should mark albums as missing when not queued and not existing', async () => {
      mockArtworkApi.queueBatch.mockResolvedValueOnce({
        status: 'ok',
        queued_count: 0,
        existing_count: 0,
        queued_hashes: [],
        existing_hashes: [],
        pending_hashes: [],
      });

      const { requestArtwork } = useArtworkStore.getState();
      await requestArtwork([{ artist: 'Artist', album: 'Album' }]);

      const { getStatus } = useArtworkStore.getState();
      expect(getStatus('Artist', 'Album')).toBe('missing');
    });

    it('should mark all as missing on API error', async () => {
      mockArtworkApi.queueBatch.mockRejectedValueOnce(new Error('Network error'));

      const { requestArtwork } = useArtworkStore.getState();
      await requestArtwork([{ artist: 'Artist', album: 'Album' }]);

      const { getStatus } = useArtworkStore.getState();
      expect(getStatus('Artist', 'Album')).toBe('missing');
    });
  });

  describe('polling', () => {
    it('should start polling when there are pending hashes', async () => {
      mockArtworkApi.queueBatch.mockResolvedValueOnce({
        status: 'ok',
        queued_count: 1,
        existing_count: 0,
        queued_hashes: ['hash_artist_album'],
        existing_hashes: [],
        pending_hashes: [],
      });

      const { requestArtwork } = useArtworkStore.getState();
      await requestArtwork([{ artist: 'Artist', album: 'Album' }]);

      expect(useArtworkStore.getState().isPolling).toBe(true);
    });

    it('should not start polling when no pending hashes', async () => {
      mockArtworkApi.queueBatch.mockResolvedValueOnce({
        status: 'ok',
        queued_count: 0,
        existing_count: 1,
        queued_hashes: [],
        existing_hashes: ['hash_artist_album'],
        pending_hashes: [],
      });

      const { requestArtwork } = useArtworkStore.getState();
      await requestArtwork([{ artist: 'Artist', album: 'Album' }]);

      expect(useArtworkStore.getState().isPolling).toBe(false);
    });

    it('should stop polling when all pending are resolved', async () => {
      // Set up a pending state
      useArtworkStore.setState({
        status: new Map([['Artist::Album', 'pending']]),
        hashes: new Map([['Artist::Album', 'hash123']]),
        pendingHashes: new Set(['hash123']),
      });

      // Mock the poll response saying artwork is ready
      mockArtworkApi.statusBatch.mockResolvedValue({
        status: { hash123: true },
        failed: [],
      });

      // Start polling
      useArtworkStore.getState().startPolling();
      expect(useArtworkStore.getState().isPolling).toBe(true);

      // Advance timer to trigger poll
      await vi.advanceTimersByTimeAsync(2000);

      expect(useArtworkStore.getState().isPolling).toBe(false);
      expect(useArtworkStore.getState().status.get('Artist::Album')).toBe('ready');
    });

    it('should mark failed hashes as missing and stop polling', async () => {
      useArtworkStore.setState({
        status: new Map([['Artist::Album', 'pending']]),
        hashes: new Map([['Artist::Album', 'hash123']]),
        pendingHashes: new Set(['hash123']),
      });

      mockArtworkApi.statusBatch.mockResolvedValue({
        status: { hash123: false },
        failed: ['hash123'],
      });

      useArtworkStore.getState().startPolling();
      await vi.advanceTimersByTimeAsync(2000);

      expect(useArtworkStore.getState().status.get('Artist::Album')).toBe('missing');
      expect(useArtworkStore.getState().pendingHashes.size).toBe(0);
    });

    it('should not start duplicate polling', () => {
      useArtworkStore.setState({
        pendingHashes: new Set(['hash1']),
      });

      const { startPolling } = useArtworkStore.getState();
      startPolling();
      startPolling(); // Should not start a second interval

      expect(useArtworkStore.getState().isPolling).toBe(true);
    });

    it('stopPolling should clear interval and state', () => {
      useArtworkStore.setState({
        isPolling: true,
        pollIntervalId: setInterval(() => {}, 1000),
      });

      useArtworkStore.getState().stopPolling();

      const state = useArtworkStore.getState();
      expect(state.isPolling).toBe(false);
      expect(state.pollIntervalId).toBeNull();
    });
  });
});
