/* @vitest-environment jsdom */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useSyncedLyrics } from '../useSyncedLyrics';
import { tracksApi } from '../../api';
import type { LyricsResponse } from '../../api';

vi.mock('../../api', () => ({ tracksApi: { getLyrics: vi.fn() } }));

const getLyrics = tracksApi.getLyrics as ReturnType<typeof vi.fn>;

function synced(text: string): LyricsResponse {
  return { synced: true, lines: [{ time: 0, text }], plain_text: text, source: 'lrclib' };
}
const empty: LyricsResponse = { synced: false, lines: [], plain_text: '', source: 'none' };

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

beforeEach(() => getLyrics.mockReset());
afterEach(() => vi.clearAllMocks());

describe('useSyncedLyrics', () => {
  it('loads synced lyrics for a track', async () => {
    getLyrics.mockResolvedValueOnce(synced('hello'));
    const { result } = renderHook(({ id }) => useSyncedLyrics(id), { initialProps: { id: 'A' } });
    await waitFor(() => expect(result.current?.[0]?.text).toBe('hello'));
  });

  it('treats an unsynced/empty response as no lyrics', async () => {
    getLyrics.mockResolvedValueOnce(empty);
    const { result } = renderHook(({ id }) => useSyncedLyrics(id), { initialProps: { id: 'A' } });
    await waitFor(() => expect(getLyrics).toHaveBeenCalled());
    expect(result.current).toBeNull();
  });

  it('clears the previous track lyrics immediately on skip', async () => {
    getLyrics.mockResolvedValueOnce(synced('first'));
    const slow = deferred<LyricsResponse>();
    getLyrics.mockReturnValueOnce(slow.promise);

    const { result, rerender } = renderHook(({ id }) => useSyncedLyrics(id), { initialProps: { id: 'A' } });
    await waitFor(() => expect(result.current?.[0]?.text).toBe('first'));

    rerender({ id: 'B' }); // skip before B resolves
    expect(result.current).toBeNull(); // old lyrics gone right away

    await act(async () => { slow.resolve(synced('second')); });
    await waitFor(() => expect(result.current?.[0]?.text).toBe('second'));
  });

  it('ignores a stale out-of-order response from a previous track', async () => {
    const a = deferred<LyricsResponse>(); // slow track A
    const b = deferred<LyricsResponse>(); // track B
    getLyrics.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);

    const { result, rerender } = renderHook(({ id }) => useSyncedLyrics(id), { initialProps: { id: 'A' } });
    rerender({ id: 'B' });

    // B resolves first (good), then A resolves late with empty.
    await act(async () => { b.resolve(synced('B-lyrics')); });
    await waitFor(() => expect(result.current?.[0]?.text).toBe('B-lyrics'));

    await act(async () => { a.resolve(empty); });
    // The stale A response must NOT overwrite B's lyrics back to the fallback.
    expect(result.current?.[0]?.text).toBe('B-lyrics');
  });
});
