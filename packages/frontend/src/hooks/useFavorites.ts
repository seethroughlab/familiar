/**
 * Hook for managing favorites with optimistic updates.
 * Uses React Query as the single source of truth for favorites state.
 *
 * **Online only (ADR-0071 point 2).** This used to cache favorites in Dexie, fall back to that
 * cache when the server was unreachable, and queue a toggle for later sync. All three are gone
 * with the offline stack: the surface that renders this is the embedded Discover page inside a
 * native app, which registers a null audio engine and never plays, and whose host downloads
 * through a background `URLSession` (ADR-0009). A favourite toggled with no server is now an
 * error the caller sees, not an action queued for a sync nothing would run.
 */
import { useMemo, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { favoritesApi, type FavoriteTrack, type FavoritesListResponse } from '../api';
import { STALE_TIME } from '../api/queryDefaults';
import { queryKeys } from '../api/queryKeys';

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
}

/**
 * Hook for managing favorites with shared state and optimistic updates.
 * Fetches all favorites once and provides O(1) lookups for heart icon state.
 */
export function useFavorites(): UseFavoritesResult {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.favorites.all,
    queryFn: () => favoritesApi.list(10000, 0), // Get all favorites
    staleTime: STALE_TIME.SHORT,
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

  // Toggle mutation with optimistic updates
  const toggleMutation = useMutation({
    mutationFn: (trackId: string) => favoritesApi.toggle(trackId),
    onMutate: async (trackId: string) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: queryKeys.favorites.all });

      // Snapshot previous value
      const previous = queryClient.getQueryData<FavoritesListResponse>(queryKeys.favorites.all);

      // Optimistically update
      queryClient.setQueryData<FavoritesListResponse>(queryKeys.favorites.all, (old) => {
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

      return { previous };
    },
    onError: (_err, _trackId, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.favorites.all, context.previous);
      }
    },
    onSettled: () => {
      // Refetch to ensure consistency
      queryClient.invalidateQueries({ queryKey: queryKeys.favorites.all });
    },
  });

  return {
    favoriteIds,
    isFavorite,
    toggle: toggleMutation.mutate,
    favorites: data?.favorites ?? [],
    total: data?.total ?? 0,
    isLoading,
  };
}
