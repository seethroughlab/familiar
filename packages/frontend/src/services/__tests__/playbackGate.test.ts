/**
 * Tests for the download/playback bandwidth throttle.
 *
 * Regression cover for the second cause of issue #13. A bulk offline download saturates
 * the link — measured on a real failure, one 34.9 MB track took 41s (~850 KB/s, the whole
 * pipe) — and a track that had started playing 15s earlier died with
 * `PIPELINE_ERROR_READ: FFmpegDemuxer: data source error`.
 *
 * The throttle deliberately does *not* stop downloads. Measured across 26,446 tracks, a
 * track needs 33.8 KB/s on average and 102.5 KB/s at p95 — 4% and 12% of that link. The
 * point is to leave headroom, not to hand playback the whole pipe.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { usePlaybackStore } from '../../player/playbackStore';
import {
  DownloadThrottle,
  THROTTLE_BURST_MS,
  THROTTLE_IDLE_MS,
  isPlaybackActive,
} from '../playbackGate';

const setPlaying = (isPlaying: boolean) => usePlaybackStore.setState({ isPlaying });

/** Has the promise settled? Lets us assert "still sleeping" without hanging the test. */
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

describe('DownloadThrottle when nothing is playing', () => {
  it('never sleeps, so an idle device downloads at full speed', async () => {
    const t = new DownloadThrottle();
    for (let i = 0; i < 50; i++) {
      const w = track(t.pace());
      await vi.advanceTimersByTimeAsync(0);
      expect(w.done).toBe(true);
    }
    expect(t.throttling).toBe(false);
  });
});

describe('DownloadThrottle while audio plays', () => {
  it('lets a burst through before sleeping', async () => {
    setPlaying(true);
    const t = new DownloadThrottle();

    // First call opens the burst window; chunks inside it pass straight through.
    await t.pace();
    vi.setSystemTime(Date.now() + THROTTLE_BURST_MS - 50);
    const inBurst = track(t.pace());
    await vi.advanceTimersByTimeAsync(0);

    expect(inBurst.done).toBe(true);
  });

  it('sleeps once the burst window is spent', async () => {
    setPlaying(true);
    const t = new DownloadThrottle();

    await t.pace();
    vi.setSystemTime(Date.now() + THROTTLE_BURST_MS + 10);
    const w = track(t.pace());

    await vi.advanceTimersByTimeAsync(THROTTLE_IDLE_MS - 50);
    expect(w.done).toBe(false);

    await vi.advanceTimersByTimeAsync(100);
    expect(w.done).toBe(true);
  });

  it('reports that it is throttling, for the UI', async () => {
    setPlaying(true);
    const t = new DownloadThrottle();

    await t.pace();

    expect(t.throttling).toBe(true);
  });

  it('does not stop downloads outright', async () => {
    // The whole point: playback needs ~4-12% of the link, so a throttled download must
    // keep making progress rather than waiting for silence.
    setPlaying(true);
    const t = new DownloadThrottle();

    let chunks = 0;
    for (let i = 0; i < 12; i++) {
      const w = track(t.pace());
      await vi.advanceTimersByTimeAsync(THROTTLE_IDLE_MS + 10);
      vi.setSystemTime(Date.now() + THROTTLE_BURST_MS + 10);
      if (w.done) chunks++;
    }

    expect(chunks).toBe(12);
  });
});

describe('DownloadThrottle when playback stops', () => {
  it('goes back to full speed', async () => {
    setPlaying(true);
    const t = new DownloadThrottle();
    await t.pace();
    expect(t.throttling).toBe(true);

    setPlaying(false);
    const w = track(t.pace());
    await vi.advanceTimersByTimeAsync(0);

    expect(w.done).toBe(true);
    expect(t.throttling).toBe(false);
  });

  it('notices playback stopping during a sleep', async () => {
    setPlaying(true);
    const t = new DownloadThrottle();
    await t.pace();
    vi.setSystemTime(Date.now() + THROTTLE_BURST_MS + 10);

    const w = track(t.pace());
    setPlaying(false); // stopped mid-sleep
    await vi.advanceTimersByTimeAsync(THROTTLE_IDLE_MS + 50);

    expect(w.done).toBe(true);
    expect(t.throttling).toBe(false);
  });

  it('returns immediately when the download is cancelled mid-sleep', async () => {
    setPlaying(true);
    const t = new DownloadThrottle();
    const controller = new AbortController();
    await t.pace(controller.signal);
    vi.setSystemTime(Date.now() + THROTTLE_BURST_MS + 10);

    const w = track(t.pace(controller.signal));
    controller.abort();
    await vi.advanceTimersByTimeAsync(THROTTLE_IDLE_MS + 50);

    expect(w.done).toBe(true);
  });
});

describe('throttle instances are independent', () => {
  it('does not share burst state between downloads', async () => {
    setPlaying(true);
    const a = new DownloadThrottle();
    const b = new DownloadThrottle();

    await a.pace();
    vi.setSystemTime(Date.now() + THROTTLE_BURST_MS + 10);

    // `b` has never paced, so it opens its own burst rather than inheriting a's.
    const w = track(b.pace());
    await vi.advanceTimersByTimeAsync(0);

    expect(w.done).toBe(true);
  });
});
