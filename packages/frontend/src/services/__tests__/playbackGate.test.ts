/**
 * Tests for the download/playback bandwidth gate.
 *
 * Regression cover for the second cause of issue #13. A bulk offline download saturates
 * the link — measured on a real failure, one 34.9 MB track took 41s (~850 KB/s, the whole
 * pipe) — and a track that had started playing 15s earlier died with
 * `PIPELINE_ERROR_READ: FFmpegDemuxer: data source error`. The download queue had no idea
 * playback existed.
 *
 * The subtle requirement is `RESUME_SETTLE_MS`: `isPlaying` dips briefly during ordinary
 * transitions, so resuming on the first `false` would restart a large transfer straight
 * into a track change and starve the next track — reproducing the bug while appearing to
 * fix it.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { usePlaybackStore } from '../../player/playbackStore';
import {
  DownloadPausedError,
  RESUME_SETTLE_MS,
  isPlaybackActive,
  waitForPlaybackIdle,
} from '../playbackGate';

const setPlaying = (isPlaying: boolean) => usePlaybackStore.setState({ isPlaying });

/** Has the promise settled? Lets us assert "still waiting" without hanging the test. */
function track(p: Promise<void>) {
  const state = { done: false };
  p.then(() => {
    state.done = true;
  });
  return state;
}

beforeEach(() => {
  vi.useFakeTimers();
  setPlaying(false);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('isPlaybackActive', () => {
  it('reflects the playback store', () => {
    setPlaying(true);
    expect(isPlaybackActive()).toBe(true);
    setPlaying(false);
    expect(isPlaybackActive()).toBe(false);
  });
});

describe('waitForPlaybackIdle', () => {
  it('resolves immediately when nothing is playing', async () => {
    setPlaying(false);
    await expect(waitForPlaybackIdle()).resolves.toBeUndefined();
  });

  it('blocks while audio is playing', async () => {
    setPlaying(true);
    const w = track(waitForPlaybackIdle());

    await vi.advanceTimersByTimeAsync(60_000);

    expect(w.done).toBe(false);
  });

  it('resolves once playback has been stopped for the settle window', async () => {
    setPlaying(true);
    const w = track(waitForPlaybackIdle());

    setPlaying(false);
    await vi.advanceTimersByTimeAsync(RESUME_SETTLE_MS + 50);

    expect(w.done).toBe(true);
  });

  it('does not resume during a brief gap between tracks', async () => {
    // The case that would reintroduce the bug: `isPlaying` flickers false on a track
    // change, a 35 MB transfer restarts, and the next track starves.
    setPlaying(true);
    const w = track(waitForPlaybackIdle());

    setPlaying(false);
    await vi.advanceTimersByTimeAsync(500); // shorter than the settle window
    setPlaying(true);
    await vi.advanceTimersByTimeAsync(60_000);

    expect(w.done).toBe(false);
  });

  it('restarts the settle window each time playback resumes', async () => {
    setPlaying(true);
    const w = track(waitForPlaybackIdle());

    for (let i = 0; i < 3; i++) {
      setPlaying(false);
      await vi.advanceTimersByTimeAsync(RESUME_SETTLE_MS - 500);
      setPlaying(true);
      await vi.advanceTimersByTimeAsync(100);
    }
    expect(w.done).toBe(false);

    setPlaying(false);
    await vi.advanceTimersByTimeAsync(RESUME_SETTLE_MS + 50);
    expect(w.done).toBe(true);
  });

  it('resolves when the download is cancelled, so cancellation is not blocked', async () => {
    setPlaying(true);
    const controller = new AbortController();
    const w = track(waitForPlaybackIdle(controller.signal));

    controller.abort();
    await vi.advanceTimersByTimeAsync(0);

    expect(w.done).toBe(true);
  });

  it('resolves immediately for an already-aborted signal', async () => {
    setPlaying(true);
    const controller = new AbortController();
    controller.abort();

    await expect(waitForPlaybackIdle(controller.signal)).resolves.toBeUndefined();
  });

  it('stops listening to the store once resolved', async () => {
    setPlaying(true);
    const w = track(waitForPlaybackIdle());
    setPlaying(false);
    await vi.advanceTimersByTimeAsync(RESUME_SETTLE_MS + 50);
    expect(w.done).toBe(true);

    // Further churn must not throw or re-arm anything.
    setPlaying(true);
    setPlaying(false);
    await vi.advanceTimersByTimeAsync(RESUME_SETTLE_MS + 50);
  });
});

describe('DownloadPausedError', () => {
  it('is distinguishable from a real failure', () => {
    const err = new DownloadPausedError();
    expect(err).toBeInstanceOf(Error);
    expect(err).toBeInstanceOf(DownloadPausedError);
    expect(err.name).toBe('DownloadPausedError');
    // The queue relies on this to retry rather than mark the track failed.
    expect(new Error('boom')).not.toBeInstanceOf(DownloadPausedError);
  });
});
