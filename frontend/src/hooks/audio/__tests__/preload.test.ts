/**
 * Tests for preloadNextTrack - loading next track into the spare audio element.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { preloadNextTrack } from '../crossfade';
import * as audioGraph from '../audioGraph';

vi.mock('../platform', () => ({
  useDirectPlayback: false,
  useWebAudio: true,
  MOBILE_TRANSITION_OVERLAP: 0.3,
  log: {
    info: vi.fn(),
    debug: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock('../../../stores/playerStore', () => ({
  usePlayerStore: Object.assign(vi.fn(), {
    getState: () => ({ currentTrack: null }),
  }),
}));

vi.mock('../../../services/offlineService', () => ({
  getOfflineTrack: vi.fn(() => Promise.resolve(null)),
  createOfflineTrackUrl: vi.fn((_blob: unknown) => 'blob:offline-url'),
  revokeOfflineTrackUrl: vi.fn(),
}));

vi.mock('../../../api', () => ({
  tracksApi: {
    getStreamUrl: (id: string) => `/api/v1/tracks/${id}/stream`,
  },
}));

vi.mock('../../../services/audioEffects', () => ({
  initEffectsChain: vi.fn(() => ({
    input: { connect: vi.fn() },
    output: { connect: vi.fn() },
  })),
}));

vi.mock('../../../stores/toastStore', () => ({
  showError: vi.fn(),
}));

describe('preloadNextTrack', () => {
  let nextElement: HTMLAudioElement;

  beforeEach(() => {
    vi.useFakeTimers();

    nextElement = new Audio() as unknown as HTMLAudioElement;

    vi.spyOn(audioGraph, 'getNextElement').mockReturnValue(nextElement);
    vi.spyOn(audioGraph, 'getPreloadingTrackId').mockReturnValue(null);
    vi.spyOn(audioGraph, 'setPreloadingTrackId').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getNextOfflineUrl').mockReturnValue(null);
    vi.spyOn(audioGraph, 'setNextOfflineUrl').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getTrackUrl').mockResolvedValue({
      url: '/api/v1/tracks/track-1/stream',
      isOffline: false,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('sets src, loads, and resolves true on canplay event', async () => {
    const promise = preloadNextTrack('track-1');

    // Need to flush the await getTrackUrl() microtask
    await vi.advanceTimersByTimeAsync(0);

    // src should now be set
    expect(nextElement.src).toBe('/api/v1/tracks/track-1/stream');
    expect(nextElement.load).toHaveBeenCalled();

    // Simulate canplay event
    (nextElement as unknown as { emit: (e: string) => void }).emit('canplay');

    const result = await promise;
    expect(result).toBe(true);
    expect(audioGraph.setPreloadingTrackId).toHaveBeenCalledWith(null);
  });

  it('resolves false on 10s timeout', async () => {
    const promise = preloadNextTrack('track-1');

    // Flush the async getTrackUrl
    await vi.advanceTimersByTimeAsync(0);

    // Advance past the 10s timeout
    await vi.advanceTimersByTimeAsync(10001);

    const result = await promise;
    expect(result).toBe(false);
    expect(audioGraph.setPreloadingTrackId).toHaveBeenCalledWith(null);
  });

  it('resolves false on error event', async () => {
    const promise = preloadNextTrack('track-1');

    // Flush the async getTrackUrl
    await vi.advanceTimersByTimeAsync(0);

    // Simulate error event
    (nextElement as unknown as { emit: (e: string) => void }).emit('error');

    const result = await promise;
    expect(result).toBe(false);
    expect(audioGraph.setPreloadingTrackId).toHaveBeenCalledWith(null);
  });

  it('skips if already preloading same track ID', async () => {
    vi.spyOn(audioGraph, 'getPreloadingTrackId').mockReturnValue('track-1');

    const result = await preloadNextTrack('track-1');
    expect(result).toBe(false);
    expect(nextElement.load).not.toHaveBeenCalled();
  });

  it('revokes previous offline URL before setting new one', async () => {
    const { revokeOfflineTrackUrl } = await import('../../../services/offlineService');
    vi.spyOn(audioGraph, 'getNextOfflineUrl').mockReturnValue('blob:old-url');

    const promise = preloadNextTrack('track-2');

    // Flush the async getTrackUrl
    await vi.advanceTimersByTimeAsync(0);

    expect(revokeOfflineTrackUrl).toHaveBeenCalledWith('blob:old-url');
    expect(audioGraph.setNextOfflineUrl).toHaveBeenCalledWith(null);

    // Complete the preload
    (nextElement as unknown as { emit: (e: string) => void }).emit('canplay');
    await promise;
  });

  it('returns false when next element is null', async () => {
    vi.spyOn(audioGraph, 'getNextElement').mockReturnValue(null);

    const result = await preloadNextTrack('track-1');
    expect(result).toBe(false);
  });
});
