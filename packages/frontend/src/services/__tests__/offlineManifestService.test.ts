/**
 * Tests for offline manifest lookup (ADR-0006).
 *
 * These are the first tests for the offline ambient path — `player/ambient/` had none.
 * That matters because the code they replace, `offlineScoring.ts`, shipped untested and
 * carried a real bug: it read `db.cachedTracks` (all cached metadata) rather than
 * `db.offlineTracks` (what is actually downloaded), so offline ambient could select a
 * track whose audio was never on the device — a failure that only appears offline.
 *
 * The manifest is built from genuinely-downloaded ids, which fixes that. It is asserted
 * here rather than assumed.
 *
 * The other thing worth guarding is that a missing or stale manifest **degrades** rather
 * than throws. Offline ambient getting worse is acceptable; offline ambient crashing is
 * not, and it would happen exactly when the listener has no way to recover.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

const { mockGetManifest, mockGetOfflineTrackIds, mockGetProfileId, store } = vi.hoisted(() => ({
  mockGetManifest: vi.fn(),
  mockGetOfflineTrackIds: vi.fn(),
  mockGetProfileId: vi.fn(),
  store: new Map<string, unknown>(),
}));

vi.mock('../../db', () => ({
  db: {
    offlineManifests: {
      get: (id: string) => Promise.resolve(store.get(id)),
      put: (row: { profileId: string }) => {
        store.set(row.profileId, row);
        return Promise.resolve();
      },
      delete: (id: string) => {
        store.delete(id);
        return Promise.resolve();
      },
    },
  },
}));
vi.mock('../offlineService', () => ({ getOfflineTrackIds: mockGetOfflineTrackIds }));
vi.mock('../profileService', () => ({ getSelectedProfileId: mockGetProfileId }));
vi.mock('../../api/queue', () => ({ queueApi: { getOfflineManifest: mockGetManifest } }));

import {
  MIN_POOL_SIZE,
  REFRESH_DEBOUNCE_MS,
  getOfflineNeighbours,
  initOfflineManifestSync,
  pickOfflineSeed,
  refreshManifest,
} from '../offlineManifestService';

const PROFILE = 'profile-1';

function manifestRow(overrides: Record<string, unknown> = {}) {
  return {
    profileId: PROFILE,
    trackCount: 3,
    generatedAt: new Date(),
    variants: [
      {
        profile: 'ambient',
        filter_preset: 'all',
        entries: [
          {
            track_id: 'seed',
            neighbours: [
              { track_id: 'best', score: 0.9 },
              { track_id: 'middling', score: 0.6 },
              { track_id: 'weak', score: 0.2 },
            ],
          },
        ],
        seed_track_ids: ['seed', 'best'],
      },
      {
        profile: 'ambient',
        filter_preset: 'soft',
        entries: [{ track_id: 'seed', neighbours: [{ track_id: 'quiet', score: 0.8 }] }],
        seed_track_ids: ['quiet'],
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  store.clear();
  mockGetManifest.mockReset();
  mockGetOfflineTrackIds.mockReset();
  mockGetProfileId.mockReset().mockResolvedValue(PROFILE);
});

describe('lookup', () => {
  beforeEach(() => store.set(PROFILE, manifestRow()));

  it('returns neighbours best first', async () => {
    const n = await getOfflineNeighbours('seed');
    expect(n.map((x) => x.trackId)).toEqual(['best', 'middling', 'weak']);
  });

  it('excludes recently played tracks', async () => {
    const n = await getOfflineNeighbours('seed', { recentTrackIds: ['best'] });
    expect(n.map((x) => x.trackId)).toEqual(['middling', 'weak']);
  });

  it('respects the limit', async () => {
    expect(await getOfflineNeighbours('seed', { limit: 2 })).toHaveLength(2);
  });

  it('uses the requested filter preset', async () => {
    const n = await getOfflineNeighbours('seed', { filterPreset: 'soft' });
    expect(n.map((x) => x.trackId)).toEqual(['quiet']);
  });

  it('falls back to the "all" preset for one it does not know', async () => {
    // A preset added server-side before the client knows it should degrade, not vanish.
    const n = await getOfflineNeighbours('seed', { filterPreset: 'nonexistent' });
    expect(n.map((x) => x.trackId)).toEqual(['best', 'middling', 'weak']);
  });
});

describe('degrading rather than throwing', () => {
  it('returns nothing when there is no manifest', async () => {
    await expect(getOfflineNeighbours('seed')).resolves.toEqual([]);
  });

  it('returns nothing for a seed the manifest does not know', async () => {
    // A track downloaded since the last refresh is unusable as a seed until then —
    // ADR-0006 accepts that explicitly.
    store.set(PROFILE, manifestRow());
    await expect(getOfflineNeighbours('downloaded-since')).resolves.toEqual([]);
  });

  it('returns nothing without a selected profile', async () => {
    mockGetProfileId.mockResolvedValue(null);
    await expect(getOfflineNeighbours('seed')).resolves.toEqual([]);
  });

  it('picks no seed when there is no manifest', async () => {
    await expect(pickOfflineSeed()).resolves.toBeNull();
  });
});

describe('seeds', () => {
  it('picks from the manifest seed list only', async () => {
    store.set(PROFILE, manifestRow());
    const seed = await pickOfflineSeed();
    expect(['seed', 'best']).toContain(seed);
  });

  it('picks per preset', async () => {
    store.set(PROFILE, manifestRow());
    expect(await pickOfflineSeed({ filterPreset: 'soft' })).toBe('quiet');
  });
});

describe('refresh', () => {
  it('sends the downloaded set, not the cached-metadata set', async () => {
    // The bug in the code this replaces: it ranked over all cached metadata, so it could
    // pick a track whose audio was never downloaded.
    mockGetOfflineTrackIds.mockResolvedValue(Array.from({ length: 12 }, (_, i) => `t${i}`));
    mockGetManifest.mockResolvedValue({ variants: [], track_count: 12 });

    await refreshManifest();

    expect(mockGetOfflineTrackIds).toHaveBeenCalled();
    expect(mockGetManifest.mock.calls[0][0].track_ids).toHaveLength(12);
  });

  it('does not request a manifest for too small a set', async () => {
    mockGetOfflineTrackIds.mockResolvedValue(['a', 'b']);
    await refreshManifest();
    expect(mockGetManifest).not.toHaveBeenCalled();
  });

  it('drops a stale manifest when the set falls below the floor', async () => {
    store.set(PROFILE, manifestRow());
    mockGetOfflineTrackIds.mockResolvedValue(Array.from({ length: MIN_POOL_SIZE - 1 }, (_, i) => `t${i}`));

    await refreshManifest();

    // Better nothing than a manifest describing tracks the device no longer holds.
    expect(store.has(PROFILE)).toBe(false);
  });

  it('keeps the existing manifest when the request fails', async () => {
    // A slightly stale ranking beats none, and the listener never asked for this.
    store.set(PROFILE, manifestRow());
    mockGetOfflineTrackIds.mockResolvedValue(Array.from({ length: 12 }, (_, i) => `t${i}`));
    mockGetManifest.mockRejectedValue(new Error('offline'));

    await expect(refreshManifest()).resolves.toBeUndefined();
    expect(store.has(PROFILE)).toBe(true);
  });
});


describe('refresh is debounced', () => {
  // Found in use: `offline-tracks-updated` fires once per completed download, so a
  // 1,573-track job triggered a rebuild per track. Measured 17 rebuilds in 15 minutes,
  // 21s of server time, and the cost per rebuild grows with the set.
  beforeEach(() => {
    vi.useFakeTimers();
    mockGetOfflineTrackIds.mockResolvedValue(Array.from({ length: 12 }, (_, i) => `t${i}`));
    mockGetManifest.mockResolvedValue({ variants: [], track_count: 12 });
  });

  afterEach(() => vi.useRealTimers());

  it('collapses a burst of downloads into one rebuild', async () => {
    const stop = initOfflineManifestSync();
    await vi.advanceTimersByTimeAsync(0);
    mockGetManifest.mockClear(); // ignore the eager refresh at startup

    for (let i = 0; i < 50; i++) {
      window.dispatchEvent(new CustomEvent('offline-tracks-updated'));
      await vi.advanceTimersByTimeAsync(200); // downloads land faster than the window
    }
    expect(mockGetManifest).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(REFRESH_DEBOUNCE_MS + 100);
    expect(mockGetManifest).toHaveBeenCalledTimes(1);

    stop();
  });

  it('cancels a pending rebuild on teardown', async () => {
    const stop = initOfflineManifestSync();
    await vi.advanceTimersByTimeAsync(0);
    mockGetManifest.mockClear();

    window.dispatchEvent(new CustomEvent('offline-tracks-updated'));
    stop();
    await vi.advanceTimersByTimeAsync(REFRESH_DEBOUNCE_MS + 100);

    expect(mockGetManifest).not.toHaveBeenCalled();
  });
});
