/**
 * useOfflineQuery - A wrapper around useQuery with offline-first pattern.
 *
 * This hook provides automatic caching and offline fallback for React Query.
 * When online, it fetches fresh data and caches it.
 * When offline, it returns cached data.
 */
import { useState, useCallback, useEffect } from 'react';
import { STALE_TIME, offlineAwareRetry } from '../api/queryDefaults';
import { createLogger } from '../utils/logger';
import {
  useQuery,
  type UseQueryOptions,
} from '@tanstack/react-query';
import { useOfflineStatus } from './useOfflineStatus';

const log = createLogger('OfflineQuery');

export type CacheStatus = 'fresh' | 'stale' | 'offline' | 'none';

export interface UseOfflineQueryOptions<TData, TError = Error>
  extends Omit<UseQueryOptions<TData, TError>, 'queryFn'> {
  /** Function to fetch data from the network */
  queryFn: () => Promise<TData>;
  /** Function to save data to cache */
  cacheData?: (data: TData) => Promise<void>;
  /** Function to load data from cache */
  loadCachedData?: () => Promise<TData | null>;
  /** Max age in milliseconds before cache is considered stale (default: 24 hours) */
  maxAge?: number;
}

export interface UseOfflineQueryResult<TData, TError = Error> {
  /** The query data */
  data: TData | undefined;
  /** Whether the query is loading */
  isLoading: boolean;
  /** Any error that occurred */
  error: TError | null;
  /** Whether we're using cached data */
  isUsingCache: boolean;
  /** Cache status: fresh, stale, offline, or none */
  cacheStatus: CacheStatus;
  /** Whether the app is offline */
  isOffline: boolean;
  /** Refetch the data */
  refetch: () => Promise<unknown>;
}

/**
 * Hook that provides offline-first data fetching with automatic caching.
 *
 * @example
 * ```tsx
 * const { data, isLoading, cacheStatus } = useOfflineQuery({
 *   queryKey: ['playlist', playlistId],
 *   queryFn: () => playlistsApi.get(playlistId),
 *   cacheData: (data) => playlistCache.cachePlaylist(data),
 *   loadCachedData: () => playlistCache.getCachedPlaylist(playlistId),
 * });
 * ```
 */
export function useOfflineQuery<TData, TError = Error>(
  options: UseOfflineQueryOptions<TData, TError>
): UseOfflineQueryResult<TData, TError> {
  const {
    queryFn,
    cacheData,
    loadCachedData,
    maxAge: _maxAge = 24 * 60 * 60 * 1000, // 24 hours
    ...queryOptions
  } = options;

  const { isOffline } = useOfflineStatus();
  const [isUsingCache, setIsUsingCache] = useState(false);
  const [cacheStatus, setCacheStatus] = useState<CacheStatus>('none');

  // Wrap the query function to handle caching and offline fallback
  const wrappedQueryFn = useCallback(async (): Promise<TData> => {
    // Try network first if online
    if (!isOffline) {
      try {
        const data = await queryFn();
        setIsUsingCache(false);
        setCacheStatus('fresh');

        // Cache the successful response
        if (cacheData) {
          await cacheData(data).catch((err) => {
            log.warn('Failed to cache data:', err);
          });
        }

        return data;
      } catch (error) {
        // Network failed, try cache even if "online"
        log.warn('Network request failed, trying cache:', error);
      }
    }

    // Try to load from cache
    if (loadCachedData) {
      const cached = await loadCachedData();
      if (cached !== null) {
        setIsUsingCache(true);
        setCacheStatus(isOffline ? 'offline' : 'stale');
        return cached;
      }
    }

    // No cache available
    setCacheStatus('none');
    throw new Error('No data available (offline with no cache)');
  }, [isOffline, queryFn, cacheData, loadCachedData]);

  const query = useQuery<TData, TError>({
    ...queryOptions,
    queryFn: wrappedQueryFn,
    retry: offlineAwareRetry(isOffline, typeof queryOptions.retry === 'number' ? queryOptions.retry : 3),
    // Keep stale data available while revalidating
    staleTime: queryOptions.staleTime ?? STALE_TIME.SHORT,
  });

  // Reset cache status when data changes
  useEffect(() => {
    if (query.data && !isOffline && !query.isFetching) {
      setCacheStatus('fresh');
      setIsUsingCache(false);
    }
  }, [query.data, isOffline, query.isFetching]);

  return {
    data: query.data,
    isLoading: query.isLoading,
    error: query.error,
    isUsingCache,
    cacheStatus,
    isOffline,
    refetch: query.refetch,
  };
}

/**
 * Helper to determine if data should be refreshed based on cache age.
 */
export function isCacheStale(
  cachedAt: Date | null | undefined,
  maxAgeMs: number = 24 * 60 * 60 * 1000
): boolean {
  if (!cachedAt) return true;
  const age = Date.now() - cachedAt.getTime();
  return age > maxAgeMs;
}
