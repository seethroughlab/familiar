/**
 * Tests for prefetch reading against playback.
 *
 * The prefetcher pulled whole tracks with `response.arrayBuffer()` — an unbounded
 * transfer with no chunk loop, so the throttle added for the offline download queue could
 * not apply to it even in principle. It is how the component that exists to make playback
 * smooth became the thing breaking it: measured, 10-24 MB prefetches saturating a
 * ~850 KB/s link while the playing track needed 40 KB/s, producing PIPELINE_ERROR_READ
 * and tracks that ended about a second after starting (issue #13).
 *
 * The riskiest part of the fix is not the throttling — it is that reassembling chunks
 * must reproduce the bytes exactly. Corrupt audio would be the quietest possible failure,
 * so that is tested first and with real data rather than a length check.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { usePlaybackStore } from '../../player/playbackStore';
import { prefetchService } from '../prefetchService';
import { THROTTLE_BURST_MS, THROTTLE_IDLE_MS } from '../playbackGate';

const setPlaying = (isPlaying: boolean) => usePlaybackStore.setState({ isPlaying });

/**
 * Minimal stand-in for the parts of `Response` that `readThrottled` touches.
 *
 * `tickMs` advances the mocked clock on each read. Without it a fake-timer test reads
 * every chunk at a frozen `Date.now()`, the throttle's burst window never lapses, and the
 * whole transfer completes without pacing — the test would pass against a broken throttle.
 */
function fakeResponse(
  chunks: Uint8Array[],
  opts: { withBody?: boolean; tickMs?: number } = {}
) {
  const withBody = opts.withBody !== false;
  const tickMs = opts.tickMs ?? 0;
  let i = 0;
  const cancel = vi.fn(() => Promise.resolve());

  return {
    cancel,
    response: {
      arrayBuffer: () => {
        const total = chunks.reduce((n, c) => n + c.length, 0);
        const out = new Uint8Array(total);
        let off = 0;
        for (const c of chunks) {
          out.set(c, off);
          off += c.length;
        }
        return Promise.resolve(out.buffer);
      },
      body: withBody
        ? {
            getReader: () => ({
              read: () => {
                if (tickMs) vi.setSystemTime(Date.now() + tickMs);
                return Promise.resolve(
                  i < chunks.length
                    ? { done: false, value: chunks[i++] }
                    : { done: true, value: undefined }
                );
              },
              cancel,
            }),
          }
        : null,
    } as unknown as Response,
  };
}

// `readThrottled` is private; the reassembly and abort behaviour it owns is exactly what
// carries risk, so it is exercised directly rather than through the store subscriptions.
const readThrottled = (response: Response, signal: AbortSignal): Promise<ArrayBuffer> =>
  (prefetchService as unknown as {
    readThrottled(r: Response, s: AbortSignal): Promise<ArrayBuffer>;
  }).readThrottled(response, signal);

beforeEach(() => {
  setPlaying(false);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('reassembly', () => {
  it('reproduces the bytes exactly across chunk boundaries', async () => {
    // Deterministic, non-uniform, and larger than one chunk — a length-only check would
    // pass on data that was silently reordered or overlapped.
    const source = new Uint8Array(4096);
    for (let i = 0; i < source.length; i++) source[i] = (i * 31 + 7) % 256;

    const chunks: Uint8Array[] = [];
    for (let off = 0; off < source.length; off += 300) {
      chunks.push(source.slice(off, Math.min(off + 300, source.length)));
    }
    expect(chunks.length).toBeGreaterThan(10);

    const { response } = fakeResponse(chunks);
    const out = new Uint8Array(await readThrottled(response, new AbortController().signal));

    expect(out.length).toBe(source.length);
    expect(Array.from(out)).toEqual(Array.from(source));
  });

  it('handles a single chunk', async () => {
    const source = new Uint8Array([1, 2, 3, 4, 5]);
    const { response } = fakeResponse([source]);

    const out = new Uint8Array(await readThrottled(response, new AbortController().signal));
    expect(Array.from(out)).toEqual([1, 2, 3, 4, 5]);
  });

  it('handles an empty body', async () => {
    const { response } = fakeResponse([]);
    const out = await readThrottled(response, new AbortController().signal);
    expect(out.byteLength).toBe(0);
  });

  it('falls back to arrayBuffer when the body is not a stream', async () => {
    const { response } = fakeResponse([new Uint8Array([9, 8, 7])], { withBody: false });

    const out = new Uint8Array(await readThrottled(response, new AbortController().signal));
    expect(Array.from(out)).toEqual([9, 8, 7]);
  });
});

describe('pacing', () => {
  it('runs at full speed when nothing is playing', async () => {
    setPlaying(false);
    const chunks = Array.from({ length: 40 }, () => new Uint8Array(64));
    const { response } = fakeResponse(chunks);

    // No fake timers: if this paced, the test would take 40 x 600ms and time out.
    const out = await readThrottled(response, new AbortController().signal);
    expect(out.byteLength).toBe(40 * 64);
  });

  it('paces while audio is playing', async () => {
    vi.useFakeTimers();
    setPlaying(true);
    // Each read consumes half a burst window, so the throttle must sleep every 2 chunks.
    const chunks = Array.from({ length: 20 }, () => new Uint8Array(64));
    const { response } = fakeResponse(chunks, { tickMs: THROTTLE_BURST_MS / 2 });

    let done = false;
    readThrottled(response, new AbortController().signal).then(() => {
      done = true;
    });

    // Far more than enough wall-clock for an unthrottled read of 20 tiny chunks.
    await vi.advanceTimersByTimeAsync(THROTTLE_IDLE_MS - 50);
    expect(done).toBe(false);

    await vi.advanceTimersByTimeAsync(THROTTLE_IDLE_MS * 20);
    expect(done).toBe(true);
  });

  it('stops pacing when playback stops mid-transfer', async () => {
    vi.useFakeTimers();
    setPlaying(true);
    const chunks = Array.from({ length: 20 }, () => new Uint8Array(64));
    const { response } = fakeResponse(chunks, { tickMs: THROTTLE_BURST_MS / 2 });

    let done = false;
    readThrottled(response, new AbortController().signal).then(() => {
      done = true;
    });

    await vi.advanceTimersByTimeAsync(THROTTLE_IDLE_MS + 50);
    expect(done).toBe(false);

    setPlaying(false); // user hits pause — the rest should finish at full speed
    await vi.advanceTimersByTimeAsync(THROTTLE_IDLE_MS + 50);
    expect(done).toBe(true);
  });
});

describe('eviction', () => {
  it('aborts promptly and cancels the reader rather than finishing a discarded download', async () => {
    setPlaying(false);
    const chunks = Array.from({ length: 50 }, () => new Uint8Array(64));
    const { response, cancel } = fakeResponse(chunks);

    const controller = new AbortController();
    controller.abort();

    await expect(readThrottled(response, controller.signal)).rejects.toMatchObject({
      name: 'AbortError',
    });
    // Releasing the connection is the point — an evicted prefetch must stop consuming
    // bandwidth immediately, not run to completion for a result nobody will read.
    expect(cancel).toHaveBeenCalled();
  });

  it('surfaces as AbortError so the existing handler treats it as expected, not a failure', async () => {
    setPlaying(false);
    const { response } = fakeResponse([new Uint8Array(8)]);
    const controller = new AbortController();
    controller.abort();

    const err = await readThrottled(response, controller.signal).catch((e) => e);
    // prefetchService's catch checks `(e as Error).name === 'AbortError'` and returns
    // silently; anything else gets logged as a prefetch failure.
    expect((err as Error).name).toBe('AbortError');
  });
});
