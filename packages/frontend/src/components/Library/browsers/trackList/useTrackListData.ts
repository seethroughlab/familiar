/**
 * Data hook for the track list browser.
 * Encapsulates useInfiniteQuery, sparse page fetching, computed arrays,
 * column/sort config, and queue filters.
 *
 * Mobile jump state is handled separately by useMobileJumpFetch.
 */
import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { tracksApi } from '../../../../api';
import { queryKeys } from '../../../../api/queryKeys';
import { useColumnStore, getVisibleColumns } from '../../../../stores/columnStore';
import { COLUMN_DEFINITIONS, getAnalysisColumns, COLUMN_MAP } from '../../columnDefinitions';
import { getDownloadedTracksPage } from '../../../../services/libraryCache';
import type { LibraryFilters } from '../../types';
import type { Track } from '../../../../types';

import { createLogger } from '../../../../utils/logger';

const log = createLogger('TrackListData');

export const PAGE_SIZE = 50;

export interface TrackListData {
  // Core data
  allTracksUnfiltered: Track[];
  allTracks: (Track | undefined)[];
  total: number;
  sparsePages: Map<number, Track[]>;

  // Query state
  isLoading: boolean;
  error: Error | null;
  hasNextPage: boolean | undefined;
  isFetchingNextPage: boolean;
  fetchNextPage: () => void;
  handleLoadMore: () => void;

  // Sparse page fetching
  fetchPage: (pageNumber: number) => Promise<void>;
  loadedPagesRef: React.MutableRefObject<Set<number>>;

  // Raw page fetcher (for useMobileJumpFetch and other consumers)
  fetchTracksPage: (page: number) => Promise<{ items: Track[]; total: number; page: number }>;

  // Column/sort info
  visibleColumnIds: string[];
  gridColumns: string;
  needsFeatures: boolean;
  sortField: string | undefined;
  sortOrder: 'asc' | 'desc';

  // Queue filters
  queueFilters: Record<string, string | number | undefined>;
}

