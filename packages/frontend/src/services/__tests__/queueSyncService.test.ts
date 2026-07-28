/**
 * Tests for mirroring the playback queue to the server (ADR-0003 phase 3).
 *
 * Three behaviours here are the ones that would cause real damage if they regressed, and
 * none of them would be obvious from watching the app:
 *
 * - **Position ticks must not become requests.** `setCurrentTime` fires every ~16ms and
 *   persists on a 500ms throttle. Syncing off that cadence would mean a request twice a
 *   second for the whole of playback, which is why this service watches a structural
 *   signature rather than hooking the persistence funnel.
 *
 * - **The reservoir is sent once, then referenced by hash.** It is ~1 MB for a full
 *   library. Resending it on every cursor advance is the thing the hash exists to avoid.
 *
 * - **The offline-narrowed queue must never be uploaded.** While offline the store's
 *   queue is filtered to downloaded tracks; sending that would overwrite every other
 *   device's copy with whatever this one happened to have. This is the worst thing the
 *   service could do, so it is asserted directly.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createMockTrack, mockConnectivityState } from '../../player/__tests__/testHelpers';

const { mockQueueAction, mockRegisterHandlers, mockProcessPending } = vi.hoisted(() => ({
  // Typed args, or `vi.fn(() => ...)` infers an empty parameter tuple and every
  // `mock.calls[0][0]` below becomes a type error.
  mockQueueAction: vi.fn((_type: string, _payload: unknown) => Promise.resolve()),
  mockRegisterHandlers: vi.fn(),
  mockProcessPending: vi.fn(() => Promise.resolve({ processed: 0, failed: 0 })),
}));

vi.mock('../syncService', () => ({
  queueAction: mockQueueAction,
  registerQueueSyncHandlers: mockRegisterHandlers,
  processPendingActions: mockProcessPending,
}));

const { mockGetSession } = vi.hoisted(() => ({ mockGetSession: vi.fn() }));

vi.mock('../../api/queue', () => ({
  queueApi: { getSession: mockGetSession, putSession: vi.fn() },
}));

vi.mock('../profileService', () => ({
  getSelectedProfileId: () => Promise.resolve('profile-1'),
}));

vi.mock('../../player/persistence', () => ({
  debouncedSavePlayerState: vi.fn(),
  loadPlayerState: vi.fn(() => Promise.resolve(null)),
  migrateOldPlayerState: vi.fn(() => Promise.resolve()),
  fetchTracksBatched: (ids: string[]) => Promise.resolve(ids.map((id) => createMockTrack(id))),
}));

vi.mock('../../stores/connectivityStore', () => ({
  useConnectivityStore: Object.assign(
    (selector: (s: typeof mockConnectivityState) => unknown) => selector(mockConnectivityState),
    { getState: () => mockConnectivityState },
  ),
}));

vi.mock('../../api', () => ({ tracksApi: { getBatch: vi.fn(), getIds: vi.fn() } }));

vi.mock('../../player/audio/engineInstance', () => ({
  getEngine: () => ({ seek: vi.fn(), cancelCrossfade: vi.fn() }),
}));

import { useQueueStore } from '../../player/queueStore';
import { usePlaybackStore } from '../../player/playbackStore';
import { initQueueSync, _resetQueueSyncState, isQueueSyncEnabled } from '../queueSyncService';

const DEBOUNCE_MS = 2_000;

/** The payload of the most recent queue_sync enqueue. */
function lastPayload() {
  const calls = mockQueueAction.mock.calls.filter((c) => c[0] === 'queue_sync');
  return calls.at(-1)?.[1] as Record<string, unknown> | undefined;
}

function seedQueue(ids: string[], reservoir?: string[]) {
  useQueueStore.setState({
    queue: ids.map((id, i) => ({ track: createMockTrack(id), queueId: `q${i}` })),
    queueIndex: 0,
    queueSource: { type: 'library' },
    lazyQueueIds: reservoir ?? null,
    lazyQueueIndex: reservoir ? 50 : -1,
    logicalTrackIds: null,
    logicalIndex: -1,
  });
  usePlaybackStore.setState({ currentTrack: createMockTrack(ids[0]), currentTime: 0 });
}

let stop: () => void = () => {};

beforeEach(() => {
  vi.useFakeTimers();
  _resetQueueSyncState();
  mockQueueAction.mockClear();
  mockProcessPending.mockClear();
  mockGetSession.mockReset();
  localStorage.setItem('familiar:queueSync', '1');
  mockConnectivityState.offlineModeActive = false;
  useQueueStore.setState({
    queue: [], queueIndex: -1, history: [], shuffleOrder: [], shuffleIndex: -1,
    lazyQueueIds: null, lazyQueueIndex: -1, queueSource: null, isQueueHydrating: false,
    logicalTrackIds: null, logicalIndex: -1,
  });
  usePlaybackStore.setState({
    currentTrack: null, isPlaying: false, currentTime: 0, shuffle: false,
    repeat: 'off', consume: false,
  });
});

afterEach(() => {
  stop();
  stop = () => {};
  vi.useRealTimers();
  localStorage.removeItem('familiar:queueSync');
});

