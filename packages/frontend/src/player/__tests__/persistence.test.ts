/**
 * Tests for the persistence layer's storage shape.
 *
 * The lazy reservoir is the one persisted field that is both large and rarely changing:
 * ~26k UUIDs (~1 MB) for a full library, changed only by `setLazyQueue`, `toggleShuffle`
 * and refills. But `setCurrentTime` persists on every tick, throttled to 500ms, so a
 * reservoir kept in the main record would be rewritten twice a second for the whole of
 * playback — ~2 MB/s of flash writes to save a value that did not change.
 *
 * It therefore lives in its own row, written only when it actually differs. These tests
 * pin that down, because it is invisible from the store's point of view: `loadPlayerState`
 * stitches the two rows back together, so nothing upstream can tell the difference except
 * by counting writes.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

/* eslint-disable @typescript-eslint/no-explicit-any */
const { mockPut, mockGet, mockDelete, mockBulkDelete } = vi.hoisted(() => ({
  mockPut: vi.fn(() => Promise.resolve()) as any,
  mockGet: vi.fn() as any,
  mockDelete: vi.fn(() => Promise.resolve()) as any,
  mockBulkDelete: vi.fn(() => Promise.resolve()) as any,
}));

vi.mock('../../db', () => ({
  db: {
    playerState: {
      put: mockPut,
      get: mockGet,
      delete: mockDelete,
      bulkDelete: mockBulkDelete,
    },
  },
  isIndexedDBAvailable: () => Promise.resolve(true),
}));

vi.mock('../../services/profileService', () => ({
  getSelectedProfileId: () => Promise.resolve('profile-1'),
}));

vi.mock('../../api', () => ({ tracksApi: { getBatch: vi.fn() } }));

import { savePlayerState, loadPlayerState, clearPlayerState } from '../persistence';

const RESERVOIR_KEY = 'profile-1::reservoir';

const baseState = {
  volume: 1,
  shuffle: false,
  repeat: 'off' as const,
  consume: false,
  queue: [],
  queueIndex: -1,
  currentTrack: null,
  shuffleOrder: [],
  shuffleIndex: -1,
  currentTime: 0,
};

const putFor = (id: string): Record<string, unknown>[] =>
  mockPut.mock.calls
    .map((c: unknown[]) => c[0] as Record<string, unknown>)
    .filter((r: Record<string, unknown>) => r.id === id);

beforeEach(() => {
  mockPut.mockClear();
  mockGet.mockReset();
  mockGet.mockResolvedValue(undefined);
  mockDelete.mockClear();
  mockBulkDelete.mockClear();
});

describe('reservoir storage', () => {
  it('writes the reservoir to its own row', async () => {
    const ids = ['a', 'b', 'c'];
    await savePlayerState({ ...baseState, lazyQueueIds: ids, lazyQueueIndex: 2 });

    const rows = putFor(RESERVOIR_KEY);
    expect(rows).toHaveLength(1);
    expect(rows[0].lazyQueueIds).toEqual(ids);
  });

  it('keeps the bulk out of the main record', async () => {
    const ids = ['a', 'b', 'c'];
    await savePlayerState({ ...baseState, lazyQueueIds: ids, lazyQueueIndex: 2 });

    const main = putFor('profile-1')[0];
    expect(main.lazyQueueIds).toBeUndefined();
    // The cursor is small and tracks the queue, so it stays with the main record.
    expect(main.lazyQueueIndex).toBe(2);
  });

  it('does not rewrite an unchanged reservoir', async () => {
    const ids = ['a', 'b', 'c'];
    await savePlayerState({ ...baseState, lazyQueueIds: ids, lazyQueueIndex: 2 });
    mockPut.mockClear();

    // What playback does twice a second: same queue, later position.
    for (let t = 1; t <= 5; t++) {
      await savePlayerState({ ...baseState, currentTime: t, lazyQueueIds: ids, lazyQueueIndex: 2 });
    }

    expect(putFor('profile-1')).toHaveLength(5);
    expect(putFor(RESERVOIR_KEY)).toHaveLength(0);
  });

  it('rewrites when the reservoir actually changes', async () => {
    await savePlayerState({ ...baseState, lazyQueueIds: ['a'], lazyQueueIndex: 1 });
    mockPut.mockClear();

    await savePlayerState({ ...baseState, lazyQueueIds: ['x', 'y'], lazyQueueIndex: 2 });

    expect(putFor(RESERVOIR_KEY)).toHaveLength(1);
  });

  it('deletes the row when lazy mode ends', async () => {
    await savePlayerState({ ...baseState, lazyQueueIds: ['a'], lazyQueueIndex: 1 });
    mockDelete.mockClear();

    await savePlayerState({ ...baseState, lazyQueueIds: null, lazyQueueIndex: -1 });

    expect(mockDelete).toHaveBeenCalledWith(RESERVOIR_KEY);
  });
});

describe('loading stitches the rows back together', () => {
  it('returns the reservoir alongside the main record', async () => {
    mockGet.mockImplementation((key: string) =>
      Promise.resolve(
        key === RESERVOIR_KEY
          ? { id: key, lazyQueueIds: ['a', 'b'], lazyQueueIndex: 2 }
          : { id: 'profile-1', queueTrackIds: [], lazyQueueIndex: 2 }
      )
    );

    const loaded = await loadPlayerState();

    expect(loaded?.lazyQueueIds).toEqual(['a', 'b']);
    expect(loaded?.lazyQueueIndex).toBe(2);
  });

  it('reads a record written before the reservoir row existed', async () => {
    mockGet.mockImplementation((key: string) =>
      Promise.resolve(key === RESERVOIR_KEY ? undefined : { id: 'profile-1', queueTrackIds: ['t1'] })
    );

    const loaded = await loadPlayerState();

    expect(loaded?.queueTrackIds).toEqual(['t1']);
    expect(loaded?.lazyQueueIds).toBeNull();
  });

  it('returns null when there is no state at all', async () => {
    mockGet.mockResolvedValue(undefined);
    expect(await loadPlayerState()).toBeNull();
  });
});

describe('clearing', () => {
  it('removes both rows, so the reservoir cannot outlive its state', async () => {
    await clearPlayerState();
    expect(mockBulkDelete).toHaveBeenCalledWith(['profile-1', RESERVOIR_KEY]);
  });

  it('lets a later save rewrite the reservoir it had already written', async () => {
    const ids = ['a', 'b'];
    await savePlayerState({ ...baseState, lazyQueueIds: ids, lazyQueueIndex: 2 });
    await clearPlayerState();
    mockPut.mockClear();

    // Same array reference as before the clear — the skip-if-unchanged cache must not
    // suppress this, or the cleared row would never come back.
    await savePlayerState({ ...baseState, lazyQueueIds: ids, lazyQueueIndex: 2 });

    expect(putFor(RESERVOIR_KEY)).toHaveLength(1);
  });
});
