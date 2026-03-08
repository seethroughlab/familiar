/* @vitest-environment jsdom */
/**
 * Tests for useFavorites hook - favorite management with optimistic updates.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { act } from 'react';

// Mock API client
const mockToggle = vi.fn();
const mockList = vi.fn();
vi.mock('../../api', () => ({
  favoritesApi: {
    list: (...args: unknown[]) => mockList(...args),
    toggle: (...args: unknown[]) => mockToggle(...args),
  },
}));

// Mock offline status
const mockIsOffline = { value: false };
vi.mock('../useOfflineStatus', () => ({
  useOfflineStatus: () => ({ isOffline: mockIsOffline.value }),
}));

// Mock playlist cache
vi.mock('../../services/playlistCache', () => ({
  cacheFavorites: vi.fn(() => Promise.resolve()),
  cacheTrackMetadata: vi.fn(() => Promise.resolve()),
  getCachedFavorites: vi.fn(() => Promise.resolve(null)),
  resolveTrackIds: vi.fn(() => Promise.resolve([])),
}));

// Mock offline service
vi.mock('../../services/offlineService', () => ({
  downloadTrackForOffline: vi.fn(() => Promise.resolve()),
}));

// Mock sync service
vi.mock('../../services/syncService', () => ({
  queueAction: vi.fn(() => Promise.resolve()),
}));

// Mock profile service
vi.mock('../../services/profileService', () => ({
  getSelectedProfileId: vi.fn(() => Promise.resolve('profile-1')),
}));

// React Query wrapper
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

import { useFavorites } from '../useFavorites';

describe('useFavorites', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsOffline.value = false;

    mockList.mockResolvedValue({
      favorites: [
        { id: 'track-1', title: 'Song 1', artist: 'Artist', album: 'Album', duration_seconds: 200, genre: null, year: null, favorited_at: '2024-01-01T00:00:00Z' },
        { id: 'track-2', title: 'Song 2', artist: 'Artist', album: 'Album', duration_seconds: 180, genre: null, year: null, favorited_at: '2024-01-02T00:00:00Z' },
      ],
      total: 2,
    });
  });

  it('should fetch favorites on mount', async () => {
    const { result } = renderHook(() => useFavorites(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.favorites).toHaveLength(2);
    expect(result.current.total).toBe(2);
    expect(mockList).toHaveBeenCalledWith(10000, 0);
  });

  it('should provide O(1) lookup via favoriteIds set', async () => {
    const { result } = renderHook(() => useFavorites(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.favoriteIds).toBeInstanceOf(Set);
    expect(result.current.favoriteIds.has('track-1')).toBe(true);
    expect(result.current.favoriteIds.has('track-99')).toBe(false);
  });

  it('isFavorite should check membership', async () => {
    const { result } = renderHook(() => useFavorites(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isFavorite('track-1')).toBe(true);
    expect(result.current.isFavorite('unknown')).toBe(false);
  });

  it('should call toggle API when toggling', async () => {
    mockToggle.mockResolvedValue({ track_id: 'track-3', is_favorite: true });

    const { result } = renderHook(() => useFavorites(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    act(() => {
      result.current.toggle('track-3');
    });

    await waitFor(() => {
      expect(mockToggle).toHaveBeenCalledWith('track-3');
    });
  });

  it('should call toggle API for removing a favorite', async () => {
    mockToggle.mockResolvedValue({ track_id: 'track-1', is_favorite: false });

    const { result } = renderHook(() => useFavorites(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    act(() => {
      result.current.toggle('track-1');
    });

    await waitFor(() => {
      expect(mockToggle).toHaveBeenCalledWith('track-1');
    });
  });

  it('should return defaults when loading', () => {
    // Never-resolving promise to stay in loading state
    mockList.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useFavorites(), { wrapper: createWrapper() });

    expect(result.current.favorites).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(result.current.favoriteIds.size).toBe(0);
  });

  it('should queue action when offline', async () => {
    mockIsOffline.value = true;
    const { queueAction } = await import('../../services/syncService');

    const { result } = renderHook(() => useFavorites(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    act(() => {
      result.current.toggle('track-1');
    });

    await waitFor(() => {
      expect(queueAction).toHaveBeenCalledWith('favorite_toggle', { trackId: 'track-1' });
    });
  });

  it('hydrates offline favorites metadata from cached tracks', async () => {
    mockIsOffline.value = true;
    mockList.mockRejectedValueOnce(new Error('offline'));

    const { getCachedFavorites, resolveTrackIds } = await import('../../services/playlistCache');
    vi.mocked(getCachedFavorites).mockResolvedValueOnce({
      profileId: 'profile-1',
      trackIds: ['track-1'],
      cachedAt: new Date(),
    });
    vi.mocked(resolveTrackIds).mockResolvedValueOnce([
      {
        id: 'track-1',
        title: 'Cached Song',
        artist: 'Cached Artist',
        album: 'Cached Album',
        albumArtist: null,
        genre: null,
        year: 2024,
        durationSeconds: 210,
        trackNumber: 1,
        discNumber: 1,
        cachedAt: new Date(),
      },
    ]);

    const { result } = renderHook(() => useFavorites(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.usingCachedData).toBe(true);
    expect(result.current.favorites).toHaveLength(1);
    expect(result.current.favorites[0].title).toBe('Cached Song');
    expect(result.current.favorites[0].artist).toBe('Cached Artist');
    expect(result.current.favorites[0].album).toBe('Cached Album');
  });
});
