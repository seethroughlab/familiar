/**
 * Tests for usePlayTracking hook.
 *
 * Covers ADR-0004 phase 2: every track the listener moves on from reports a listening
 * event, including short skips that previously produced no API call at all.
 *
 * Note on negative assertions: `await waitFor(() => expect(x).not.toHaveBeenCalled())`
 * passes on the first tick and proves nothing about async work. These tests flush the
 * microtask queue first, then assert directly.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { renderHook, act, waitFor, cleanup } from '@testing-library/react';
import { usePlayTracking } from '../usePlayTracking';
import { usePlayerStore } from '../../stores/playerStore';
import { deliverListenEvent } from '../../services/syncService';

// The hook delivers through syncService, which owns the catch-then-queue policy.
vi.mock('../../services/syncService', () => ({
  deliverListenEvent: vi.fn(() => Promise.resolve()),
}));

vi.mock('../../services/playerPersistence', () => ({
  debouncedSavePlayerState: vi.fn(),
  loadPlayerState: vi.fn(() => Promise.resolve(null)),
  fetchTracksBatched: vi.fn(() => Promise.resolve([])),
  migrateOldPlayerState: vi.fn(() => Promise.resolve()),
}));

const mockDeliver = vi.mocked(deliverListenEvent);

/** Let any pending promise chains settle so a negative assertion means something. */
const flush = async () => {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
};

