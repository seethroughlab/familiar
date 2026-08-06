/**
 * Tests for useScrobbling — the track-start signal (ADR-0030).
 *
 * **Six tests were deleted from this file rather than made to pass**, and that is worth saying
 * here. They asserted browser-side scrobbling: the 30-second floor, the halfway threshold, the
 * four-minute cap on long tracks, not scrobbling while paused or while Last.fm was disconnected.
 * None of that happens in the browser any more — the server scrobbles from the `/played` and
 * `/skipped` events it already receives from every client, so leaving this here would scrobble each
 * browser play twice.
 *
 * The coverage did not vanish, it moved to `backend/tests/test_scrobble_policy.py`, which asserts
 * the same thresholds plus a case this file could never have caught: a track abandoned at 60% is a
 * *skip* to Familiar and a *scrobble* to Last.fm, and only the server sees both events.
 *
 * What is left is the one thing the server cannot infer, because `/played` and `/skipped` both fire
 * at the *end* of a track: what is playing right now.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { act } from 'react';
import { useScrobbling } from '../useScrobbling';
import { usePlayerStore } from '../../stores/playerStore';

// Unmounted hooks still react to zustand changes, which leaks calls between tests.
let _unmount: (() => void) | undefined;
function renderScrobbling() {
  const result = renderHook(() => useScrobbling());
  _unmount = result.unmount;
  return result;
}

const recordStart = vi.fn(() => Promise.resolve());

vi.mock('../../api/profiles', () => ({
  playTrackingApi: {
    recordStart: (...args: unknown[]) => recordStart(...args),
  },
}));

vi.mock('../../services/playerPersistence', () => ({
  debouncedSavePlayerState: vi.fn(),
  loadPlayerState: vi.fn(() => Promise.resolve(null)),
  fetchTracksBatched: vi.fn(() => Promise.resolve([])),
  migrateOldPlayerState: vi.fn(() => Promise.resolve()),
}));

const track = (id: string) =>
  ({
    id,
    title: `Track ${id}`,
    artist: 'Artist',
    album: 'Album',
    duration_seconds: 180,
  }) as never;

function setPlayer(state: Record<string, unknown>) {
  act(() => {
    usePlayerStore.setState(state as never);
  });
}

describe('useScrobbling — the track-start signal', () => {
  beforeEach(() => {
    usePlayerStore.setState({ currentTrack: null, isPlaying: false } as never);
    recordStart.mockClear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    _unmount?.();
    _unmount = undefined;
  });

  it('announces a track when it starts playing', async () => {
    renderScrobbling();
    setPlayer({ currentTrack: track('a'), isPlaying: true });

    await waitFor(() => expect(recordStart).toHaveBeenCalledWith('a'));
  });

  it('says nothing while nothing is playing', async () => {
    renderScrobbling();
    setPlayer({ currentTrack: track('a'), isPlaying: false });

    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(recordStart).not.toHaveBeenCalled();
  });

  /** Re-announcing mid-track would re-assert something already true. */
  it('announces each track once, not on every pause and resume', async () => {
    renderScrobbling();
    setPlayer({ currentTrack: track('a'), isPlaying: true });
    await waitFor(() => expect(recordStart).toHaveBeenCalledTimes(1));

    setPlayer({ isPlaying: false });
    setPlayer({ isPlaying: true });

    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(recordStart).toHaveBeenCalledTimes(1);
  });

  it('announces the next track when the queue advances', async () => {
    renderScrobbling();
    setPlayer({ currentTrack: track('a'), isPlaying: true });
    await waitFor(() => expect(recordStart).toHaveBeenCalledTimes(1));

    setPlayer({ currentTrack: track('b') });

    await waitFor(() => expect(recordStart).toHaveBeenCalledWith('b'));
  });

  /** Nothing downstream depends on this landing; the durable record arrives on /played. */
  it('ignores a failure to announce', async () => {
    recordStart.mockImplementationOnce(() => Promise.reject(new Error('offline')));
    renderScrobbling();

    setPlayer({ currentTrack: track('a'), isPlaying: true });
    await waitFor(() => expect(recordStart).toHaveBeenCalledTimes(1));

    // Reaching the next announcement without an unhandled rejection is the assertion.
    setPlayer({ currentTrack: track('b') });
    await waitFor(() => expect(recordStart).toHaveBeenCalledTimes(2));
  });
});
