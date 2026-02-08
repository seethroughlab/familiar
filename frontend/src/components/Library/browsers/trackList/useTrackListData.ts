/**
 * Data hook for the track list browser.
 * Encapsulates useInfiniteQuery, sparse page fetching, computed arrays,
 * and mobile jump state.
 */
import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { tracksApi } from '../../../../api/client';
import { useColumnStore, getVisibleColumns } from '../../../../stores/columnStore';
import { COLUMN_DEFINITIONS, getAnalysisColumns, COLUMN_MAP } from '../../columnDefinitions';
import type { LibraryFilters } from '../../types';
import type { Track } from '../../../../types';

import { createLogger } from '../../../../utils/logger';

const log = createLogger('TrackListData');

export const PAGE_SIZE = 50;

export interface MobileJumpState {
  letter: string;
  tracks: Track[];
  nextPage: number;
  hasMore: boolean;
  isLoading: boolean;
}

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

  // Column/sort info
  visibleColumnIds: string[];
  gridColumns: string;
  needsFeatures: boolean;
  sortField: string | undefined;
  sortOrder: 'asc' | 'desc';

  // Queue filters
  queueFilters: Record<string, string | number | undefined>;

  // Mobile jump state
  mobileJump: MobileJumpState | null;
  setMobileJump: React.Dispatch<React.SetStateAction<MobileJumpState | null>>;
  mobileTracks: Track[];
  mobileHasMore: boolean;
  mobileLoadMore: () => void;
  mobileIsLoading: boolean;
  handleMobileJumpLoadMore: () => Promise<void>;
}

