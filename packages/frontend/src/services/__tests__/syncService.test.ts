/**
 * Tests for syncService - offline action queue, retry logic, and online/offline handling.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock the db module
const mockAdd = vi.fn();
const mockDelete = vi.fn();
const mockUpdate = vi.fn();
const mockClear = vi.fn();
const mockCount = vi.fn();
const mockToArray = vi.fn();
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mockOrderBy = vi.fn((_key?: any) => ({ toArray: mockToArray }));

/* eslint-disable @typescript-eslint/no-explicit-any */
vi.mock('../../db', () => ({
  db: {
    pendingActions: {
      add: (...args: any[]) => mockAdd(...args),
      delete: (...args: any[]) => mockDelete(...args),
      update: (...args: any[]) => mockUpdate(...args),
      clear: () => mockClear(),
      count: () => mockCount(),
      orderBy: (key: any) => mockOrderBy(key),
    },
  },
  isIndexedDBAvailable: vi.fn(() => Promise.resolve(true)),
}));

// Mock profileService
vi.mock('../profileService', () => ({
  getSelectedProfileId: vi.fn(() => Promise.resolve('profile-123')),
}));

// Mock logger
vi.mock('../../utils/logger', () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
}));

// Mock toast store
vi.mock('../../stores/toastStore', () => ({
  showSuccess: vi.fn(),
  showWarning: vi.fn(),
}));

// Mock API clients
const mockLastfmApi = {
  scrobble: vi.fn(),
  updateNowPlaying: vi.fn(),
};
const mockFavoritesApi = {
  toggle: vi.fn(),
};

vi.mock('../../api/integrations', () => ({
  lastfmApi: mockLastfmApi,
}));

vi.mock('../../api/profiles', () => ({
  favoritesApi: mockFavoritesApi,
}));

vi.mock('../../stores/connectivityStore', () => ({
  useConnectivityStore: {
    getState: vi.fn(() => ({ browserOnline: true })),
  },
}));

// We need to import after mocks are set up
const getModule = async () => await import('../syncService');
const getDbModule = async () => await import('../../db');
const getProfileModule = async () => await import('../profileService');

