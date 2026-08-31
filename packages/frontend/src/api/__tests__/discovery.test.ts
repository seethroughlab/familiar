/**
 * Unit tests for the discovery API client (newReleasesApi + externalAlbumsApi).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// vi.mock is hoisted; use vi.hoisted so the mock object is available when
// the factory runs.
const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

vi.mock('../base', () => ({
  default: mockApi,
}));

import { newReleasesApi, externalAlbumsApi } from '../discovery';

describe('newReleasesApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('list() GETs /new-releases with params', async () => {
    mockApi.get.mockResolvedValueOnce({
      data: { releases: [], total: 0, limit: 50, offset: 0 },
    });

    const result = await newReleasesApi.list({
      limit: 50,
      offset: 100,
      include_dismissed: true,
      include_owned: false,
    });

    expect(mockApi.get).toHaveBeenCalledWith('/new-releases', {
      params: {
        limit: 50,
        offset: 100,
        include_dismissed: true,
        include_owned: false,
      },
    });
    expect(result.total).toBe(0);
  });

  it('getStatus() GETs /new-releases/status', async () => {
    mockApi.get.mockResolvedValueOnce({
      data: {
        total_releases_found: 12,
        new_releases_available: 4,
        artists_in_library: 50,
        artists_checked: 50,
        last_check_at: '2026-04-27T00:00:00Z',
        progress: null,
        rotation: {
          total_artists_in_rotation: 0,
          checked_this_week: 0,
          remaining_this_week: 0,
          estimated_days_to_complete: 0,
        },
      },
    });

    const result = await newReleasesApi.getStatus();
    expect(mockApi.get).toHaveBeenCalledWith('/new-releases/status');
    expect(result.new_releases_available).toBe(4);
  });

  it('checkBatch() POSTs /new-releases/check/batch with params', async () => {
    mockApi.post.mockResolvedValueOnce({
      data: { status: 'started', message: 'Priority-based new releases check started (batch size: 75)' },
    });

    await newReleasesApi.checkBatch({ batch_size: 75 });
    expect(mockApi.post).toHaveBeenCalledWith('/new-releases/check/batch', null, {
      params: { batch_size: 75 },
    });
  });
});

describe('externalAlbumsApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('dismiss() POSTs /external-albums/{id}/dismiss', async () => {
    mockApi.post.mockResolvedValueOnce({ data: { status: 'ok' } });

    await externalAlbumsApi.dismiss('cache-row-abc');
    expect(mockApi.post).toHaveBeenCalledWith(
      '/external-albums/cache-row-abc/dismiss',
    );
  });

  it('listeningProfile() GETs /library/discover/external-albums', async () => {
    mockApi.get.mockResolvedValueOnce({ data: { albums: [] } });

    await externalAlbumsApi.listeningProfile({ limit: 12, refresh: true });
    expect(mockApi.get).toHaveBeenCalledWith('/library/discover/external-albums', {
      params: { limit: 12, refresh: true },
    });
  });

  it('forPlaylist() GETs /playlists/{id}/recommendations/external-albums', async () => {
    mockApi.get.mockResolvedValueOnce({ data: { albums: [] } });

    await externalAlbumsApi.forPlaylist('playlist-abc', { limit: 8 });
    expect(mockApi.get).toHaveBeenCalledWith(
      '/playlists/playlist-abc/recommendations/external-albums',
      { params: { limit: 8 } },
    );
  });
});