export function useTrackListData(
  filters: LibraryFilters,
  offlineTrackIds?: Set<string>,
  isOffline?: boolean,
): TrackListData {
  const columns = useColumnStore((state) => state.columns);
  const sortBy = useColumnStore((state) => state.sortBy);
  const sortOrder = useColumnStore((state) => state.sortOrder);

  // Get visible column IDs in order
  const visibleColumnIds = useMemo(() => getVisibleColumns(columns), [columns]);

  // Check if any analysis columns are visible
  const analysisColumnIds = useMemo(
    () => new Set(getAnalysisColumns().map((c) => c.id)),
    []
  );
  const needsFeatures = useMemo(
    () => visibleColumnIds.some((id) => analysisColumnIds.has(id)),
    [visibleColumnIds, analysisColumnIds]
  );

  // Build map of custom column widths
  const columnWidths = useMemo(() => {
    return Object.fromEntries(columns.map(c => [c.id, c.width]));
  }, [columns]);

  // Build grid template columns
  const gridColumns = useMemo(() => {
    const cols: string[] = ['3rem']; // Index column
    cols.push('1fr'); // Title (always visible, flexible)

    for (const colId of visibleColumnIds) {
      const customWidth = columnWidths[colId];
      if (customWidth != null) {
        cols.push(`${customWidth}px`);
      } else {
        const colDef = COLUMN_DEFINITIONS.find((d) => d.id === colId);
        cols.push(colDef?.width || '1fr');
      }
    }

    cols.push('3rem', '3rem'); // Favorite, Offline
    return cols.join(' ');
  }, [visibleColumnIds, columnWidths]);

  // Get the sortField from column definition (may differ from column ID)
  // 'title' is a special case since it's not in COLUMN_DEFINITIONS (always visible)
  const sortField = useMemo(() => {
    if (!sortBy) return undefined;
    if (sortBy === 'title') return 'title';
    const colDef = COLUMN_MAP.get(sortBy);
    return colDef?.sortField;
  }, [sortBy]);

  // Page fetcher with offline fallback
  const fetchTracksPage = useCallback(
    async (pageNumber: number) => {
      const params = {
        search: filters.search,
        artist: filters.artist,
        album: filters.album,
        year_from: filters.yearFrom,
        year_to: filters.yearTo,
        energy_min: filters.energyMin,
        energy_max: filters.energyMax,
        valence_min: filters.valenceMin,
        valence_max: filters.valenceMax,
        fx: filters.fx,
        fx_min: filters.fxMin,
        fx_max: filters.fxMax,
        fy: filters.fy,
        fy_min: filters.fyMin,
        fy_max: filters.fyMax,
        page: pageNumber,
        page_size: PAGE_SIZE,
        include_features: needsFeatures,
        sort_by: sortField,
        sort_order: sortOrder,
      } as const;

      try {
        return await tracksApi.list(params);
      } catch (error) {
        if (isOffline) {
          return await getDownloadedTracksPage(params);
        }
        throw error;
      }
    },
    [filters.search, filters.artist, filters.album, filters.yearFrom, filters.yearTo,
      filters.energyMin, filters.energyMax, filters.valenceMin, filters.valenceMax,
      filters.fx, filters.fxMin, filters.fxMax, filters.fy, filters.fyMin, filters.fyMax,
      needsFeatures, sortField, sortOrder, isOffline]
  );

  const {
    data,
    isLoading,
    error,
    hasNextPage,
    fetchNextPage: fetchNextPageRaw,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: queryKeys.tracks.list({
      search: filters.search,
      artist: filters.artist,
      album: filters.album,
      yearFrom: filters.yearFrom,
      yearTo: filters.yearTo,
      energyMin: filters.energyMin,
      energyMax: filters.energyMax,
      valenceMin: filters.valenceMin,
      valenceMax: filters.valenceMax,
      fx: filters.fx,
      fxMin: filters.fxMin,
      fxMax: filters.fxMax,
      fy: filters.fy,
      fyMin: filters.fyMin,
      fyMax: filters.fyMax,
      include_features: needsFeatures,
      sortBy: sortField,
      sortOrder,
      offline: isOffline,
    }),
    queryFn: ({ pageParam = 1 }) => fetchTracksPage(pageParam),
    getNextPageParam: (lastPage) => {
      const totalPages = Math.ceil(lastPage.total / PAGE_SIZE);
      return lastPage.page < totalPages ? lastPage.page + 1 : undefined;
    },
    initialPageParam: 1,
  });

  const fetchNextPage = useCallback(() => {
    fetchNextPageRaw();
  }, [fetchNextPageRaw]);

  const handleLoadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Track which pages we've loaded (either from infinite query or direct fetch)
  const loadedPagesRef = useRef<Set<number>>(new Set([1]));
  const [sparsePages, setSparsePages] = useState<Map<number, Track[]>>(new Map());

  // Direct page fetching for sparse loading (when jumping to far indices)
  const fetchPage = useCallback(async (pageNumber: number) => {
    if (loadedPagesRef.current.has(pageNumber)) return;

    loadedPagesRef.current.add(pageNumber); // Mark as loading to prevent duplicates

    try {
      const result = await fetchTracksPage(pageNumber);

      setSparsePages(prev => new Map(prev).set(pageNumber, result.items));
    } catch (error) {
      // Remove from loaded set so it can be retried
      loadedPagesRef.current.delete(pageNumber);
      log.error(`Failed to fetch page ${pageNumber}:`, error);
    }
  }, [fetchTracksPage]);

  // Reset sparse pages and loaded tracking when filters or sort changes
  useEffect(() => {
    loadedPagesRef.current = new Set([1]);
    setSparsePages(new Map());
  }, [filters.search, filters.artist, filters.album, filters.yearFrom, filters.yearTo,
      filters.energyMin, filters.energyMax, filters.valenceMin, filters.valenceMax,
      filters.fx, filters.fxMin, filters.fxMax, filters.fy, filters.fyMin, filters.fyMax,
      sortField, sortOrder]);

  // Track which pages came from infinite query
  useEffect(() => {
    if (data?.pages) {
      data.pages.forEach(page => loadedPagesRef.current.add(page.page));
    }
  }, [data?.pages]);

  // Flatten all pages into a single array (filter out any undefined/null entries defensively)
  const allTracksUnfiltered = useMemo(
    () => (data?.pages.flatMap((page) => page.items) ?? []).filter((t): t is Track => t != null),
    [data]
  );

  // Build unified sparse array merging infinite query and direct-fetched pages
  const allTracksSparse = useMemo(() => {
    const totalCount = data?.pages[0]?.total ?? 0;
    if (totalCount === 0) return [];

    const arr: (Track | undefined)[] = new Array(totalCount);

    // Fill from infinite query pages
    data?.pages.forEach(page => {
      const startIdx = (page.page - 1) * PAGE_SIZE;
      page.items.forEach((track, i) => { arr[startIdx + i] = track; });
    });

    // Fill from directly-fetched sparse pages
    sparsePages.forEach((tracks, pageNum) => {
      const startIdx = (pageNum - 1) * PAGE_SIZE;
      tracks.forEach((track, i) => { arr[startIdx + i] = track; });
    });

    return arr;
  }, [data?.pages, sparsePages]);

  const downloadedOnlyActive = filters.downloadedOnly || isOffline;

  // Filter by downloaded tracks if downloadedOnly is enabled or offline mode is active
  // Note: For downloaded-only mode, we use allTracksUnfiltered (dense array)
  // since we can't filter a sparse array by offline status efficiently
  const allTracks = useMemo(() => {
    if (downloadedOnlyActive) {
      if (!offlineTrackIds || offlineTrackIds.size === 0) return [];
      return allTracksUnfiltered.filter(track => offlineTrackIds.has(track.id));
    }
    // Use sparse array for normal mode to support alphabet bar jumping
    return allTracksSparse;
  }, [allTracksUnfiltered, allTracksSparse, downloadedOnlyActive, offlineTrackIds]) as (Track | undefined)[];

  const total = downloadedOnlyActive && offlineTrackIds
    ? allTracks.length
    : data?.pages[0]?.total ?? 0;

  // Build filters object for queue source tracking
  const queueFilters = useMemo(() => ({
    search: filters.search,
    artist: filters.artist,
    album: filters.album,
    year_from: filters.yearFrom,
    year_to: filters.yearTo,
    energy_min: filters.energyMin,
    energy_max: filters.energyMax,
    valence_min: filters.valenceMin,
    valence_max: filters.valenceMax,
    fx: filters.fx,
    fx_min: filters.fxMin,
    fx_max: filters.fxMax,
    fy: filters.fy,
    fy_min: filters.fyMin,
    fy_max: filters.fyMax,
    sort_by: sortField,
    sort_order: sortOrder,
  }), [filters, sortField, sortOrder]);

  return {
    allTracksUnfiltered,
    allTracks,
    total,
    sparsePages,
    isLoading,
    error: error as Error | null,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    handleLoadMore,
    fetchPage,
    loadedPagesRef,
    fetchTracksPage,
    visibleColumnIds,
    gridColumns,
    needsFeatures,
    sortField,
    sortOrder,
    queueFilters,
  };
}
