/**
 * Tests for playerPersistence - saves and loads player state from IndexedDB per profile.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

// Mock db module
/* eslint-disable @typescript-eslint/no-explicit-any */
const { mockPlayerState } = vi.hoisted(() => ({
  mockPlayerState: {
    get: vi.fn() as any,
    put: vi.fn(() => Promise.resolve()) as any,
    delete: vi.fn(() => Promise.resolve()) as any,
  },
}));

vi.mock('../../db', () => ({
  db: {
    playerState: mockPlayerState,
  },
  isIndexedDBAvailable: vi.fn(() => Promise.resolve(true)),
}));

vi.mock('../profileService', () => ({
  getSelectedProfileId: vi.fn(() => Promise.resolve('profile-123')),
}));

const { mockGetBatch } = vi.hoisted(() => ({
  mockGetBatch: vi.fn((_ids: string[]) => Promise.resolve([] as Record<string, unknown>[])),
}));

vi.mock('../../api', () => ({
  tracksApi: {
    getBatch: mockGetBatch,
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
  savePlayerState,
  loadPlayerState,
  loadPlayerStateForProfile,
  clearPlayerState,
  migrateOldPlayerState,
  fetchTracksBatched,
  debouncedSavePlayerState,
} from '../playerPersistence';
import { isIndexedDBAvailable } from '../../db';
import { getSelectedProfileId } from '../profileService';
import type { Track, QueueItem } from '../../types';

// Helper to create mock state
function createMockState() {
  const track: Track = {
    id: 'track-1',
    title: 'Test Song',
    artist: 'Test Artist',
    album: 'Test Album',
    album_artist: null,
    album_type: 'album',
    track_number: 1,
    disc_number: 1,
    year: 2024,
    genre: 'Rock',
    duration_seconds: 200,
    format: 'mp3',
    file_path: '/music/test.mp3',
    analysis_version: 1,
  };

  const queueItem: QueueItem = {
    track,
    queueId: 'q-1',
  };

  return {
    volume: 0.8,
    shuffle: true,
    repeat: 'all' as const,
    consume: false,
    queue: [queueItem],
    queueIndex: 0,
    currentTrack: track,
    shuffleOrder: [0],
    shuffleIndex: 0,
    currentTime: 42.5,
  };
}

describe('playerPersistence', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('savePlayerState', () => {
    it('should save state to IndexedDB for current profile', async () => {
      const state = createMockState();

      await savePlayerState(state);

      expect(mockPlayerState.put).toHaveBeenCalledWith(
        expect.objectContaining({
          id: 'profile-123',
          volume: 0.8,
          shuffle: true,
          repeat: 'all',
          queueTrackIds: ['track-1'],
          queueIndex: 0,
          currentTrackId: 'track-1',
          shuffleOrder: [0],
          shuffleIndex: 0,
          currentTime: 42.5,
        })
      );
    });

    it('should not save when IndexedDB unavailable', async () => {
      vi.mocked(isIndexedDBAvailable).mockResolvedValueOnce(false);

      const state = createMockState();
      await savePlayerState(state);

      expect(mockPlayerState.put).not.toHaveBeenCalled();
    });

    it('should not save when no profile selected', async () => {
      vi.mocked(getSelectedProfileId).mockResolvedValueOnce(null);

      const state = createMockState();
      await savePlayerState(state);

      expect(mockPlayerState.put).not.toHaveBeenCalled();
    });

    it('should handle null currentTrack', async () => {
      const state = {
        ...createMockState(),
        currentTrack: null as Track | null,
      };

      await savePlayerState(state);

      expect(mockPlayerState.put).toHaveBeenCalledWith(
        expect.objectContaining({
          currentTrackId: null,
        })
      );
    });

    it('should silently handle save errors', async () => {
      mockPlayerState.put.mockRejectedValueOnce(new Error('IDB write failed'));

      const state = createMockState();
      // Should not throw
      await savePlayerState(state);
    });

    it('should include updatedAt timestamp', async () => {
      const state = createMockState();
      await savePlayerState(state);

      const savedState = mockPlayerState.put.mock.calls[0]?.[0] as Record<string, unknown> | undefined;
      expect(savedState).toBeDefined();
      expect(savedState!.updatedAt).toBeInstanceOf(Date);
    });
  });

  describe('loadPlayerState', () => {
    it('should load state for current profile', async () => {
      const persisted = {
        id: 'profile-123',
        volume: 0.7,
        shuffle: false,
        repeat: 'off' as const,
        queueTrackIds: ['t1', 't2'],
        queueIndex: 1,
        currentTrackId: 't2',
        shuffleOrder: [],
        shuffleIndex: -1,
        currentTime: 10,
        updatedAt: new Date(),
      };
      mockPlayerState.get.mockResolvedValueOnce(persisted);

      const result = await loadPlayerState();

      expect(result).toEqual(persisted);
      expect(mockPlayerState.get).toHaveBeenCalledWith('profile-123');
    });

    it('should return null when no saved state', async () => {
      mockPlayerState.get.mockResolvedValueOnce(undefined);

      const result = await loadPlayerState();
      expect(result).toBeNull();
    });

    it('should return null when IndexedDB unavailable', async () => {
      vi.mocked(isIndexedDBAvailable).mockResolvedValueOnce(false);

      const result = await loadPlayerState();
      expect(result).toBeNull();
      expect(mockPlayerState.get).not.toHaveBeenCalled();
    });

    it('should return null when no profile selected', async () => {
      vi.mocked(getSelectedProfileId).mockResolvedValueOnce(null);

      const result = await loadPlayerState();
      expect(result).toBeNull();
    });

    it('should return null on load error', async () => {
      mockPlayerState.get.mockRejectedValueOnce(new Error('IDB read error'));

      const result = await loadPlayerState();
      expect(result).toBeNull();
    });
  });

  describe('loadPlayerStateForProfile', () => {
    it('should load state for a specific profile', async () => {
      const persisted = {
        id: 'other-profile',
        volume: 0.5,
        shuffle: true,
        repeat: 'one' as const,
        queueTrackIds: [],
        queueIndex: -1,
        currentTrackId: null,
        shuffleOrder: [],
        shuffleIndex: -1,
        currentTime: 0,
        updatedAt: new Date(),
      };
      mockPlayerState.get.mockResolvedValueOnce(persisted);

      const result = await loadPlayerStateForProfile('other-profile');

      expect(result).toEqual(persisted);
      expect(mockPlayerState.get).toHaveBeenCalledWith('other-profile');
    });

    it('should return null when IndexedDB unavailable', async () => {
      vi.mocked(isIndexedDBAvailable).mockResolvedValueOnce(false);

      const result = await loadPlayerStateForProfile('some-profile');
      expect(result).toBeNull();
    });

    it('should return null on error', async () => {
      mockPlayerState.get.mockRejectedValueOnce(new Error('fail'));

      const result = await loadPlayerStateForProfile('some-profile');
      expect(result).toBeNull();
    });
  });

  describe('clearPlayerState', () => {
    it('should delete state for current profile', async () => {
      await clearPlayerState();

      expect(mockPlayerState.delete).toHaveBeenCalledWith('profile-123');
    });

    it('should not delete when IndexedDB unavailable', async () => {
      vi.mocked(isIndexedDBAvailable).mockResolvedValueOnce(false);

      await clearPlayerState();
      expect(mockPlayerState.delete).not.toHaveBeenCalled();
    });

    it('should not delete when no profile selected', async () => {
      vi.mocked(getSelectedProfileId).mockResolvedValueOnce(null);

      await clearPlayerState();
      expect(mockPlayerState.delete).not.toHaveBeenCalled();
    });

    it('should silently handle errors', async () => {
      mockPlayerState.delete.mockRejectedValueOnce(new Error('delete failed'));

      // Should not throw
      await clearPlayerState();
    });
  });

  describe('migrateOldPlayerState', () => {
    it('should migrate old fixed-ID state to current profile', async () => {
      const oldState = {
        id: 'player-state',
        volume: 0.9,
        shuffle: false,
        repeat: 'off' as const,
        queueTrackIds: ['t1'],
        queueIndex: 0,
        currentTrackId: 't1',
        shuffleOrder: [],
        shuffleIndex: -1,
        currentTime: 30,
        updatedAt: new Date(),
      };

      mockPlayerState.get
        .mockResolvedValueOnce(oldState) // get('player-state')
        .mockResolvedValueOnce(undefined); // get(profileId) - no existing

      await migrateOldPlayerState();

      // Should write with new profile ID
      expect(mockPlayerState.put).toHaveBeenCalledWith(
        expect.objectContaining({
          id: 'profile-123',
          volume: 0.9,
        })
      );
      // Should delete old state
      expect(mockPlayerState.delete).toHaveBeenCalledWith('player-state');
    });

    it('should not overwrite existing profile state', async () => {
      const oldState = {
        id: 'player-state',
        volume: 0.5,
        shuffle: false,
        repeat: 'off' as const,
        queueTrackIds: [],
        queueIndex: -1,
        currentTrackId: null,
        shuffleOrder: [],
        shuffleIndex: -1,
        currentTime: 0,
        updatedAt: new Date(),
      };

      const existingState = {
        id: 'profile-123',
        volume: 0.8,
        shuffle: true,
        repeat: 'all' as const,
        queueTrackIds: ['t1', 't2'],
        queueIndex: 1,
        currentTrackId: 't2',
        shuffleOrder: [1, 0],
        shuffleIndex: 0,
        currentTime: 60,
        updatedAt: new Date(),
      };

      mockPlayerState.get
        .mockResolvedValueOnce(oldState)
        .mockResolvedValueOnce(existingState);

      await migrateOldPlayerState();

      // Should NOT put new state (existing state takes priority)
      expect(mockPlayerState.put).not.toHaveBeenCalled();
      // But should still delete old state
      expect(mockPlayerState.delete).toHaveBeenCalledWith('player-state');
    });

    it('should do nothing when no old state exists', async () => {
      mockPlayerState.get.mockResolvedValueOnce(undefined);

      await migrateOldPlayerState();

      expect(mockPlayerState.put).not.toHaveBeenCalled();
      expect(mockPlayerState.delete).not.toHaveBeenCalled();
    });

    it('should skip when IndexedDB unavailable', async () => {
      vi.mocked(isIndexedDBAvailable).mockResolvedValueOnce(false);

      await migrateOldPlayerState();

      expect(mockPlayerState.get).not.toHaveBeenCalled();
    });
  });

  describe('fetchTracksBatched', () => {
    it('should fetch tracks using batch API', async () => {
      const track1 = { id: 't1', title: 'Song 1', artist: 'A' };
      const track2 = { id: 't2', title: 'Song 2', artist: 'B' };

      mockGetBatch.mockResolvedValueOnce([track1, track2]);

      const result = await fetchTracksBatched(['t1', 't2']);

      expect(result).toEqual([track1, track2]);
      expect(mockGetBatch).toHaveBeenCalledWith(['t1', 't2']);
    });

    it('should return empty array for empty input', async () => {
      const result = await fetchTracksBatched([]);
      expect(result).toEqual([]);
      expect(mockGetBatch).not.toHaveBeenCalled();
    });

    it('should chunk into groups of 50 and fetch in parallel', async () => {
      // Create 120 track IDs
      const ids = Array.from({ length: 120 }, (_, i) => `t${i}`);
      const tracks = ids.map(id => ({ id, title: `Song ${id}` }));

      mockGetBatch
        .mockResolvedValueOnce(tracks.slice(0, 50))
        .mockResolvedValueOnce(tracks.slice(50, 100))
        .mockResolvedValueOnce(tracks.slice(100, 120));

      const result = await fetchTracksBatched(ids);

      expect(mockGetBatch).toHaveBeenCalledTimes(3);
      expect(mockGetBatch).toHaveBeenCalledWith(ids.slice(0, 50));
      expect(mockGetBatch).toHaveBeenCalledWith(ids.slice(50, 100));
      expect(mockGetBatch).toHaveBeenCalledWith(ids.slice(100, 120));
      expect(result).toHaveLength(120);
    });

    it('should preserve original ID order', async () => {
      const track1 = { id: 't1', title: 'Song 1' };
      const track2 = { id: 't2', title: 'Song 2' };

      // API returns in different order
      mockGetBatch.mockResolvedValueOnce([track2, track1]);

      const result = await fetchTracksBatched(['t1', 't2']);

      expect(result).toEqual([track1, track2]);
    });

    it('should skip missing tracks gracefully', async () => {
      const track1 = { id: 't1', title: 'Song 1' };

      // Only t1 returned, t2 is missing
      mockGetBatch.mockResolvedValueOnce([track1]);

      const result = await fetchTracksBatched(['t1', 't2']);

      expect(result).toEqual([track1]);
    });

    it('should handle batch errors gracefully', async () => {
      mockGetBatch.mockRejectedValueOnce(new Error('Network error'));

      const result = await fetchTracksBatched(['t1']);

      expect(result).toEqual([]);
    });
  });

  describe('debouncedSavePlayerState', () => {
    it('should throttle saves with leading + trailing edges', async () => {
      const state = createMockState();

      // First call saves immediately (leading edge, since >500ms since last save)
      debouncedSavePlayerState(state);
      await vi.runAllTimersAsync();
      expect(mockPlayerState.put).toHaveBeenCalledTimes(1);

      // Rapid subsequent calls within 500ms schedule a trailing save
      debouncedSavePlayerState(state);
      debouncedSavePlayerState(state);
      expect(mockPlayerState.put).toHaveBeenCalledTimes(1);

      // Advance past throttle window to trigger trailing save
      vi.advanceTimersByTime(600);
      await vi.runAllTimersAsync();

      expect(mockPlayerState.put).toHaveBeenCalledTimes(2);
    });

    it('should use latest state for trailing save', async () => {
      const state1 = createMockState();
      state1.volume = 0.3;

      const state2 = createMockState();
      state2.volume = 0.9;

      // First call saves immediately with state1
      debouncedSavePlayerState(state1);
      await vi.runAllTimersAsync();

      // Second call schedules trailing save with state2
      debouncedSavePlayerState(state2);

      vi.advanceTimersByTime(600);
      await vi.runAllTimersAsync();

      // Last save should have state2's volume
      const lastCall = mockPlayerState.put.mock.calls[mockPlayerState.put.mock.calls.length - 1];
      expect(lastCall[0]).toEqual(
        expect.objectContaining({
          volume: 0.9,
        })
      );
    });

    it('should save during continuous rapid calls (e.g. playback position updates)', async () => {
      const state = createMockState();

      // Simulate rapid calls like setCurrentTime during playback (~16ms apart)
      // With the old debounce, saves would NEVER fire. With throttle, they do.
      for (let i = 0; i < 10; i++) {
        state.currentTime = i;
        debouncedSavePlayerState(state);
        vi.advanceTimersByTime(16);
      }

      await vi.runAllTimersAsync();

      // Should have saved at least once (leading edge)
      expect(mockPlayerState.put.mock.calls.length).toBeGreaterThanOrEqual(1);

      // Advance to flush any trailing save
      vi.advanceTimersByTime(600);
      await vi.runAllTimersAsync();

      // Total saves should be reasonable (not 0, not 10)
      const totalSaves = mockPlayerState.put.mock.calls.length;
      expect(totalSaves).toBeGreaterThanOrEqual(1);
      expect(totalSaves).toBeLessThanOrEqual(3);
    });
  });
});