describe('the flag', () => {
  it('is off unless explicitly set', () => {
    localStorage.removeItem('familiar:queueSync');
    expect(isQueueSyncEnabled()).toBe(false);
  });

  it('makes initQueueSync a no-op when off', () => {
    localStorage.removeItem('familiar:queueSync');
    stop = initQueueSync();

    seedQueue(['a', 'b']);
    vi.advanceTimersByTime(DEBOUNCE_MS * 2);

    expect(mockQueueAction).not.toHaveBeenCalled();
    expect(mockRegisterHandlers).not.toHaveBeenCalled();
  });
});

describe('what triggers a sync', () => {
  it('syncs after a structural change settles', async () => {
    stop = initQueueSync();
    seedQueue(['a', 'b', 'c']);

    // Debounced: nothing yet.
    expect(mockQueueAction).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(lastPayload()?.track_ids).toEqual(['a', 'b', 'c']);
  });

  it('coalesces a burst of changes into one sync', async () => {
    stop = initQueueSync();
    seedQueue(['a', 'b', 'c']);

    // What a drag-reorder looks like: many mutations in quick succession.
    for (let i = 0; i < 5; i++) {
      useQueueStore.setState({ queueIndex: i });
      await vi.advanceTimersByTimeAsync(100);
    }
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);

    const syncs = mockQueueAction.mock.calls.filter((c) => c[0] === 'queue_sync');
    expect(syncs).toHaveLength(1);
  });

  it('does not sync for position ticks alone', async () => {
    stop = initQueueSync();
    seedQueue(['a', 'b']);
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    mockQueueAction.mockClear();

    // 60 seconds of playback at the persistence layer's 500ms cadence.
    for (let t = 1; t <= 120; t++) {
      usePlaybackStore.setState({ currentTime: t * 0.5 });
      await vi.advanceTimersByTimeAsync(500);
    }

    // Only the slow position timer may have fired, and only because isPlaying is false
    // here it should not have fired at all.
    expect(mockQueueAction.mock.calls.filter((c) => c[0] === 'queue_sync')).toHaveLength(0);
  });

  it('treats shuffle and repeat as structural even though they live in playbackStore', async () => {
    stop = initQueueSync();
    seedQueue(['a', 'b']);
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    mockQueueAction.mockClear();

    usePlaybackStore.setState({ repeat: 'all' });
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);

    expect(lastPayload()?.repeat).toBe('all');
  });
});

describe('the reservoir', () => {
  it('is sent the first time and omitted thereafter', async () => {
    const reservoir = Array.from({ length: 200 }, (_, i) => `r${i}`);
    stop = initQueueSync();
    seedQueue(['a', 'b'], reservoir);
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);

    expect(lastPayload()?.reservoir_ids).toEqual(reservoir);

    // Advance the cursor without touching the reservoir — the ~1 MB must not go again.
    useQueueStore.setState({ queueIndex: 1 });
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);

    expect(lastPayload()?.reservoir_ids).toBeUndefined();
  });

  it('is sent again when it is actually replaced', async () => {
    stop = initQueueSync();
    seedQueue(['a', 'b'], ['r1', 'r2']);
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);

    // toggleShuffle replaces the array wholesale, which is what the reference check sees.
    useQueueStore.setState({ lazyQueueIds: ['r9', 'r8'], lazyQueueIndex: 2 });
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);

    expect(lastPayload()?.reservoir_ids).toEqual(['r9', 'r8']);
  });
});

describe('the logical queue', () => {
  it('sends the logical queue, never the offline-narrowed one', async () => {
    stop = initQueueSync();

    // Start already narrowed, so the very first sync is the one under test. Narrowing an
    // already-synced queue changes nothing structurally — the logical queue is the same
    // either way — so it correctly produces no second sync to inspect.
    useQueueStore.setState({
      queue: [{ track: createMockTrack('a'), queueId: 'q0' }],
      queueIndex: 0,
      queueSource: { type: 'library' },
      logicalTrackIds: ['a', 'b', 'c'],
      logicalIndex: 2,
    });
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);

    // Uploading ['a'] here would overwrite every other device's queue with this
    // device's downloads.
    expect(lastPayload()?.track_ids).toEqual(['a', 'b', 'c']);
    // And the cursor has to be the one into the logical queue, not into the narrowed view.
    expect(lastPayload()?.cursor).toBe(2);
  });

  it('drops the shuffle order while narrowed, since it indexes the wrong queue', async () => {
    stop = initQueueSync();
    seedQueue(['a', 'b', 'c']);
    useQueueStore.setState({
      queue: [{ track: createMockTrack('a'), queueId: 'q0' }],
      queueIndex: 0,
      shuffleOrder: [2, 0, 1],
      shuffleIndex: 1,
      logicalTrackIds: ['a', 'b', 'c'],
      logicalIndex: 0,
    });
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);

    expect(lastPayload()?.shuffle_order).toEqual([]);
    expect(lastPayload()?.shuffle_index).toBe(-1);
  });
});

describe('offline behaviour', () => {
  it('still enqueues while offline, for delivery on reconnect', async () => {
    mockConnectivityState.offlineModeActive = true;
    stop = initQueueSync();
    seedQueue(['a', 'b']);
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);

    expect(mockQueueAction).toHaveBeenCalledWith('queue_sync', expect.anything());
    // But does not try to send it — the outbox replays on reconnect.
    expect(mockProcessPending).not.toHaveBeenCalled();
  });
});
