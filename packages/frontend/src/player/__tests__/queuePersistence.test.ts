/**
 * Tests for what survives a page reload.
 *
 * `savePlayerState` wrote twelve fields, and neither `queueSource` nor the lazy
 * reservoir (`lazyQueueIds` / `lazyQueueIndex`) was among them. `hydrate()` restored
 * neither. The consequences are not cosmetic:
 *
 * - **Playback silently stops after 50 tracks.** `setLazyQueue` keeps the full ID list
 *   in `lazyQueueIds` and materialises only the first `WINDOW_SIZE = 50` into `queue`.
 *   After a reload `lazyQueueIds` is back to its `null` default, so
 *   `refillFromReservoir` returns immediately and the queue never grows again. The user
 *   sees playback end mid-library with no error.
 * - **Shuffle quietly stops using the server.** `toggleShuffle`'s lazy branch requires
 *   both `lazyQueueIds` and `queueSource?.type === 'library'`. With both gone it falls
 *   through to the standard branch and permutes only the 50 loaded tracks, bypassing the
 *   server-side weighted preset entirely.
 * - **Listening events lose their context**, which is what the issue was filed about and
 *   what ADR-0005 needs.
 *
 * The first of those is the one a user would report, so it gets the most direct test.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { createMockTrack, mockConnectivityState } from './testHelpers';

// `vi.hoisted`, not plain consts. `vi.mock` is hoisted above const declarations, and a
// factory that *dereferences* an outer const at factory-call time (as `loadPlayerState:
// mockLoadPlayerState` does) hits the temporal dead zone. Vitest swallows that and falls
// back to the real module, so the mocks appear to do nothing and every test fails for a
// reason unrelated to what it is testing.
const { mockLoadPlayerState, mockSave } = vi.hoisted(() => ({
  mockLoadPlayerState: vi.fn(() => Promise.resolve(null as unknown)),
  mockSave: vi.fn(),
}));

vi.mock('../persistence', () => ({
  debouncedSavePlayerState: mockSave,
  loadPlayerState: mockLoadPlayerState,
  fetchTracksBatched: (ids: string[]) =>
    Promise.resolve(ids.map((id) => ({
      id,
      title: `Track ${id}`,
      artist: 'Test Artist',
      album: 'Test Album',
      duration_seconds: 180,
      file_path: `/music/${id}.mp3`,
    }))),
  migrateOldPlayerState: vi.fn(() => Promise.resolve()),
}));

vi.mock('../audio/engineInstance', () => ({
  getEngine: () => ({ seek: vi.fn(), cancelCrossfade: vi.fn() }),
}));

vi.mock('../../stores/connectivityStore', () => ({
  useConnectivityStore: Object.assign(
    (selector: (state: typeof mockConnectivityState) => unknown) => selector(mockConnectivityState),
    { getState: () => mockConnectivityState }
  ),
}));

const { mockGetBatch, mockGetIds } = vi.hoisted(() => ({
  mockGetBatch: vi.fn(),
  mockGetIds: vi.fn(),
}));

vi.mock('../../api', () => ({
  tracksApi: {
    getBatch: (ids: string[]) => mockGetBatch(ids),
    getIds: (params: unknown) => mockGetIds(params as never),
  },
}));

import { useQueueStore } from '../queueStore';
import { usePlaybackStore } from '../playbackStore';

const ids = (n: number, prefix = 't') =>
  Array.from({ length: n }, (_, i) => `${prefix}${i}`);

/** A persisted record as it would exist after playing the library. */
function persistedLazyQueue(total = 200, window = 50) {
  const all = ids(total);
  return {
    id: 'profile-1',
    volume: 1,
    shuffle: false,
    repeat: 'off' as const,
    consume: false,
    queueTrackIds: all.slice(0, window),
    queueIndex: 0,
    currentTrackId: all[0],
    shuffleOrder: [],
    shuffleIndex: -1,
    currentTime: 0,
    queueSource: { type: 'library' as const, filters: { genre: 'jazz' } },
    lazyQueueIds: all,
    lazyQueueIndex: window,
    updatedAt: new Date(),
  };
}

function resetStores() {
  usePlaybackStore.setState({
    currentTrack: null,
    isPlaying: false,
    currentTime: 0,
    duration: 0,
    volume: 1,
    shuffle: false,
    repeat: 'off',
    consume: false,
    crossfadeState: 'idle',
    nextTrackPreloaded: false,
    isLoadingAudio: false,
    isHydrated: false,
    _circuitBreakerTimestamps: [],
  });
  useQueueStore.setState({
    queue: [],
    queueIndex: -1,
    history: [],
    shuffleOrder: [],
    shuffleIndex: -1,
    lazyQueueIds: null,
    lazyQueueIndex: -1,
    queueSource: null,
    isQueueHydrating: false,
  });
  mockConnectivityState.offlineModeActive = false;
  mockConnectivityState.offlineTrackIds = new Set<string>();
}

beforeEach(() => {
  resetStores();
  mockSave.mockClear();
  mockGetBatch.mockReset();
  mockGetBatch.mockImplementation((batchIds: string[]) =>
    Promise.resolve(batchIds.map((id) => createMockTrack(id)))
  );
  mockGetIds.mockReset();
  mockGetIds.mockResolvedValue({ ids: [] });
  mockLoadPlayerState.mockResolvedValue(null);
});