describe('usePlayTracking', () => {
  beforeEach(() => {
    usePlayerStore.setState({
      currentTrack: null,
      isPlaying: false,
      currentTime: 0,
      duration: 180,
      volume: 0.5,
      shuffle: false,
      repeat: 'off',
      queue: [],
      queueIndex: -1,
      history: [],
      shuffleOrder: [],
      shuffleIndex: -1,
      crossfadeState: 'idle',
      nextTrackPreloaded: false,
      isHydrated: true,
      _advanceReason: 'user',
      queueSource: null,
    });
    vi.clearAllMocks();
  });

  afterEach(() => {
    // vitest.config.ts sets neither `globals: true` nor a setupFile, so React Testing
    // Library's automatic cleanup never runs. Without this, hooks from earlier tests
    // stay mounted and keep reacting to the shared player store — every assertion after
    // the first test would be counting other tests' emissions.
    cleanup();
    vi.clearAllMocks();
  });

  const createMockTrack = (id: string) => ({
    id,
    file_path: `/music/${id}.mp3`,
    title: 'Test Track',
    artist: 'Test Artist',
    album: 'Test Album',
    album_artist: null,
    album_type: 'album' as const,
    track_number: null,
    disc_number: null,
    year: null,
    genre: null,
    duration_seconds: 180,
    format: 'mp3',
    analysis_version: 1,
  });

  /** Play `track` up to `currentTime`, then advance to another track with `reason`. */
  const playThenAdvance = async (
    track: ReturnType<typeof createMockTrack>,
    currentTime: number,
    reason: string,
    duration = 180,
  ) => {
    const { rerender } = renderHook(() => usePlayTracking());

    act(() => {
      usePlayerStore.setState({ currentTrack: track, isPlaying: true, duration, currentTime: 0 });
    });
    rerender();
    act(() => {
      usePlayerStore.setState({ currentTime });
    });
    rerender();

    act(() => {
      usePlayerStore.setState({
        currentTrack: createMockTrack('next-track'),
        currentTime: 0,
        _advanceReason: reason as never,
      });
    });
    rerender();
    await flush();
  };

  describe('play recording', () => {
    it('does not record a play below the 30s minimum', async () => {
      const track = createMockTrack('track-1');
      renderHook(() => usePlayTracking());

      act(() => {
        usePlayerStore.setState({ currentTrack: track, isPlaying: true, duration: 180, currentTime: 10 });
      });
      await flush();

      const plays = mockDeliver.mock.calls.filter((c) => c[1] === 'played');
      expect(plays).toHaveLength(0);
    });

    it('records a play once the threshold is reached', async () => {
      const track = createMockTrack('track-2');
      const { rerender } = renderHook(() => usePlayTracking());

      act(() => {
        usePlayerStore.setState({ currentTrack: track, isPlaying: true, duration: 180, currentTime: 0 });
      });
      rerender();
      act(() => {
        usePlayerStore.setState({ currentTime: 95 });
      });
      rerender();

      await waitFor(() => {
        expect(mockDeliver).toHaveBeenCalledWith(
          'track-2',
          'played',
          expect.objectContaining({ track_duration: 180 }),
          expect.any(Number),
        );
      }, { timeout: 2000 });
    });

    it('does not accumulate time while paused', async () => {
      const track = createMockTrack('track-3');
      const { rerender } = renderHook(() => usePlayTracking());

      act(() => {
        usePlayerStore.setState({ currentTrack: track, isPlaying: true, duration: 180, currentTime: 25 });
      });
      rerender();
      act(() => {
        usePlayerStore.setState({ isPlaying: false });
      });
      rerender();
      act(() => {
        usePlayerStore.setState({ currentTime: 100 });
      });
      rerender();
      await flush();

      const plays = mockDeliver.mock.calls.filter((c) => c[1] === 'played');
      expect(plays).toHaveLength(0);
    });
  });

  describe('skip reporting', () => {
    it('reports a short skip that previously emitted nothing', async () => {
      await playThenAdvance(createMockTrack('track-skip'), 5, 'user');

      expect(mockDeliver).toHaveBeenCalledWith(
        'track-skip',
        'skipped',
        expect.objectContaining({ reason: 'user', track_duration: 180 }),
      );
      // A skip must never bump the play aggregate.
      expect(mockDeliver.mock.calls.filter((c) => c[1] === 'played')).toHaveLength(0);
    });

    it('reports a natural end as natural, not a skip', async () => {
      await playThenAdvance(createMockTrack('track-ended'), 20, 'ended');

      expect(mockDeliver).toHaveBeenCalledWith(
        'track-ended',
        'skipped',
        expect.objectContaining({ reason: 'natural' }),
      );
    });

    it('reports a crossfade advance as natural', async () => {
      // Crossfade fires early, so the ratio alone would read as a skip.
      await playThenAdvance(createMockTrack('track-xfade'), 20, 'crossfade');

      expect(mockDeliver).toHaveBeenCalledWith(
        'track-xfade',
        'skipped',
        expect.objectContaining({ reason: 'natural' }),
      );
    });

    it('reports iOS background auto-advance as natural', async () => {
      await playThenAdvance(createMockTrack('track-native'), 20, 'native-auto');

      expect(mockDeliver).toHaveBeenCalledWith(
        'track-native',
        'skipped',
        expect.objectContaining({ reason: 'natural' }),
      );
    });

    it('reports a failed load as error, never as dislike', async () => {
      await playThenAdvance(createMockTrack('track-broken'), 2, 'error');

      expect(mockDeliver).toHaveBeenCalledWith(
        'track-broken',
        'skipped',
        expect.objectContaining({ reason: 'error' }),
      );
    });

    it('emits nothing for a system advance', async () => {
      // Offline queue rebuilds, hydration and profile switches change the track without
      // the listener doing anything — reporting those would log phantom skips.
      await playThenAdvance(createMockTrack('track-rebuild'), 5, 'system');

      expect(mockDeliver).not.toHaveBeenCalled();
    });
  });

  describe('completion ratio', () => {
    it('uses the OUTGOING track duration, not the incoming one', async () => {
      // The regression this guards: by the time the reset effect runs, `duration` in the
      // render closure is already the new track's.
      await playThenAdvance(createMockTrack('track-short'), 10, 'user', 40);

      expect(mockDeliver).toHaveBeenCalledWith(
        'track-short',
        'skipped',
        expect.objectContaining({ track_duration: 40, played_seconds: 10 }),
      );
    });

    it('uses a never-played track OWN duration, not the previous track', async () => {
      // Regression from real data: a track that failed to load reported the previous
      // track's duration (75.5s instead of its own 374.5s), because the accumulate
      // effect early-returns before it can update the duration ref.
      const first = createMockTrack('first');
      const broken = { ...createMockTrack('broken'), duration_seconds: 374 };
      const { rerender } = renderHook(() => usePlayTracking());

      act(() => {
        usePlayerStore.setState({ currentTrack: first, isPlaying: true, duration: 75, currentTime: 0 });
      });
      rerender();
      act(() => {
        usePlayerStore.setState({ currentTime: 72 });
      });
      rerender();

      // Advance to a track that never plays — no duration ever reported by the engine.
      act(() => {
        usePlayerStore.setState({ currentTrack: broken, currentTime: 0, isPlaying: false, _advanceReason: 'ended' });
      });
      rerender();
      act(() => {
        usePlayerStore.setState({ currentTrack: createMockTrack('third'), currentTime: 0, _advanceReason: 'error' });
      });
      rerender();
      await flush();

      expect(mockDeliver).toHaveBeenCalledWith(
        'broken',
        'skipped',
        expect.objectContaining({ reason: 'error', track_duration: 374 }),
      );
    });
  });

  describe('context', () => {
    it('passes the queue source through as context', async () => {
      const track = createMockTrack('track-ctx');
      const { rerender } = renderHook(() => usePlayTracking());

      act(() => {
        usePlayerStore.setState({
          currentTrack: track,
          isPlaying: true,
          duration: 180,
          currentTime: 0,
          queueSource: { type: 'playlist', id: 'pl-1' },
        });
      });
      rerender();
      act(() => {
        usePlayerStore.setState({ currentTime: 5 });
      });
      rerender();
      act(() => {
        usePlayerStore.setState({
          currentTrack: createMockTrack('next'),
          currentTime: 0,
          _advanceReason: 'user',
        });
      });
      rerender();
      await flush();

      expect(mockDeliver).toHaveBeenCalledWith(
        'track-ctx',
        'skipped',
        expect.objectContaining({ context: 'playlist' }),
      );
    });
  });
});
