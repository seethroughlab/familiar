/* @vitest-environment jsdom */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useTrackDetail } from '../useTrackDetail';
import { tracksApi } from '../../api';
import type { Track, TrackFeatures } from '../../types';

vi.mock('../../api', () => ({ tracksApi: { get: vi.fn() } }));

const get = tracksApi.get as ReturnType<typeof vi.fn>;

function track(id: string, features?: Partial<TrackFeatures>): Track {
  return {
    id,
    title: id,
    features: features as TrackFeatures | undefined,
  } as Track;
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

beforeEach(() => get.mockReset());
afterEach(() => vi.clearAllMocks());

describe('useTrackDetail', () => {
  it('loads the track detail, carrying features', async () => {
    get.mockResolvedValueOnce(track('A', { energy: 0.8, valence: 0.3 }));
    const { result } = renderHook(({ id }) => useTrackDetail(id), { initialProps: { id: 'A' } });
    await waitFor(() => expect(result.current?.features?.energy).toBe(0.8));
  });

  it('does not fetch without a track id', () => {
    const { result } = renderHook(({ id }) => useTrackDetail(id), {
      initialProps: { id: null as string | null },
    });
    expect(get).not.toHaveBeenCalled();
    expect(result.current).toBeNull();
  });

  // An unanalysed track resolves fine, just without features. That is not an error, and the
  // visualizer falls back to its own defaults (ADR-0064: no analysis must not mean no track).
  it('accepts a track with no features', async () => {
    get.mockResolvedValueOnce(track('A'));
    const { result } = renderHook(({ id }) => useTrackDetail(id), { initialProps: { id: 'A' } });
    await waitFor(() => expect(result.current?.id).toBe('A'));
    expect(result.current?.features).toBeUndefined();
  });

  it('yields null when the fetch fails, rather than throwing', async () => {
    get.mockRejectedValueOnce(new Error('offline'));
    const { result } = renderHook(({ id }) => useTrackDetail(id), { initialProps: { id: 'A' } });
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(result.current).toBeNull();
  });

  it('clears the previous track detail immediately on skip', async () => {
    get.mockResolvedValueOnce(track('A', { energy: 0.1 }));
    const slow = deferred<Track>();
    get.mockReturnValueOnce(slow.promise);

    const { result, rerender } = renderHook(({ id }) => useTrackDetail(id), {
      initialProps: { id: 'A' },
    });
    await waitFor(() => expect(result.current?.id).toBe('A'));

    rerender({ id: 'B' }); // skip before B resolves
    // A's analysis must not be read against B — that would drive the visualizer from the wrong song.
    expect(result.current).toBeNull();

    await act(async () => { slow.resolve(track('B', { energy: 0.9 })); });
    await waitFor(() => expect(result.current?.features?.energy).toBe(0.9));
  });

  it('ignores a stale out-of-order response from a previous track', async () => {
    const a = deferred<Track>();
    const b = deferred<Track>();
    get.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);

    const { result, rerender } = renderHook(({ id }) => useTrackDetail(id), {
      initialProps: { id: 'A' },
    });
    rerender({ id: 'B' });

    await act(async () => { b.resolve(track('B', { energy: 0.9 })); });
    await waitFor(() => expect(result.current?.id).toBe('B'));

    await act(async () => { a.resolve(track('A', { energy: 0.1 })); });
    // The late A response must not replace B's detail.
    expect(result.current?.id).toBe('B');
    expect(result.current?.features?.energy).toBe(0.9);
  });
});
