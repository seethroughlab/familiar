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
// Backs the coalescing lookup: db.pendingActions.where('profileId').equals(id).filter(fn).first()
const mockCoalesceFirst = vi.fn();

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
      where: (_key: any) => ({
        equals: (_value: any) => ({
          filter: (_predicate: any) => ({ first: () => mockCoalesceFirst() }),
        }),
      }),
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

const mockPlayTrackingApi = {
  recordPlay: vi.fn(),
  recordSkip: vi.fn(),
  recordRejection: vi.fn(),
};

vi.mock('../../api/integrations', () => ({
  lastfmApi: mockLastfmApi,
}));

vi.mock('../../api/profiles', () => ({
  favoritesApi: mockFavoritesApi,
  playTrackingApi: mockPlayTrackingApi,
}));

const mockQueueApi = {
  putSession: vi.fn(),
};

vi.mock('../../api/queue', () => ({
  queueApi: mockQueueApi,
}));

const mockConnectivityState = { browserOnline: true, offlineModeActive: false };
type ConnectivityListener = (state: { offlineModeActive: boolean }) => void;
const mockSubscribe = vi.fn((_listener: ConnectivityListener) => () => {});

vi.mock('../../stores/connectivityStore', () => ({
  useConnectivityStore: {
    getState: vi.fn(() => mockConnectivityState),
    subscribe: (listener: ConnectivityListener) => mockSubscribe(listener),
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
    mockCoalesceFirst.mockResolvedValue(undefined);
    mockQueueApi.putSession.mockResolvedValue({ version: 1, superseded: false });
    mockConnectivityState.offlineModeActive = false;
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

      expect(mockLastfmApi.scrobble).toHaveBeenCalledWith('track-1', expect.any(Number), { headers: { 'X-Profile-ID': 'profile-123' } });
    });

    it('should dispatch now_playing action via lastfmApi', async () => {
      const actions = [
        { id: 1, profileId: 'profile-123', type: 'now_playing' as const, payload: { trackId: 'track-1' }, createdAt: new Date(), retries: 0 },
      ];
      mockToArray.mockResolvedValueOnce(actions);

      mockLastfmApi.updateNowPlaying.mockResolvedValueOnce({ status: 'ok', message: 'Updated' });

      const { processPendingActions } = await getModule();
      await processPendingActions();

      expect(mockLastfmApi.updateNowPlaying).toHaveBeenCalledWith('track-1', { headers: { 'X-Profile-ID': 'profile-123' } });
    });

    it('should dispatch favorite_toggle action via favoritesApi', async () => {
      const actions = [
        { id: 1, profileId: 'profile-123', type: 'favorite_toggle' as const, payload: { trackId: 'track-1' }, createdAt: new Date(), retries: 0 },
      ];
      mockToArray.mockResolvedValueOnce(actions);

      mockFavoritesApi.toggle.mockResolvedValueOnce({ track_id: 'track-1', is_favorite: true });

      const { processPendingActions } = await getModule();
      await processPendingActions();

      expect(mockFavoritesApi.toggle).toHaveBeenCalledWith('track-1', { headers: { 'X-Profile-ID': 'profile-123' } });
    });

    it('should dispatch a queued listen_event skip via playTrackingApi', async () => {
      const actions = [
        { id: 1, profileId: 'profile-123', type: 'listen_event' as const, payload: {
          trackId: 'track-1', kind: 'skipped',
          body: { played_seconds: 5, track_duration: 200, reason: 'user', context: 'playlist' },
        }, createdAt: new Date(), retries: 0 },
      ];
      mockToArray.mockResolvedValueOnce(actions);
      mockPlayTrackingApi.recordSkip.mockResolvedValueOnce({ track_id: 'track-1', outcome: 'skipped', completion_ratio: 0.025 });

      const { processPendingActions } = await getModule();
      await processPendingActions();

      expect(mockPlayTrackingApi.recordSkip).toHaveBeenCalledWith(
        'track-1',
        expect.objectContaining({ reason: 'user', played_seconds: 5 }),
        { headers: { 'X-Profile-ID': 'profile-123' } },
      );
      expect(mockPlayTrackingApi.recordPlay).not.toHaveBeenCalled();
    });

    it('should dispatch a queued listen_event rejection via playTrackingApi', async () => {
      const actions = [
        { id: 1, profileId: 'profile-123', type: 'listen_event' as const, payload: {
          trackId: 'track-2', kind: 'rejected', body: { context: 'radio' },
        }, createdAt: new Date(), retries: 0 },
      ];
      mockToArray.mockResolvedValueOnce(actions);
      mockPlayTrackingApi.recordRejection.mockResolvedValueOnce({ track_id: 'track-2', outcome: 'rejected', completion_ratio: 0 });

      const { processPendingActions } = await getModule();
      await processPendingActions();

      expect(mockPlayTrackingApi.recordRejection).toHaveBeenCalledWith('track-2', expect.objectContaining({ context: 'radio' }), { headers: { 'X-Profile-ID': 'profile-123' } });
    });
  });

  describe('deliverListenEvent', () => {
    it('sends directly when online', async () => {
      mockPlayTrackingApi.recordSkip.mockResolvedValueOnce({ track_id: 't', outcome: 'skipped', completion_ratio: 0 });

      const { deliverListenEvent } = await getModule();
      await deliverListenEvent('t', 'skipped', { played_seconds: 3 });

      expect(mockPlayTrackingApi.recordSkip).toHaveBeenCalled();
      expect(mockAdd).not.toHaveBeenCalled();
    });

    it('queues without attempting the request when already offline', async () => {
      mockConnectivityState.offlineModeActive = true;

      const { deliverListenEvent } = await getModule();
      await deliverListenEvent('t', 'skipped', { played_seconds: 3 });

      expect(mockPlayTrackingApi.recordSkip).not.toHaveBeenCalled();
      expect(mockAdd).toHaveBeenCalledWith(expect.objectContaining({ type: 'listen_event' }));
    });

    it('queues when an online request fails, rather than losing the event', async () => {
      // The case no existing producer handles: useFavorites only pre-checks isOffline,
      // so a 500 or a mid-flight drop would silently discard the data.
      mockPlayTrackingApi.recordSkip.mockRejectedValueOnce(new Error('500'));

      const { deliverListenEvent } = await getModule();
      await deliverListenEvent('t', 'skipped', { played_seconds: 3 });

      expect(mockPlayTrackingApi.recordSkip).toHaveBeenCalled();
      expect(mockAdd).toHaveBeenCalledWith(expect.objectContaining({ type: 'listen_event' }));
    });

    it('never throws, so a failed event cannot disturb playback', async () => {
      mockPlayTrackingApi.recordSkip.mockRejectedValueOnce(new Error('boom'));
      mockAdd.mockRejectedValueOnce(new Error('indexeddb gone'));

      const { deliverListenEvent } = await getModule();
      await expect(deliverListenEvent('t', 'skipped')).resolves.toBeUndefined();
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

    it('also drains on the connectivity store recovering', async () => {
      // The probe-driven forcedOffline -> reachable transition emits no browser 'online'
      // event, so without this subscription that recovery was only covered incidentally
      // by an effect in a mounted UI component.
      const { initSyncListeners } = await getModule();
      initSyncListeners();

      expect(mockSubscribe).toHaveBeenCalledWith(expect.any(Function));

      const listener = mockSubscribe.mock.calls[0][0];
      mockToArray.mockResolvedValue([
        { id: 1, profileId: 'profile-123', type: 'favorite_toggle', payload: { trackId: 't1' }, retries: 0 },
      ]);

      // Offline, then back: only the falling edge should drain.
      listener({ offlineModeActive: true });
      expect(mockFavoritesApi.toggle).not.toHaveBeenCalled();

      listener({ offlineModeActive: false });
      await vi.waitFor(() => expect(mockFavoritesApi.toggle).toHaveBeenCalled());
    });
  });

  describe('queue_sync — state, not events', () => {
    it('replaces an existing row for the profile instead of appending', async () => {
      // A queue is state: appending one row per mutation would replay hundreds of stale
      // queues on reconnect, all but the last of them pointless.
      mockCoalesceFirst.mockResolvedValue({ id: 7, profileId: 'profile-123', type: 'queue_sync' });
      const { queueAction } = await getModule();

      await queueAction('queue_sync', { track_ids: ['a'], version: 3 });

      expect(mockAdd).not.toHaveBeenCalled();
      expect(mockUpdate).toHaveBeenCalledWith(
        7,
        expect.objectContaining({ payload: { track_ids: ['a'], version: 3 }, retries: 0 }),
      );
    });

    it('adds a row when the profile has none yet', async () => {
      mockCoalesceFirst.mockResolvedValue(undefined);
      const { queueAction } = await getModule();

      await queueAction('queue_sync', { track_ids: ['a'] });

      expect(mockAdd).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'queue_sync', profileId: 'profile-123' }),
      );
    });

    it('still appends event-shaped actions', async () => {
      // Coalescing must not leak to scrobbles and listening events, each of which is a
      // distinct thing that happened.
      mockCoalesceFirst.mockResolvedValue({ id: 7, type: 'scrobble' });
      const { queueAction } = await getModule();

      await queueAction('scrobble', { trackId: 't1', timestamp: '123' });

      expect(mockAdd).toHaveBeenCalled();
      expect(mockUpdate).not.toHaveBeenCalled();
    });

    it('is never dropped for exceeding the retry limit', async () => {
      // Dropping a scrobble loses a scrobble. Dropping this leaves the server on a state
      // no device ever held, which ADR-0003 point 6 rules out.
      mockToArray.mockResolvedValue([
        { id: 1, profileId: 'profile-123', type: 'queue_sync', payload: {}, retries: 5 },
      ]);
      mockQueueApi.putSession.mockRejectedValue(new Error('boom'));
      const { processPendingActions } = await getModule();

      const result = await processPendingActions();

      expect(mockDelete).not.toHaveBeenCalled();
      expect(result.failed).toBe(0);
      expect(mockUpdate).toHaveBeenCalledWith(1, { retries: 6 });
    });

    it('treats a rejected reservoir hash as handled rather than retryable', async () => {
      // A 409 means the omitted reservoir cannot be filled in. Retrying the same payload
      // would fail identically; the caller has to resend it in full.
      mockToArray.mockResolvedValue([
        { id: 1, profileId: 'profile-123', type: 'queue_sync', payload: {}, retries: 0 },
      ]);
      mockQueueApi.putSession.mockRejectedValue({ response: { status: 409 } });
      const { processPendingActions } = await getModule();

      const result = await processPendingActions();

      expect(result.processed).toBe(1);
      expect(mockDelete).toHaveBeenCalledWith(1);
    });
  });

  describe('replaying against the right profile', () => {
    it('pins each action to the profile that queued it', async () => {
      // The X-Profile-ID interceptor uses whichever profile is selected *now*, so before
      // this an action queued under one profile replayed against another.
      mockToArray.mockResolvedValue([
        { id: 1, profileId: 'profile-abc', type: 'favorite_toggle', payload: { trackId: 't1' }, retries: 0 },
      ]);
      const { processPendingActions } = await getModule();

      await processPendingActions();

      expect(mockFavoritesApi.toggle).toHaveBeenCalledWith('t1', {
        headers: { 'X-Profile-ID': 'profile-abc' },
      });
    });

    it('pins a queue sync to the profile that queued it', async () => {
      // The most important case: a queue delivered to the wrong profile would overwrite
      // that profile's own queue.
      mockToArray.mockResolvedValue([
        { id: 1, profileId: 'profile-abc', type: 'queue_sync', payload: { track_ids: ['a'] }, retries: 0 },
      ]);
      const { processPendingActions } = await getModule();

      await processPendingActions();

      expect(mockQueueApi.putSession).toHaveBeenCalledWith(
        { track_ids: ['a'] },
        { headers: { 'X-Profile-ID': 'profile-abc' } },
      );
    });
  });

  describe('concurrent drains', () => {
    it('runs a single drain when triggered twice at once', async () => {
      // The 'online' handler, the connectivity subscription and OfflineIndicator's effect
      // can all fire together; without a guard each action is delivered more than once.
      mockToArray.mockResolvedValue([
        { id: 1, profileId: 'profile-123', type: 'favorite_toggle', payload: { trackId: 't1' }, retries: 0 },
      ]);
      // Deferred up front: the mock is only reached after several awaits, so capturing
      // `resolve` from inside the executor would still be unset when we call it.
      let resolveToggle: () => void = () => {};
      const inFlightToggle = new Promise<void>((resolve) => {
        resolveToggle = resolve;
      });
      mockFavoritesApi.toggle.mockImplementation(() => inFlightToggle);
      const { processPendingActions } = await getModule();

      const first = processPendingActions();
      const second = processPendingActions();
      await vi.waitFor(() => expect(mockFavoritesApi.toggle).toHaveBeenCalled());
      resolveToggle();
      await Promise.all([first, second]);

      expect(mockFavoritesApi.toggle).toHaveBeenCalledTimes(1);
    });
  });
});