describe('saving', () => {
  it('writes queueSource so listening events keep their context', async () => {
    const source = { type: 'playlist' as const, id: 'p1' };
    useQueueStore.getState().setQueue([createMockTrack('a')], 0, source);

    expect(mockSave).toHaveBeenCalled();
    expect(mockSave.mock.calls.at(-1)![0]).toMatchObject({ queueSource: source });
  });

  it('writes the lazy reservoir', async () => {
    await useQueueStore.getState().setLazyQueue(ids(200), { type: 'library' });

    const saved = mockSave.mock.calls.at(-1)![0];
    expect(saved.lazyQueueIds).toHaveLength(200);
    expect(saved.lazyQueueIndex).toBe(50);
  });

  it('writes the advanced reservoir index after a refill', async () => {
    await useQueueStore.getState().setLazyQueue(ids(200), { type: 'library' });
    // Sit near the end of the loaded window so a refill is due.
    useQueueStore.setState({ queueIndex: 45 });
    mockSave.mockClear();

    await useQueueStore.getState().playNext();
    await vi.waitFor(() => expect(mockSave).toHaveBeenCalled());

    const saved = mockSave.mock.calls.at(-1)![0];
    expect(saved.lazyQueueIndex).toBeGreaterThan(50);
  });
});

describe('hydrating', () => {
  it('restores queueSource', async () => {
    mockLoadPlayerState.mockResolvedValue(persistedLazyQueue());

    await useQueueStore.getState().hydrate();

    expect(useQueueStore.getState().queueSource).toEqual({
      type: 'library',
      filters: { genre: 'jazz' },
    });
  });

  it('restores the full reservoir, not just the loaded window', async () => {
    mockLoadPlayerState.mockResolvedValue(persistedLazyQueue(200, 50));

    await useQueueStore.getState().hydrate();

    const s = useQueueStore.getState();
    expect(s.queue).toHaveLength(50);
    expect(s.lazyQueueIds).toHaveLength(200);
    expect(s.lazyQueueIndex).toBe(50);
  });

  it('keeps playing past the 50-track window after a reload', async () => {
    // The bug a user would actually report: playback just ends mid-library.
    mockLoadPlayerState.mockResolvedValue(persistedLazyQueue(200, 50));
    await useQueueStore.getState().hydrate();

    // Advance to the end of the loaded window, which should trigger a refill.
    useQueueStore.setState({ queueIndex: 45 });
    await useQueueStore.getState().playNext();

    await vi.waitFor(() => {
      expect(useQueueStore.getState().queue.length).toBeGreaterThan(50);
    });
  });

  it('takes the server-side lazy branch on toggleShuffle after a reload', async () => {
    mockLoadPlayerState.mockResolvedValue(persistedLazyQueue(200, 50));
    mockGetIds.mockResolvedValue({ ids: ids(200).reverse() });
    await useQueueStore.getState().hydrate();

    await useQueueStore.getState().toggleShuffle();

    expect(mockGetIds).toHaveBeenCalled();
    // The library filters have to survive too, or the reshuffle spans the wrong set.
    expect(mockGetIds.mock.calls[0][0]).toMatchObject({ genre: 'jazz' });
  });
});

describe('hydrating defensively', () => {
  it('reads a record saved before these fields existed', async () => {
    const legacy = persistedLazyQueue();
    delete (legacy as Record<string, unknown>).queueSource;
    delete (legacy as Record<string, unknown>).lazyQueueIds;
    delete (legacy as Record<string, unknown>).lazyQueueIndex;
    mockLoadPlayerState.mockResolvedValue(legacy);

    await useQueueStore.getState().hydrate();

    const s = useQueueStore.getState();
    expect(s.lazyQueueIds).toBeNull();
    expect(s.lazyQueueIndex).toBe(-1);
    expect(s.queueSource).toBeNull();
    expect(s.queue).toHaveLength(50); // still hydrates the queue itself
  });

  it('ignores a reservoir index past the end of the list', async () => {
    mockLoadPlayerState.mockResolvedValue({
      ...persistedLazyQueue(200, 50),
      lazyQueueIndex: 9999,
    });

    await useQueueStore.getState().hydrate();

    // Falling back to non-lazy mode is correct: an index past the end can only
    // produce an empty refill batch forever.
    expect(useQueueStore.getState().lazyQueueIds).toBeNull();
  });

  it('ignores an empty reservoir', async () => {
    mockLoadPlayerState.mockResolvedValue({
      ...persistedLazyQueue(200, 50),
      lazyQueueIds: [],
    });

    await useQueueStore.getState().hydrate();

    expect(useQueueStore.getState().lazyQueueIds).toBeNull();
  });

  it('does not enter lazy mode from a non-lazy record', async () => {
    const plain = persistedLazyQueue();
    delete (plain as Record<string, unknown>).lazyQueueIds;
    plain.queueSource = { type: 'playlist', id: 'p1' } as never;
    mockLoadPlayerState.mockResolvedValue(plain);

    await useQueueStore.getState().hydrate();

    const s = useQueueStore.getState();
    expect(s.lazyQueueIds).toBeNull();
    expect(s.queueSource).toEqual({ type: 'playlist', id: 'p1' });
  });
});
