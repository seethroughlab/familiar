/**
 * Regression tests for the prefetch cache evicting the track that is playing.
 *
 * This was the actual cause of `PIPELINE_ERROR_READ: FFmpegDemuxer: data source error`
 * (issue #13), after two earlier fixes aimed at bandwidth that turned out to be measuring
 * the wrong thing — server logs showed 40.5 MB served in 5.1s, ~7.9 MB/s, so bandwidth was
 * never the constraint.
 *
 * The chain:
 *   1. `WebAudioEngine.resolveTrackUrl` resolves a track through `getUrl()`, so a
 *      prefetched track plays from `entry.blobUrl`.
 *   2. `reconcile()` evicts every cache entry not in `getUpcomingTrackIds()`.
 *   3. `getUpcomingTrackIds` counts from step 1 — the current track is never in it.
 *   4. `evict()` calls `URL.revokeObjectURL()` on the URL being played.
 *
 * Why it looked intermittent: revoking a blob URL does not abort a read already in
 * flight, it only breaks later fetches. A short track that buffered before the advance
 * plays through; a large one dies part-way when the element next reaches for data. That
 * is why every occurrence followed a track change and why file size predicted it.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const { playerState, connectivityState } = vi.hoisted(() => ({
  playerState: {
    currentTrack: null as { id: string } | null,
    getUpcomingTrackIds: (_n: number) => [] as string[],
  },
  connectivityState: { offlineModeActive: false },
}));

vi.mock('../../player/playerStore', () => ({
  usePlayerStore: Object.assign(
    (sel: (s: typeof playerState) => unknown) => sel(playerState),
    { getState: () => playerState, subscribe: () => () => {} }
  ),
}));

vi.mock('../../stores/connectivityStore', () => ({
  useConnectivityStore: Object.assign(
    (sel: (s: typeof connectivityState) => unknown) => sel(connectivityState),
    { getState: () => connectivityState }
  ),
}));

vi.mock('../offlineService', () => ({ isTrackOffline: () => Promise.resolve(false) }));
vi.mock('../../api/base', () => ({ getApiUrl: (p: string) => `http://test${p}` }));
vi.mock('../../utils/platform', () => ({ isNativeApp: () => false }));

import { prefetchService } from '../prefetchService';

const revoked: string[] = [];
globalThis.URL.createObjectURL = vi.fn((_b: Blob) => `blob:mock/${Math.random()}`) as never;
globalThis.URL.revokeObjectURL = vi.fn((u: string) => {
  revoked.push(u);
}) as never;

type Svc = {
  cache: Map<string, { trackId: string; status: string; blobUrl?: string }>;
  reconcile(): void;
  currentTrackId: string | null;
  previousTrackId: string | null;
  downloadQueue: string[];
};
const svc = prefetchService as unknown as Svc;

/** Put a ready, blob-backed entry in the cache, as a completed prefetch would. */
function seedCached(trackId: string): string {
  const blobUrl = `blob:mock/${trackId}`;
  svc.cache.set(trackId, { trackId, status: 'ready', blobUrl });
  return blobUrl;
}

beforeEach(() => {
  revoked.length = 0;
  svc.cache.clear();
  svc.downloadQueue = [];
  svc.currentTrackId = null;
  svc.previousTrackId = null;
  playerState.currentTrack = null;
  playerState.getUpcomingTrackIds = () => [];
  connectivityState.offlineModeActive = false;
});

describe('the playing track is never evicted', () => {
  it('does not revoke the blob URL the engine is reading from', () => {
    // The exact situation: the queue advanced onto a track that had been prefetched, so
    // it is now current and therefore no longer "upcoming".
    const playingUrl = seedCached('now-playing');
    playerState.currentTrack = { id: 'now-playing' };
    playerState.getUpcomingTrackIds = () => ['next-1', 'next-2'];

    svc.reconcile();

    expect(revoked).not.toContain(playingUrl);
    expect(svc.cache.has('now-playing')).toBe(true);
  });

  it('still evicts tracks that are genuinely neither playing nor upcoming', () => {
    const staleUrl = seedCached('long-gone');
    seedCached('now-playing');
    playerState.currentTrack = { id: 'now-playing' };
    playerState.getUpcomingTrackIds = () => ['next-1'];

    svc.reconcile();

    expect(revoked).toContain(staleUrl);
    expect(svc.cache.has('long-gone')).toBe(false);
  });

  it('keeps the outgoing track alive across a crossfade', () => {
    // Both elements read at once during a crossfade. The instant the queue advances the
    // outgoing track is neither current nor upcoming — evicting it revokes a source
    // still being faded out, which surfaced as "Crossfade failed, rolling back".
    const outgoingUrl = seedCached('outgoing');
    playerState.currentTrack = { id: 'outgoing' };
    playerState.getUpcomingTrackIds = () => ['incoming'];
    svc.reconcile();

    seedCached('incoming');
    playerState.currentTrack = { id: 'incoming' };
    playerState.getUpcomingTrackIds = () => ['after-that'];
    svc.reconcile();

    expect(revoked).not.toContain(outgoingUrl);
  });

  it('releases the outgoing track once it is two advances behind', () => {
    // Retention is bounded — one extra entry, not an unbounded leak.
    const firstUrl = seedCached('first');
    playerState.currentTrack = { id: 'first' };
    playerState.getUpcomingTrackIds = () => ['second'];
    svc.reconcile();

    playerState.currentTrack = { id: 'second' };
    playerState.getUpcomingTrackIds = () => ['third'];
    svc.reconcile();

    playerState.currentTrack = { id: 'third' };
    playerState.getUpcomingTrackIds = () => ['fourth'];
    svc.reconcile();

    expect(revoked).toContain(firstUrl);
    expect(svc.cache.has('first')).toBe(false);
  });

  it('does not retain anything when nothing is playing', () => {
    const staleUrl = seedCached('stale');
    playerState.currentTrack = null;
    playerState.getUpcomingTrackIds = () => [];

    svc.reconcile();

    expect(revoked).toContain(staleUrl);
  });

  it('leaves the cache alone in offline mode', () => {
    const url = seedCached('offline-track');
    connectivityState.offlineModeActive = true;

    svc.reconcile();

    expect(revoked).not.toContain(url);
  });
});
