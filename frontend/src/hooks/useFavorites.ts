/**
 * Hook for managing favorites with optimistic updates.
 * Uses React Query as single source of truth for favorites state.
 * Supports offline caching for offline access.
 */
import { useMemo, useCallback, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { favoritesApi, type FavoriteTrack, type FavoritesListResponse } from '../api/client';
import { useOfflineStatus } from './useOfflineStatus';
import * as playlistCache from '../services/playlistCache';
import * as offlineService from '../services/offlineService';
import * as syncService from '../services/syncService';
import { getSelectedProfileId } from '../services/profileService';

export interface UseFavoritesResult {
  /** Set of favorite track IDs for O(1) lookup */
  favoriteIds: Set<string>;
  /** Check if a track is favorited */
  isFavorite: (trackId: string) => boolean;
  /** Toggle favorite status (optimistic update) */
  toggle: (trackId: string) => void;
  /** List of favorite tracks with metadata */
  favorites: FavoriteTrack[];
  /** Total count of favorites */
  total: number;
  /** Loading state */
  isLoading: boolean;
  /** Whether using cached offline data */
  usingCachedData: boolean;
}

/**
 * Hook for managing favorites with shared state and optimistic updates.
 * Fetches all favorites once and provides O(1) lookups for heart icon state.
 */
export function useFavorites(): UseFavoritesResult {
  const queryClient = useQueryClient();
  const { isOffline } = useOfflineStatus();
  const [usingCachedData, setUsingCachedData] = useState(false);

  // Fetch all favorites (source of truth) with offline fallback
  const { data, isLoading } = useQuery({
    queryKey: ['favorites'],
    queryFn: async () => {
      try {
        const result = await favoritesApi.list(10000, 0); // Get all favorites
        setUsingCachedData(false);

        // Cache favorites for offline use
        const profileId = await getSelectedProfileId();
        if (profileId) {
          await playlistCache.cacheFavorites(
            profileId,
            result.favorites.map((f) => f.id)
          );
        }

        return result;
      } catch (error) {
        // If offline, try to load from cache
        if (isOffline) {
          const profileId = await getSelectedProfileId();
          if (profileId) {
            const cached = await playlistCache.getCachedFavorites(profileId);
            if (cached) {
              setUsingCachedData(true);
              // Return a minimal response with just the track IDs
              // Full track metadata would be resolved separately from cachedTracks
              return {
                favorites: cached.trackIds.map((id): FavoriteTrack => ({
                  id,
                  file_path: '',
                  title: null,
                  artist: null,
                  album: null,
                  album_artist: null,
                  album_type: 'album',
                  track_number: null,
                  disc_number: null,
                  year: null,
                  genre: null,
                  duration_seconds: null,
                  format: null,
                  analysis_version: 0,
                  favorited_at: '',
                })),
                total: cached.trackIds.length,
              } as FavoritesListResponse;
            }
          }
        }
        throw error;
      }
    },
    staleTime: 30000, // Consider fresh for 30s
    retry: isOffline ? false : 3,
  });

  // Derive a Set for O(1) lookups
  const favoriteIds = useMemo(
    () => new Set(data?.favorites.map((f) => f.id) ?? []),
    [data]
  );

  // Check if a track is favorited
  const isFavorite = useCallback(
    (trackId: string) => favoriteIds.has(trackId),
    [favoriteIds]
  );

  // Toggle mutation with optimistic updates and offline queueing
  const toggleMutation = useMutation({
    mutationFn: async (trackId: string) => {
      if (isOffline) {
        // Queue the action for later sync
        await syncService.queueAction('favorite_toggle', { trackId });
        // Return a mock response for optimistic update
        return { track_id: trackId, is_favorite: !favoriteIds.has(trackId) };
      }
      return favoritesApi.toggle(trackId);
    },
    onMutate: async (trackId: string) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: ['favorites'] });

      // Snapshot previous value
      const previous = queryClient.getQueryData<FavoritesListResponse>(['favorites']);

      // Optimistically update
      queryClient.setQueryData<FavoritesListResponse>(['favorites'], (old) => {
        if (!old) return old;

        const isCurrentlyFavorite = old.favorites.some((f) => f.id === trackId);

        if (isCurrentlyFavorite) {
          // Remove from favorites
          return {
            ...old,
            favorites: old.favorites.filter((f) => f.id !== trackId),
            total: old.total - 1,
          };
        } else {
          // Add to favorites (with placeholder data - will be refreshed)
          const newFavorite: FavoriteTrack = {
            id: trackId,
            file_path: '',
            title: null,
            artist: null,
            album: null,
            album_artist: null,
            album_type: 'album',
            track_number: null,
            disc_number: null,
            year: null,
            genre: null,
            duration_seconds: null,
            format: null,
            analysis_version: 0,
            favorited_at: new Date().toISOString(),
          };
          return {
            ...old,
            favorites: [newFavorite, ...old.favorites],
            total: old.total + 1,
          };
        }
      });

      // Also update cached favorites for offline
      const profileId = await getSelectedProfileId();
      if (profileId) {
        const currentIds = Array.from(favoriteIds);
        const isCurrentlyFavorite = favoriteIds.has(trackId);
        const newIds = isCurrentlyFavorite
          ? currentIds.filter((id) => id !== trackId)
          : [trackId, ...currentIds];
        await playlistCache.cacheFavorites(profileId, newIds);
      }

      return { previous };
    },
    onError: (_err, _trackId, context) => {
      // Rollback on error (only if online - offline changes are queued)
      if (context?.previous && !isOffline) {
        queryClient.setQueryData(['favorites'], context.previous);
      }
    },
    onSettled: (_data, _error, trackId) => {
      // Refetch to ensure consistency (only when online)
      if (!isOffline) {
        queryClient.invalidateQueries({ queryKey: ['favorites'] });
      }

      // Auto-download the newly favorited track if auto-download is enabled
      if (trackId && !isOffline) {
        const wasAdded = !favoriteIds.has(trackId);
        if (wasAdded) {
          // Check if auto-download is enabled (best-effort, non-blocking)
          const autoDownloadData = queryClient.getQueryData<{ enabled: boolean }>(['favorites-auto-download']);
          if (autoDownloadData?.enabled) {
            offlineService.downloadTrackForOffline(trackId).catch(() => {
              // Best-effort: silently ignore download errors
            });
          }
        }
      }
    },
  });

  return {
    favoriteIds,
    isFavorite,
    toggle: toggleMutation.mutate,
    favorites: data?.favorites ?? [],
    total: data?.total ?? 0,
    isLoading,
    usingCachedData,
  };
}