describe('syncService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAdd.mockResolvedValue(1);
    mockDelete.mockResolvedValue(undefined);
    mockUpdate.mockResolvedValue(1);
    mockClear.mockResolvedValue(undefined);
    mockCount.mockResolvedValue(0);
    mockToArray.mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('queueAction', () => {
    it('should add an action to the pending actions table', async () => {
      const { queueAction } = await getModule();

      await queueAction('scrobble', { trackId: 'track-1', timestamp: '2024-01-01T00:00:00Z' });

      expect(mockAdd).toHaveBeenCalledWith(
        expect.objectContaining({
          profileId: 'profile-123',
          type: 'scrobble',
          payload: { trackId: 'track-1', timestamp: '2024-01-01T00:00:00Z' },
          retries: 0,
        })
      );
    });

    it('should set createdAt to current date', async () => {
      const { queueAction } = await getModule();

      await queueAction('now_playing', { trackId: 'track-1' });

      const addedAction = mockAdd.mock.calls[0][0];
      expect(addedAction.createdAt).toBeInstanceOf(Date);
    });

    it('should not queue when IndexedDB is unavailable', async () => {
      const dbModule = await getDbModule();
      vi.mocked(dbModule.isIndexedDBAvailable).mockResolvedValueOnce(false);

      const { queueAction } = await getModule();
      await queueAction('scrobble', { trackId: 'track-1' });

      expect(mockAdd).not.toHaveBeenCalled();
    });

    it('should not queue without a selected profile', async () => {
      const profileModule = await getProfileModule();
      vi.mocked(profileModule.getSelectedProfileId).mockResolvedValueOnce(null);

      const { queueAction } = await getModule();
      await queueAction('scrobble', { trackId: 'track-1' });

      expect(mockAdd).not.toHaveBeenCalled();
    });

    it('should silently handle db errors on add', async () => {
      mockAdd.mockRejectedValueOnce(new Error('IDB error'));

      const { queueAction } = await getModule();
      // Should not throw
      await queueAction('favorite_toggle', { trackId: 'track-1' });
    });

    it('should queue different action types', async () => {
      const { queueAction } = await getModule();

      await queueAction('favorite_toggle', { trackId: 'track-1' });
      expect(mockAdd).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'favorite_toggle' })
      );

    });
  });

  describe('getPendingCount', () => {
    it('should return count from db', async () => {
      mockCount.mockResolvedValueOnce(5);

      const { getPendingCount } = await getModule();
      const count = await getPendingCount();

      expect(count).toBe(5);
    });

    it('should return 0 when IndexedDB is unavailable', async () => {
      const dbModule = await getDbModule();
      vi.mocked(dbModule.isIndexedDBAvailable).mockResolvedValueOnce(false);

      const { getPendingCount } = await getModule();
      const count = await getPendingCount();

      expect(count).toBe(0);
    });

    it('should return 0 on db error', async () => {
      mockCount.mockRejectedValueOnce(new Error('IDB error'));

      const { getPendingCount } = await getModule();
      const count = await getPendingCount();

      expect(count).toBe(0);
    });
  });

  describe('getPendingActions', () => {
    it('should return actions ordered by createdAt', async () => {
      const actions = [
        { id: 1, profileId: 'p1', type: 'scrobble', payload: {}, createdAt: new Date(), retries: 0 },
        { id: 2, profileId: 'p1', type: 'now_playing', payload: {}, createdAt: new Date(), retries: 0 },
      ];
      mockToArray.mockResolvedValueOnce(actions);

      const { getPendingActions } = await getModule();
      const result = await getPendingActions();

      expect(mockOrderBy).toHaveBeenCalledWith('createdAt');
      expect(result).toHaveLength(2);
    });

    it('should return empty array when IndexedDB is unavailable', async () => {
      const dbModule = await getDbModule();
      vi.mocked(dbModule.isIndexedDBAvailable).mockResolvedValueOnce(false);

      const { getPendingActions } = await getModule();
      const result = await getPendingActions();

      expect(result).toEqual([]);
    });
  });

  describe('processPendingActions', () => {
    it('should process and delete successful actions', async () => {
      const actions = [
        { id: 1, profileId: 'profile-123', type: 'scrobble' as const, payload: { trackId: 'track-1', timestamp: '2024-01-01T00:00:00Z' }, createdAt: new Date(), retries: 0 },
      ];
      mockToArray.mockResolvedValueOnce(actions);

      mockLastfmApi.scrobble.mockResolvedValueOnce({ status: 'ok', message: 'Scrobbled' });

      const { processPendingActions } = await getModule();
      const result = await processPendingActions();

      expect(result.processed).toBe(1);
      expect(result.failed).toBe(0);
      expect(mockDelete).toHaveBeenCalledWith(1);
    });

    it('should increment retry count on failure', async () => {
      const actions = [
        { id: 1, profileId: 'profile-123', type: 'scrobble' as const, payload: { trackId: 'track-1', timestamp: '2024-01-01T00:00:00Z' }, createdAt: new Date(), retries: 0 },
      ];
      mockToArray.mockResolvedValueOnce(actions);

      mockLastfmApi.scrobble.mockRejectedValueOnce(new Error('Server Error'));

      const { processPendingActions } = await getModule();
      await processPendingActions();

      expect(mockUpdate).toHaveBeenCalledWith(1, { retries: 1 });
    });

    it('should remove action after 3 retries', async () => {
      const actions = [
        { id: 1, profileId: 'profile-123', type: 'scrobble' as const, payload: { trackId: 'track-1', timestamp: '2024-01-01T00:00:00Z' }, createdAt: new Date(), retries: 3 },
      ];
      mockToArray.mockResolvedValueOnce(actions);

      mockLastfmApi.scrobble.mockRejectedValueOnce(new Error('Server Error'));

      const { processPendingActions } = await getModule();
      const result = await processPendingActions();

      expect(result.failed).toBe(1);
      expect(mockDelete).toHaveBeenCalledWith(1);
    });

    it('should return zeros when IndexedDB is unavailable', async () => {
      const dbModule = await getDbModule();
      vi.mocked(dbModule.isIndexedDBAvailable).mockResolvedValueOnce(false);

      const { processPendingActions } = await getModule();
      const result = await processPendingActions();

      expect(result).toEqual({ processed: 0, failed: 0 });
    });

    it('should dispatch scrobble action via lastfmApi', async () => {
      const actions = [
        { id: 1, profileId: 'profile-123', type: 'scrobble' as const, payload: { trackId: 'track-1', timestamp: '2024-01-01T00:00:00Z' }, createdAt: new Date(), retries: 0 },
      ];
      mockToArray.mockResolvedValueOnce(actions);

      mockLastfmApi.scrobble.mockResolvedValueOnce({ status: 'ok', message: 'Scrobbled' });

      const { processPendingActions } = await getModule();
      await processPendingActions();

      expect(mockLastfmApi.scrobble).toHaveBeenCalledWith('track-1', expect.any(Number));
    });

    it('should dispatch now_playing action via lastfmApi', async () => {
      const actions = [
        { id: 1, profileId: 'profile-123', type: 'now_playing' as const, payload: { trackId: 'track-1' }, createdAt: new Date(), retries: 0 },
      ];
      mockToArray.mockResolvedValueOnce(actions);

      mockLastfmApi.updateNowPlaying.mockResolvedValueOnce({ status: 'ok', message: 'Updated' });

      const { processPendingActions } = await getModule();
      await processPendingActions();

      expect(mockLastfmApi.updateNowPlaying).toHaveBeenCalledWith('track-1');
    });

    it('should dispatch favorite_toggle action via favoritesApi', async () => {
      const actions = [
        { id: 1, profileId: 'profile-123', type: 'favorite_toggle' as const, payload: { trackId: 'track-1' }, createdAt: new Date(), retries: 0 },
      ];
      mockToArray.mockResolvedValueOnce(actions);

      mockFavoritesApi.toggle.mockResolvedValueOnce({ track_id: 'track-1', is_favorite: true });

      const { processPendingActions } = await getModule();
      await processPendingActions();

      expect(mockFavoritesApi.toggle).toHaveBeenCalledWith('track-1');
    });
  });

  describe('clearPendingActions', () => {
    it('should clear all pending actions', async () => {
      const { clearPendingActions } = await getModule();
      await clearPendingActions();

      expect(mockClear).toHaveBeenCalled();
    });

    it('should skip when IndexedDB is unavailable', async () => {
      const dbModule = await getDbModule();
      vi.mocked(dbModule.isIndexedDBAvailable).mockResolvedValueOnce(false);

      const { clearPendingActions } = await getModule();
      await clearPendingActions();

      expect(mockClear).not.toHaveBeenCalled();
    });
  });

  describe('initSyncListeners', () => {
    it('should process pending actions when already online', async () => {
      Object.defineProperty(navigator, 'onLine', { value: true, writable: true, configurable: true });
      mockToArray.mockResolvedValue([]);

      const { initSyncListeners } = await getModule();
      const cleanup = initSyncListeners();

      // Give the async call time to run
      await vi.waitFor(() => {
        expect(mockOrderBy).toHaveBeenCalled();
      });

      cleanup();
    });

    it('should return a cleanup function that removes event listener', async () => {
      const removeEventListenerSpy = vi.spyOn(window, 'removeEventListener');

      const { initSyncListeners } = await getModule();
      const cleanup = initSyncListeners();

      cleanup();

      expect(removeEventListenerSpy).toHaveBeenCalledWith('online', expect.any(Function));
      removeEventListenerSpy.mockRestore();
    });
  });
});