export function useTrackListData(
  filters: LibraryFilters,
  offlineTrackIds?: Set<string>,
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

  const {
    data,
    isLoading,
    error,
    hasNextPage,
    fetchNextPage: fetchNextPageRaw,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: [
      'tracks',
      {
        search: filters.search,
        artist: filters.artist,
        album: filters.album,
        yearFrom: filters.yearFrom,
        yearTo: filters.yearTo,
        energyMin: filters.energyMin,
        energyMax: filters.energyMax,
        valenceMin: filters.valenceMin,
        valenceMax: filters.valenceMax,
        include_features: needsFeatures,
        sortBy: sortField,
        sortOrder,
      },
    ],
    queryFn: ({ pageParam = 1 }) =>
      tracksApi.list({
        search: filters.search,
        artist: filters.artist,
        album: filters.album,
        year_from: filters.yearFrom,
        year_to: filters.yearTo,
        energy_min: filters.energyMin,
        energy_max: filters.energyMax,
        valence_min: filters.valenceMin,
        valence_max: filters.valenceMax,
        page: pageParam,
        page_size: PAGE_SIZE,
        include_features: needsFeatures,
        sort_by: sortField,
        sort_order: sortOrder,
      }),
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
      const result = await tracksApi.list({
        page: pageNumber,
        page_size: PAGE_SIZE,
        search: filters.search,
        artist: filters.artist,
        album: filters.album,
        year_from: filters.yearFrom,
        year_to: filters.yearTo,
        energy_min: filters.energyMin,
        energy_max: filters.energyMax,
        valence_min: filters.valenceMin,
        valence_max: filters.valenceMax,
        include_features: needsFeatures,
        sort_by: sortField,
        sort_order: sortOrder,
      });

      setSparsePages(prev => new Map(prev).set(pageNumber, result.items));
    } catch (error) {
      // Remove from loaded set so it can be retried
      loadedPagesRef.current.delete(pageNumber);
      log.error(`Failed to fetch page ${pageNumber}:`, error);
    }
  }, [filters.search, filters.artist, filters.album, filters.yearFrom, filters.yearTo,
      filters.energyMin, filters.energyMax, filters.valenceMin, filters.valenceMax, needsFeatures,
      sortField, sortOrder]);

  // Reset sparse pages and loaded tracking when filters or sort changes
  useEffect(() => {
    loadedPagesRef.current = new Set([1]);
    setSparsePages(new Map());
  }, [filters.search, filters.artist, filters.album, filters.yearFrom, filters.yearTo,
      filters.energyMin, filters.energyMax, filters.valenceMin, filters.valenceMax,
      sortField, sortOrder]);

  // Track which pages came from infinite query
  useEffect(() => {
    if (data?.pages) {
      data.pages.forEach(page => loadedPagesRef.current.add(page.page));
    }
  }, [data?.pages]);

  // Flatten all pages into a single array
  const allTracksUnfiltered = useMemo(
    () => data?.pages.flatMap((page) => page.items) ?? [],
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

  // Filter by downloaded tracks if downloadedOnly is enabled
  // Note: For downloaded-only mode, we use allTracksUnfiltered (dense array)
  // since we can't filter a sparse array by offline status efficiently
  const allTracks = useMemo(() => {
    if (filters.downloadedOnly && offlineTrackIds && offlineTrackIds.size > 0) {
      return allTracksUnfiltered.filter(track => offlineTrackIds.has(track.id));
    }
    // Use sparse array for normal mode to support alphabet bar jumping
    return allTracksSparse;
  }, [allTracksUnfiltered, allTracksSparse, filters.downloadedOnly, offlineTrackIds]) as (Track | undefined)[];

  const total = filters.downloadedOnly && offlineTrackIds
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
    sort_by: sortField,
    sort_order: sortOrder,
  }), [filters, sortField, sortOrder]);

  // Mobile jump-fetch state: when a letter is tapped on mobile, we fetch just that page
  // and render from there instead of loading all pages from 1 to N.
  const [mobileJump, setMobileJump] = useState<MobileJumpState | null>(null);

  const handleMobileJumpLoadMore = useCallback(async () => {
    if (!mobileJump || mobileJump.isLoading || !mobileJump.hasMore) return;

    setMobileJump(prev => prev ? { ...prev, isLoading: true } : null);

    try {
      const result = await tracksApi.list({
        page: mobileJump.nextPage,
        page_size: PAGE_SIZE,
        search: filters.search,
        artist: filters.artist,
        album: filters.album,
        year_from: filters.yearFrom,
        year_to: filters.yearTo,
        energy_min: filters.energyMin,
        energy_max: filters.energyMax,
        valence_min: filters.valenceMin,
        valence_max: filters.valenceMax,
        include_features: needsFeatures,
        sort_by: sortField,
        sort_order: sortOrder,
      });

      const totalPages = Math.ceil(result.total / PAGE_SIZE);
      setMobileJump(prev => prev ? {
        ...prev,
        tracks: [...prev.tracks, ...result.items],
        nextPage: prev.nextPage + 1,
        hasMore: prev.nextPage < totalPages,
        isLoading: false,
      } : null);
    } catch (err) {
      log.error('Failed to load more jump tracks:', err);
      setMobileJump(prev => prev ? { ...prev, isLoading: false } : null);
    }
  }, [mobileJump, filters, needsFeatures, sortField, sortOrder]);

  // Reset mobileJump when filters/sort change
  useEffect(() => {
    setMobileJump(null);
  }, [filters.search, filters.artist, filters.album, filters.yearFrom, filters.yearTo,
      filters.energyMin, filters.energyMax, filters.valenceMin, filters.valenceMax,
      sortField, sortOrder]);

  // Unified mobile rendering: use jump tracks or regular infinite query
  const mobileTracks = mobileJump?.tracks ?? allTracksUnfiltered;
  const mobileHasMore = mobileJump ? mobileJump.hasMore : (hasNextPage ?? false);
  const mobileLoadMore = mobileJump ? handleMobileJumpLoadMore : handleLoadMore;
  const mobileIsLoading = mobileJump?.isLoading ?? isFetchingNextPage;

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
    visibleColumnIds,
    gridColumns,
    needsFeatures,
    sortField,
    sortOrder,
    queueFilters,
    mobileJump,
    setMobileJump,
    mobileTracks,
    mobileHasMore,
    mobileLoadMore,
    mobileIsLoading,
    handleMobileJumpLoadMore,
  };
}
