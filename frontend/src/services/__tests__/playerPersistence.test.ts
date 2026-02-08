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
  fetchTracksByIds,
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

  describe('fetchTracksByIds', () => {
    beforeEach(() => {
      global.fetch = vi.fn();
    });

    it('should fetch tracks from API', async () => {
      const track1 = { id: 't1', title: 'Song 1', artist: 'A' };
      const track2 = { id: 't2', title: 'Song 2', artist: 'B' };

      (global.fetch as ReturnType<typeof vi.fn>)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(track1) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(track2) });

      const result = await fetchTracksByIds(['t1', 't2']);

      expect(result).toEqual([track1, track2]);
      expect(global.fetch).toHaveBeenCalledTimes(2);
    });

    it('should return empty array for empty input', async () => {
      const result = await fetchTracksByIds([]);
      expect(result).toEqual([]);
      expect(global.fetch).not.toHaveBeenCalled();
    });

    it('should skip tracks that fail to fetch', async () => {
      const track1 = { id: 't1', title: 'Song 1' };

      (global.fetch as ReturnType<typeof vi.fn>)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(track1) })
        .mockResolvedValueOnce({ ok: false, status: 404 });

      const result = await fetchTracksByIds(['t1', 't2']);

      expect(result).toEqual([track1]);
    });

    it('should handle network errors gracefully', async () => {
      (global.fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
        new Error('Network error')
      );

      const result = await fetchTracksByIds(['t1']);

      // Individual track errors are caught, but the outer try-catch may also fire
      expect(result).toEqual([]);
    });
  });

  describe('debouncedSavePlayerState', () => {
    it('should debounce saves by 500ms', async () => {
      const state = createMockState();

      debouncedSavePlayerState(state);
      debouncedSavePlayerState(state);
      debouncedSavePlayerState(state);

      // Nothing should have been saved yet
      expect(mockPlayerState.put).not.toHaveBeenCalled();

      // Advance past debounce delay
      vi.advanceTimersByTime(600);

      // Allow the async savePlayerState to run
      await vi.runAllTimersAsync();

      // Should have saved only once
      expect(mockPlayerState.put).toHaveBeenCalledTimes(1);
    });

    it('should use latest state when debouncing', async () => {
      const state1 = createMockState();
      state1.volume = 0.3;

      const state2 = createMockState();
      state2.volume = 0.9;

      debouncedSavePlayerState(state1);
      debouncedSavePlayerState(state2);

      vi.advanceTimersByTime(600);
      await vi.runAllTimersAsync();

      // Should have saved with the last state's volume
      expect(mockPlayerState.put).toHaveBeenCalledWith(
        expect.objectContaining({
          volume: 0.9,
        })
      );
    });
  });
});
