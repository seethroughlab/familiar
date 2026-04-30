/* @vitest-environment jsdom */
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import type { MixTape } from '../../api';

vi.mock('../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../api');
  return {
    ...actual,
    mixtapesApi: {
      list: vi.fn(),
    },
  };
});

import { mixtapesApi } from '../../api';
import { useMixtapeForSource } from '../useMixtapes';

function makeMixtape(overrides: Partial<MixTape> = {}): MixTape {
  const base: MixTape = {
    id: 'mt-' + Math.random().toString(36).slice(2, 8),
    name: 'Mix',
    byline: null,
    source_playlist_id: null,
    source_smart_playlist_id: null,
    track_ids: [],
    crossfade_seconds: null,
    status: 'ready',
    error_message: null,
    duration_seconds: 60,
    file_size_bytes: 1000,
    created_at: '2026-04-29T12:00:00',
    completed_at: null,
  };
  return { ...base, ...overrides };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('useMixtapeForSource', () => {
  afterEach(() => vi.clearAllMocks());

  it('returns null when no mixtapes match the source', async () => {
    (mixtapesApi.list as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    const { result } = renderHook(
      () => useMixtapeForSource('playlist', 'pl-1'),
      { wrapper },
    );
    await waitFor(() => expect(mixtapesApi.list).toHaveBeenCalled());
    expect(result.current).toBeNull();
  });

  it('prefers an in-flight render over older ready ones for the same source', async () => {
    (mixtapesApi.list as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeMixtape({
        id: 'old-ready',
        source_playlist_id: 'pl-1',
        status: 'ready',
        created_at: '2026-04-28T12:00:00',
      }),
      makeMixtape({
        id: 'new-rendering',
        source_playlist_id: 'pl-1',
        status: 'rendering',
        created_at: '2026-04-29T12:00:00',
      }),
    ]);
    const { result } = renderHook(
      () => useMixtapeForSource('playlist', 'pl-1'),
      { wrapper },
    );
    await waitFor(() => expect(result.current?.id).toBe('new-rendering'));
  });

  it('returns the most recent ready mixtape when nothing is in-flight', async () => {
    (mixtapesApi.list as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeMixtape({
        id: 'older',
        source_playlist_id: 'pl-1',
        status: 'ready',
        created_at: '2026-04-25T12:00:00',
      }),
      makeMixtape({
        id: 'newer',
        source_playlist_id: 'pl-1',
        status: 'ready',
        created_at: '2026-04-28T12:00:00',
      }),
    ]);
    const { result } = renderHook(
      () => useMixtapeForSource('playlist', 'pl-1'),
      { wrapper },
    );
    await waitFor(() => expect(result.current?.id).toBe('newer'));
  });

  it('only returns mixtapes for the specified source', async () => {
    (mixtapesApi.list as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeMixtape({
        id: 'other-playlist',
        source_playlist_id: 'pl-OTHER',
        status: 'ready',
      }),
    ]);
    const { result } = renderHook(
      () => useMixtapeForSource('playlist', 'pl-1'),
      { wrapper },
    );
    await waitFor(() => expect(mixtapesApi.list).toHaveBeenCalled());
    expect(result.current).toBeNull();
  });

  it('matches smart playlist ids only when kind is smart_playlist', async () => {
    (mixtapesApi.list as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeMixtape({
        id: 'a',
        source_smart_playlist_id: 'sp-1',
        status: 'ready',
      }),
    ]);
    const { result } = renderHook(
      () => useMixtapeForSource('smart_playlist', 'sp-1'),
      { wrapper },
    );
    await waitFor(() => expect(result.current?.id).toBe('a'));
  });

  it('returns failed renders too — caller surfaces "Retry" UX', async () => {
    (mixtapesApi.list as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeMixtape({
        id: 'failed',
        source_playlist_id: 'pl-1',
        status: 'failed',
        error_message: 'ffmpeg exploded',
      }),
    ]);
    const { result } = renderHook(
      () => useMixtapeForSource('playlist', 'pl-1'),
      { wrapper },
    );
    await waitFor(() => expect(result.current?.status).toBe('failed'));
  });
});
