/**
 * TrackList Browser - Traditional track list view.
 *
 * Desktop: Uses @tanstack/react-virtual for virtualization, enabling:
 * - Instant scroll-to-index for alphabet bar navigation (works for any index, even unloaded)
 * - Efficient rendering of large lists (only visible rows + overscan are rendered)
 * - Progressive page loading as user scrolls
 *
 * Mobile: Uses intersection observer for simpler infinite scroll.
 *
 * Wraps TrackList with BrowserProps interface for the pluggable browser system.
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useNavigate } from 'react-router-dom';
import { Play, Loader2, Music, FolderOpen, Clock, Disc, ChevronUp, ChevronDown } from 'lucide-react';
import { tracksApi } from '../../../api';
import { useOfflineStatus } from '../../../hooks/useOfflineStatus';
import { usePlayerStore } from '../../../stores/playerStore';
import { useSelectionStore } from '../../../stores/selectionStore';
import { useVisibleTracksStore } from '../../../stores/visibleTracksStore';
import { useTrackContextMenu } from '../../../hooks/useTrackContextMenu';
import { useArtworkPrefetchBatch } from '../../../hooks/useArtworkPrefetch';
import { useScrollContainer } from '../../../hooks/useScrollContainer';
import { useColumnStore } from '../../../stores/columnStore';
import { useColumnResize } from '../../../hooks/useColumnResize';
import { getColumnDef } from '../columnDefinitions';
import { TrackRow } from './trackList/TrackRow';
import { MobileTrackCard } from './trackList/MobileTrackCard';
import { AlbumOfflineButton } from './trackList/AlbumOfflineButton';
import { useTrackListData, PAGE_SIZE } from './trackList/useTrackListData';
import { useMobileJumpFetch } from './trackList/useMobileJumpFetch';
import { useIntersectionObserver } from '../../../hooks/useIntersectionObserver'; // Still used for mobile view
import { registerBrowser, type BrowserProps } from '../types';
import { AlbumArtwork } from '../../AlbumArtwork';
import { AlphabetBar, useAlphabetBar } from '../AlphabetBar';
import type { Track } from '../../../types';
import { resolveTrackRowIntent } from '../../shared/trackRowInteraction';
import { useShuffleWeightStore } from '../../../stores/shuffleWeightStore';

import { createLogger } from '../../../utils/logger';

const log = createLogger('TrackListBrowser');

const ROW_HEIGHT = 40; // Height of each track row in pixels (desktop view)

// Register this browser
registerBrowser(
  {
    id: 'track-list',
    name: 'Tracks',
    description: 'Traditional track list with sortable columns',
    icon: 'List',
    category: 'traditional',
    requiresFeatures: false,
    requiresEmbeddings: false,
  },
  TrackListBrowser
);


export function TrackListBrowser({
  filters,
  selectedTrackIds,
  onSelectTrack,
  onClearSelection,
  onQueueTrack,
  onGoToArtist,
  onGoToAlbum,
  onEditTrack,
  offlineTrackIds,
}: BrowserProps) {
  const { isOffline } = useOfflineStatus();
  const trackListNavigate = useNavigate();
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const shuffle = usePlayerStore((s) => s.shuffle);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const setQueue = usePlayerStore((s) => s.setQueue);
  const setLazyQueue = usePlayerStore((s) => s.setLazyQueue);
  const lazyQueueIds = usePlayerStore((s) => s.lazyQueueIds);
  const selectRange = useSelectionStore((state) => state.selectRange);
  const columns = useColumnStore((state) => state.columns);
  const reorderColumns = useColumnStore((state) => state.reorderColumns);
  const sortBy = useColumnStore((state) => state.sortBy);
  const sortOrder = useColumnStore((state) => state.sortOrder);
  const toggleSort = useColumnStore((state) => state.toggleSort);

  // ── Data hook: query, sparse pages, columns, sort, queue filters ──
  const {
    allTracksUnfiltered,
    allTracks,
    total,
    sparsePages,
    isLoading,
    error,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    handleLoadMore,
    fetchPage,
    loadedPagesRef,
    fetchTracksPage,
    visibleColumnIds,
    gridColumns,
    needsFeatures: _needsFeatures,
    sortField,
    queueFilters,
  } = useTrackListData(filters, offlineTrackIds, isOffline);

  // Context menu (via hook — bulk actions and favorites handled automatically)
  const { handleContextMenu, openContextMenu, contextMenuElement } = useTrackContextMenu({
    onPlay: (track) => {
      const index = allTracksUnfiltered.findIndex((t) => t.id === track.id);
      if (index !== -1) handlePlayTrack(track, index);
    },
    onQueue: (track) => onQueueTrack(track.id),
    onGoToArtist: (track) => {
      if (track.artist) onGoToArtist(track.artist);
    },
    onGoToAlbum: (track) => {
      if (track.album) {
        const albumArtist = track.album_artist || track.artist;
        if (albumArtist) onGoToAlbum(albumArtist, track.album);
      }
    },
    onExploreSimilarArtists: (track) => {
      if (track.artist) handleExploreSimilarArtists(track.artist);
    },
    onToggleSelect: (track) => onSelectTrack(track.id, true),
    selectedTrackIds,
    onClearSelection,
    onEditMetadata: (track) => onEditTrack(track.id),
    resolveSelectedTracks: (ids) => allTracksUnfiltered.filter(t => ids.has(t.id)),
  });

  // Navigate to ego music map with artist
  const handleExploreSimilarArtists = useCallback(
    (artistName: string) => {
      trackListNavigate(`/library/music-map?center=${encodeURIComponent(artistName)}`);
    },
    [trackListNavigate]
  );

  // Drag & drop state for columns
  const [draggedColId, setDraggedColId] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null);

  // Resize state for columns
  const { resizingColumnId, handleResizeStart, resetColumnWidth } = useColumnResize();

  // Drag handlers for column reordering
  const handleDragStart = (colId: string) => {
    setDraggedColId(colId);
  };

  const handleDragOver = (e: React.DragEvent, colId: string) => {
    e.preventDefault();
    if (draggedColId && draggedColId !== colId) {
      setDropTargetId(colId);
    }
  };

  const handleDragLeave = () => {
    setDropTargetId(null);
  };

  const handleDrop = (e: React.DragEvent, targetColId: string) => {
    e.preventDefault();
    if (draggedColId && draggedColId !== targetColId) {
      const fromIndex = columns.findIndex((c) => c.id === draggedColId);
      const toIndex = columns.findIndex((c) => c.id === targetColId);
      if (fromIndex !== -1 && toIndex !== -1) {
        reorderColumns(fromIndex, toIndex);
      }
    }
    setDraggedColId(null);
    setDropTargetId(null);
  };

  const handleDragEnd = () => {
    setDraggedColId(null);
    setDropTargetId(null);
  };


  // Desktop scroll container ref for virtualizer
  const desktopScrollRef = useRef<HTMLDivElement>(null);

  // Virtualizer for desktop view - enables instant scrollToIndex for any position
  const virtualizer = useVirtualizer({
    count: total,
    getScrollElement: () => desktopScrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 10, // Render 10 extra items above/below viewport
  });

  // Fetch pages containing visible items (supports sparse/targeted loading for alphabet bar jumps)
  useEffect(() => {
    const virtualItems = virtualizer.getVirtualItems();
    if (virtualItems.length === 0) return;

    const firstIdx = virtualItems[0].index;
    const lastIdx = virtualItems[virtualItems.length - 1].index;

    // Calculate which pages contain visible items
    const firstPage = Math.floor(firstIdx / PAGE_SIZE) + 1;
    const lastPage = Math.floor(lastIdx / PAGE_SIZE) + 1;

    // Find missing pages in visible range
    const missingPages: number[] = [];
    for (let p = firstPage; p <= lastPage; p++) {
      if (!loadedPagesRef.current.has(p)) {
        missingPages.push(p);
      }
    }

    if (missingPages.length > 0) {
      // Fetch only the needed pages (sparse loading)
      missingPages.forEach(p => fetchPage(p));
    } else if (lastIdx >= total - 1 && hasNextPage && !isFetchingNextPage) {
      // Normal sequential loading at end of loaded data
      fetchNextPage();
    }
  }, [virtualizer.getVirtualItems(), hasNextPage, isFetchingNextPage, total, fetchNextPage, fetchPage]);

  // Track when user intentionally navigates (e.g., alphabet bar click)
  // Used to suppress auto-scroll to current track
  const userNavigatedRef = useRef(false);
  const userNavigatedTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Callback for alphabet bar to use virtualizer's scrollToIndex
  const scrollToIndex = useCallback((index: number) => {
    // Mark that user intentionally navigated - suppress auto-scroll for 2 seconds
    userNavigatedRef.current = true;
    if (userNavigatedTimeoutRef.current) {
      clearTimeout(userNavigatedTimeoutRef.current);
    }
    userNavigatedTimeoutRef.current = setTimeout(() => {
      userNavigatedRef.current = false;
    }, 2000);

    virtualizer.scrollToIndex(index, { align: 'start', behavior: 'auto' });
  }, [virtualizer]);

  // Track the current track ID we're scrolling to, for cancellation
  const scrollTargetRef = useRef<string | null>(null);
  const scrollDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Track the previous track ID to avoid re-scrolling on filter/data changes
  const prevTrackIdRef = useRef<string | null>(null);

  // Auto-scroll to current track when it changes (desktop only)
  useEffect(() => {
    if (!currentTrack) {
      scrollTargetRef.current = null;
      return;
    }

    const trackId = currentTrack.id;

    // Only scroll if track actually changed (not just re-render from filter/data changes)
    if (trackId === prevTrackIdRef.current) {
      return;
    }

    // Skip auto-scroll if user recently navigated (e.g., clicked alphabet bar)
    if (userNavigatedRef.current) {
      prevTrackIdRef.current = trackId; // Still update ref to avoid scrolling later
      return;
    }

    prevTrackIdRef.current = trackId;
    scrollTargetRef.current = trackId;

    // Clear any pending scroll (handles rapid track skipping)
    if (scrollDebounceRef.current) {
      clearTimeout(scrollDebounceRef.current);
    }

    const scrollToCurrentTrack = async (targetId: string) => {
      // 1. Try local lookup in sparse array first (preserves true indices)
      // Read allTracks inside callback to avoid dependency
      let localIndex = -1;
      for (let i = 0; i < allTracks.length; i++) {
        if (allTracks[i]?.id === targetId) {
          localIndex = i;
          break;
        }
      }

      if (localIndex >= 0) {
        virtualizer.scrollToIndex(localIndex, { align: 'center', behavior: 'auto' });
        return; // Found locally, no API needed
      }

      // 2. Track not in loaded data - need server lookup
      // Read filters inside callback to avoid dependency
      try {
        const { index } = await tracksApi.getIndex(targetId, {
          search: filters.search,
          artist: filters.artist,
          album: filters.album,
          genre: filters.genre,
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
        });

        // Check if we're still trying to scroll to this track (handles rapid skipping)
        if (scrollTargetRef.current !== targetId) return;

        if (index >= 0) {
          virtualizer.scrollToIndex(index, { align: 'center', behavior: 'auto' });
        }
      } catch {
        // Track might not match current filters - ignore silently
      }
    };

    // Debounce: wait 150ms before scrolling (allows rapid skipping to settle)
    scrollDebounceRef.current = setTimeout(() => {
      // Double-check user hasn't navigated during debounce period
      if (!userNavigatedRef.current) {
        scrollToCurrentTrack(trackId);
      }
    }, 150);

    return () => {
      if (scrollDebounceRef.current) {
        clearTimeout(scrollDebounceRef.current);
      }
    };
  }, [currentTrack?.id, virtualizer]);

  // Alphabet bar for quick navigation
  const {
    letterIndex,
    activeLetter,
    isVisible: isAlphabetBarVisible,
    isJumping,
    jumpToLetter,
    setActiveLetter,
  } = useAlphabetBar({
    entityType: 'tracks',
    sortField: 'artist', // TrackListBrowser sorts by artist by default
    filters: {
      search: filters.search,
      artist: filters.artist,
      album: filters.album,
    },
    total,
    pageSize: PAGE_SIZE,
    fetchNextPage,
    hasNextPage: hasNextPage ?? false,
    loadedItemCount: total, // With sparse loading, array length equals total
    scrollToIndex, // Use virtualizer's scrollToIndex for instant navigation
  });

  // Mobile jump-fetch: letter tap loads target page directly instead of all pages 1..N
  const {
    mobileJump,
    prevSentinelReady,
    handleMobileJumpToLetter,
    handleMobileJumpLoadMore,
    handleMobileJumpLoadPrevious,
  } = useMobileJumpFetch({
    letterIndex,
    pageSize: PAGE_SIZE,
    fetchTracksPage,
    setActiveLetter,
    resetDeps: [
      filters.search, filters.artist, filters.album, filters.yearFrom, filters.yearTo,
      filters.energyMin, filters.energyMax, filters.valenceMin, filters.valenceMax,
      filters.fx, filters.fxMin, filters.fxMax, filters.fy, filters.fyMin, filters.fyMax,
      sortField, sortOrder,
    ],
  });

  // Letter select routing: mobile uses jump-fetch, desktop uses virtualizer
  const handleLetterSelect = useCallback((letter: string) => {
    if (window.innerWidth < 768) {
      handleMobileJumpToLetter(letter);
    } else {
      jumpToLetter(letter);
    }
  }, [handleMobileJumpToLetter, jumpToLetter]);

  // Unified mobile rendering: use jump tracks or regular infinite query
  const mobileTracks = mobileJump?.tracks ?? allTracksUnfiltered;
  const mobileHasMore = mobileJump ? mobileJump.hasMore : (hasNextPage ?? false);
  const mobileLoadMore = mobileJump ? handleMobileJumpLoadMore : handleLoadMore;
  const mobileIsLoading = mobileJump?.isLoading ?? isFetchingNextPage;

  // Mobile infinite scroll sentinel — uses unified values so it works in both
  // normal mode and jump-fetch mode
  const mobileSentinelRef = useIntersectionObserver({
    onIntersect: mobileLoadMore,
    enabled: mobileHasMore && !mobileIsLoading,
  });

  // Top sentinel for loading earlier pages after a mobile jump
  const mobilePrevSentinelRef = useIntersectionObserver({
    onIntersect: handleMobileJumpLoadPrevious,
    enabled: prevSentinelReady && !!mobileJump?.hasPrevious && !mobileJump?.isLoadingPrev,
  });

  // Mobile virtualizer — uses the shared AppShell scroll container
  const scrollContainerRef = useScrollContainer();
  const mobileVirtualizer = useVirtualizer({
    count: mobileTracks.length,
    getScrollElement: () => scrollContainerRef?.current ?? null,
    estimateSize: () => 64,
    overscan: 10,
    enabled: !!scrollContainerRef,
  });

  // Update visible tracks store when tracks change (for LLM context)
  // Debounced to avoid O(n) .map() on every page load during rapid scrolling
  const setVisibleTracks = useVisibleTracksStore((state) => state.setVisibleTracks);
  const prevTrackCountRef = useRef(0);
  const prevFiltersRef = useRef(filters);
  useEffect(() => {
    // Short-circuit: skip if count and filters haven't changed
    if (
      allTracksUnfiltered.length === prevTrackCountRef.current &&
      filters === prevFiltersRef.current
    ) {
      return;
    }

    const timer = setTimeout(() => {
      if (allTracksUnfiltered.length > 0) {
        prevTrackCountRef.current = allTracksUnfiltered.length;
        prevFiltersRef.current = filters;

        const visibleTracks = allTracksUnfiltered.map((t) => ({
          id: t.id,
          title: t.title || 'Unknown Title',
          artist: t.artist || 'Unknown Artist',
          album: t.album || 'Unknown Album',
        }));

        // Build filter description for LLM context
        const filterParts: string[] = [];
        if (filters.search) filterParts.push(`search: "${filters.search}"`);
        if (filters.artist) filterParts.push(`artist: "${filters.artist}"`);
        if (filters.album) filterParts.push(`album: "${filters.album}"`);
        const filterDescription = filterParts.length > 0
          ? `Filtered by ${filterParts.join(', ')}`
          : 'All tracks';

        setVisibleTracks(visibleTracks, total, filterDescription);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [allTracksUnfiltered, total, filters, setVisibleTracks]);

  // Prefetch artwork for visible albums (use dense array)
  const prefetchArtworkBatch = useArtworkPrefetchBatch();
  useEffect(() => {
    if (allTracksUnfiltered.length > 0) {
      prefetchArtworkBatch(
        allTracksUnfiltered.map((t) => ({
          artist: t.artist,
          album: t.album,
          trackId: t.id,
        }))
      );
    }
  }, [allTracksUnfiltered, prefetchArtworkBatch]);

  // Threshold for using lazy queue mode vs loading all tracks
  const LAZY_QUEUE_THRESHOLD = 200;

  const handlePlayTrack = useCallback(
    async (track: Track, index: number) => {
      if (currentTrack?.id === track.id) {
        setIsPlaying(!isPlaying);
        return;
      }

      // For large libraries (Tracks view), always use lazy queue mode
      // This ensures shuffle considers ALL tracks, not just loaded ones
      if (total >= LAZY_QUEUE_THRESHOLD) {
        setIsLoadingPlayAll(true);
        // Optimistic: show track as loading immediately, before getIds
        usePlayerStore.setState({
          currentTrack: track,
          isPlaying: true,
          currentTime: 0,
          isLoadingAudio: true,
        });
        try {
          const weightState = useShuffleWeightStore.getState();
          const useWeighted = shuffle && weightState.enabled && weightState.activePreset;
          const response = await tracksApi.getIds({
            shuffle: shuffle && !useWeighted,
            shuffle_preset: useWeighted ? weightState.activePreset! : undefined,
            start_with: track.id,
            ...queueFilters,
          });
          if (response.ids.length > 0) {
            await setLazyQueue(response.ids, {
              type: 'library',
              filters: queueFilters,
            }, { initialTrack: track });
          } else {
            // No tracks matched — clean up optimistic state
            usePlayerStore.setState({ currentTrack: null, isPlaying: false, isLoadingAudio: false });
          }
        } catch (error) {
          log.error('Failed to play track:', error);
          usePlayerStore.setState({ currentTrack: null, isPlaying: false, isLoadingAudio: false });
        } finally {
          setIsLoadingPlayAll(false);
        }
        return;
      }

      if (allTracksUnfiltered.length > 0) {
        // Resolve from the authoritative queue array by ID so mobile sparse/jump lists
        // always start the tapped track, even when their visible index differs.
        const resolvedIndex = allTracksUnfiltered.findIndex((t) => t.id === track.id);
        if (resolvedIndex < 0) {
          log.warn('handlePlayTrack skipped unresolved track', {
            trackId: track.id,
            visibleIndex: index,
            queueLength: allTracksUnfiltered.length,
          });
          return;
        }
        setQueue(allTracksUnfiltered, resolvedIndex);
      }
    },
    [currentTrack, isPlaying, setIsPlaying, allTracksUnfiltered, setQueue, total, shuffle, queueFilters, setLazyQueue]
  );

  const handleRowClick = useCallback(
    (track: Track, e: React.MouseEvent) => {
      const intent = resolveTrackRowIntent({
        isMobile: false,
        shiftKey: e.shiftKey,
        metaKey: e.metaKey,
        ctrlKey: e.ctrlKey,
      });

      if (intent === 'select-range') {
        const allIds = allTracksUnfiltered.map((t) => t.id);
        selectRange(track.id, allIds);
        return;
      }

      onSelectTrack(track.id, intent === 'select-toggle');
    },
    [onSelectTrack, selectRange, allTracksUnfiltered]
  );

  const handleRowDoubleClick = useCallback(
    (track: Track, index: number) => {
      handlePlayTrack(track, index);
    },
    [handlePlayTrack]
  );

  // Track loading state for play all (must be before early returns)
  const [isLoadingPlayAll, setIsLoadingPlayAll] = useState(false);

  const handlePlayAll = useCallback(async () => {
    if (total === 0) return;

    // For large result sets, use lazy queue mode with server-side ordering
    // Pass global shuffle state so server returns shuffled IDs if enabled
    if (total >= LAZY_QUEUE_THRESHOLD) {
      setIsLoadingPlayAll(true);
      try {
        const weightState = useShuffleWeightStore.getState();
        const useWeighted = shuffle && weightState.enabled && weightState.activePreset;
        const response = await tracksApi.getIds({
          shuffle: shuffle && !useWeighted,
          shuffle_preset: useWeighted ? weightState.activePreset! : undefined,
          ...queueFilters,
        });
        if (response.ids.length > 0) {
          await setLazyQueue(response.ids, {
            type: 'library',
            filters: queueFilters,
          });
        }
      } catch (error) {
        log.error('Failed to play all tracks:', error);
      } finally {
        setIsLoadingPlayAll(false);
      }
      return;
    }

    if (allTracksUnfiltered.length > 0) {
      setQueue(allTracksUnfiltered, 0);
    }
  }, [total, shuffle, queueFilters, setLazyQueue, allTracksUnfiltered, setQueue]);

  // Check if currently playing from lazy queue
  const isInLazyQueueMode = lazyQueueIds !== null && lazyQueueIds.length > 0;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-zinc-500">Loading tracks...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-red-500">Error loading tracks</div>
      </div>
    );
  }

  if (total === 0) {
    const hasFilters = filters.search || filters.artist || filters.album;
    return (
      <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
        {hasFilters ? (
          <>
            <Music className="w-12 h-12 mb-4 opacity-50" />
            <p>No tracks match your search</p>
            <p className="text-sm mt-1">Try adjusting your filters</p>
          </>
        ) : (
          <>
            <FolderOpen className="w-12 h-12 mb-4 opacity-50" />
            <p>Your library is empty</p>
            <p className="text-sm mt-1">Add music folders in Settings to get started</p>
          </>
        )}
      </div>
    );
  }

  // Compute album stats from tracks (use dense array for reliable access)
  const isAlbumView = filters.album && allTracksUnfiltered.length > 0;
  const albumStats = isAlbumView ? {
    artist: filters.artist || allTracksUnfiltered[0]?.album_artist || allTracksUnfiltered[0]?.artist || 'Unknown Artist',
    album: filters.album!, // Non-null assertion: isAlbumView guarantees filters.album is defined
    year: allTracksUnfiltered.find(t => t.year)?.year || null,
    trackCount: total,
    totalDuration: allTracksUnfiltered.reduce((sum, t) => sum + (t.duration_seconds || 0), 0),
    firstTrackId: allTracksUnfiltered[0]?.id,
  } : null;

  const formatTotalDuration = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    if (hours > 0) {
      return `${hours}h ${mins}m`;
    }
    return `${mins} min`;
  };

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Album header when viewing an album */}
      {albumStats && (
        <div className="flex items-start gap-4 md:gap-6 p-4 mb-4 bg-zinc-800/30 rounded-lg">
          {/* Album artwork */}
          <div className="w-24 h-24 md:w-40 md:h-40 rounded-lg overflow-hidden flex-shrink-0 shadow-lg">
            <AlbumArtwork
              artist={albumStats.artist}
              album={albumStats.album}
              trackId={albumStats.firstTrackId}
              size="full"
              className="w-full h-full"
            />
          </div>

          {/* Album info */}
          <div className="flex-1 min-w-0 py-1">
            <div className="text-xs text-zinc-400 uppercase tracking-wider mb-1">Album</div>
            <h2 className="text-xl md:text-2xl font-bold truncate mb-2">{albumStats.album}</h2>

            {/* Artist (clickable) */}
            <button
              onClick={() => onGoToArtist(albumStats.artist)}
              className="text-zinc-300 hover:text-white hover:underline truncate block mb-2"
            >
              {albumStats.artist}
            </button>

            {/* Stats row */}
            <div className="flex items-center gap-4 text-sm text-zinc-400">
              {albumStats.year && <span>{albumStats.year}</span>}
              <span className="flex items-center gap-1">
                <Disc className="w-4 h-4" />
                {albumStats.trackCount} tracks
              </span>
              <span className="flex items-center gap-1">
                <Clock className="w-4 h-4" />
                {formatTotalDuration(albumStats.totalDuration)}
              </span>
            </div>

            {/* Play and Download buttons */}
            <div className="mt-4 flex items-center gap-2">
              <button
                onClick={handlePlayAll}
                disabled={isLoadingPlayAll}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded-full transition-colors"
              >
                {isLoadingPlayAll ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Play className="w-4 h-4" fill="currentColor" />
                )}
                Play
              </button>
              <AlbumOfflineButton
                tracks={allTracksUnfiltered.map(t => ({ id: t.id }))}
                artist={albumStats.artist}
                album={albumStats.album}
              />
            </div>
          </div>
        </div>
      )}

      {/* Toolbar for non-album view */}
      {!albumStats && total > 0 && (
        <div className="flex items-center justify-between px-4 py-3 mb-2">
          <div className="text-sm text-zinc-400">
            {total.toLocaleString()} tracks
            {isInLazyQueueMode && (
              <span className="ml-2 text-green-500">
                • Playing all
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handlePlayAll}
              disabled={isLoadingPlayAll}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 rounded-full transition-colors"
              title="Play all tracks"
            >
              {isLoadingPlayAll ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Play className="w-3.5 h-3.5" fill="currentColor" />
              )}
              <span className="hidden sm:inline">Play</span>
            </button>
          </div>
        </div>
      )}

      {/* Mobile view - virtualized card layout (visible below md breakpoint) */}
      {/* Uses shared scroll container from AppShell via context */}
      <div className="md:hidden">
        {mobileJump?.hasPrevious && (
          <div ref={mobilePrevSentinelRef} className="h-4" />
        )}
        {mobileJump?.isLoadingPrev && (
          <div className="flex items-center justify-center py-4">
            <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
          </div>
        )}
        {scrollContainerRef ? (
          // Virtualized rendering when scroll container is available
          <div style={{ height: mobileVirtualizer.getTotalSize(), position: 'relative' }}>
            {mobileVirtualizer.getVirtualItems().map((virtualRow) => {
              const index = virtualRow.index;
              const track = mobileTracks[index];
              if (!track) return null;
              return (
                <div
                  key={track.id}
                  data-index={virtualRow.index}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                >
                  <MobileTrackCard
                    track={track}
                    index={index}
                    isCurrentTrack={currentTrack?.id === track.id}
                    isPlaying={currentTrack?.id === track.id && isPlaying}
                    isSelected={false}
                    onPlay={() => handlePlayTrack(track, index)}
                    onClick={() => {
                      onClearSelection();
                      handlePlayTrack(track, index);
                    }}
                    onContextMenu={(e) => handleContextMenu(track, e)}
                    onLongPress={(position) => openContextMenu(track, position)}
                  />
                </div>
              );
            })}
          </div>
        ) : (
          // Fallback: non-virtualized rendering (e.g. tests without AppShell)
          mobileTracks.map((track, index) => track ? (
            <MobileTrackCard
              key={track.id}
              track={track}
              index={index}
              isCurrentTrack={currentTrack?.id === track.id}
              isPlaying={currentTrack?.id === track.id && isPlaying}
              isSelected={false}
              onPlay={() => handlePlayTrack(track, index)}
              onClick={() => {
                onClearSelection();
                handlePlayTrack(track, index);
              }}
              onContextMenu={(e) => handleContextMenu(track, e)}
              onLongPress={(position) => openContextMenu(track, position)}
            />
          ) : null)
        )}
        {/* Loading indicator for infinite scroll */}
        {mobileIsLoading && (
          <div className="flex items-center justify-center py-4">
            <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
          </div>
        )}
        {/* Sentinel for infinite scroll (both normal and jump mode) */}
        {mobileHasMore && <div ref={mobileSentinelRef} className="h-4" />}
        {/* Mobile footer */}
        <div className="px-4 py-4 text-sm text-zinc-500">
          {mobileJump
            ? `Showing from ${mobileJump.letter} · ${mobileTracks.length} of ${total.toLocaleString()} tracks`
            : `${mobileTracks.length} of ${total.toLocaleString()} tracks`
          }
        </div>
      </div>

      {/* Desktop view - virtualized grid layout (visible at md and above) */}
      {/* flex-1 + min-h-0 (not h-full) so the scroll area takes the space *remaining*
          after the album header / toolbar siblings — h-full ignores them and pushes
          the list's bottom (and footer) behind the fixed player bar. */}
      <div className="hidden md:flex md:flex-col md:flex-1 md:min-h-0">
        {/* Header - fixed outside scroll area */}
        <div
          className="grid gap-4 px-4 py-2 text-sm text-zinc-400 border-b border-zinc-800 flex-shrink-0"
          style={{ gridTemplateColumns: gridColumns }}
        >
          <div
            onClick={() => toggleSort('trackNum')}
            className={`cursor-pointer hover:text-white flex items-center gap-1 ${
              sortBy === 'trackNum' ? 'text-white' : ''
            }`}
            title="Click to sort by track number"
          >
            <span>#</span>
            {sortBy === 'trackNum' && (
              sortOrder === 'asc'
                ? <ChevronUp className="w-3 h-3 flex-shrink-0" />
                : <ChevronDown className="w-3 h-3 flex-shrink-0" />
            )}
          </div>
          <div
            onClick={() => toggleSort('title')}
            className={`cursor-pointer hover:text-white flex items-center gap-1 ${
              sortBy === 'title' ? 'text-white' : ''
            }`}
            title="Click to sort by Title"
          >
            <span>Title</span>
            {sortBy === 'title' && (
              sortOrder === 'asc' ? (
                <ChevronUp className="w-3 h-3 flex-shrink-0" />
              ) : (
                <ChevronDown className="w-3 h-3 flex-shrink-0" />
              )
            )}
          </div>
          {visibleColumnIds.map((colId) => {
            const colDef = getColumnDef(colId);
            if (!colDef) return null;
            const isDragging = draggedColId === colId;
            const isDropTarget = dropTargetId === colId;
            const isSortable = !!colDef.sortField;
            const isSorted = sortBy === colId;
            return (
              <div key={colId} className="relative">
                <div
                  draggable
                  onDragStart={() => handleDragStart(colId)}
                  onDragOver={(e) => handleDragOver(e, colId)}
                  onDragLeave={handleDragLeave}
                  onDrop={(e) => handleDrop(e, colId)}
                  onDragEnd={handleDragEnd}
                  onClick={(e) => {
                    // Only sort on click, not drag
                    if (isSortable && !draggedColId) {
                      e.stopPropagation();
                      toggleSort(colId);
                    }
                  }}
                  className={`select-none truncate pr-2 flex items-center gap-1 ${
                    colDef.align === 'right'
                      ? 'justify-end'
                      : colDef.align === 'center'
                      ? 'justify-center'
                      : ''
                  } ${isDragging ? 'opacity-50' : ''} ${
                    isDropTarget ? 'border-l-2 border-green-500' : ''
                  } ${isSortable ? 'cursor-pointer hover:text-white' : 'cursor-grab'} ${
                    isSorted ? 'text-white' : ''
                  }`}
                  title={isSortable ? `Click to sort by ${colDef.label}, drag to reorder` : `${colDef.label} (drag to reorder)`}
                >
                  <span>{colDef.shortLabel || colDef.label}</span>
                  {isSorted && (
                    sortOrder === 'asc' ? (
                      <ChevronUp className="w-3 h-3 flex-shrink-0" />
                    ) : (
                      <ChevronDown className="w-3 h-3 flex-shrink-0" />
                    )
                  )}
                </div>

                {/* Resize handle */}
                <div
                  className={`absolute right-0 top-1 bottom-1 w-1.5 cursor-col-resize
                             transition-colors border-r border-transparent
                             hover:border-zinc-500 hover:bg-zinc-500/20
                             ${resizingColumnId === colId ? 'border-zinc-400 bg-zinc-500/30' : ''}`}
                  onMouseDown={(e) => handleResizeStart(colId, e)}
                  onDoubleClick={() => resetColumnWidth(colId)}
                  title="Drag to resize, double-click to reset"
                />
              </div>
            );
          })}
          <div></div>
          <div></div>
        </div>

        {/* Virtualized track list */}
        <div
          ref={desktopScrollRef}
          className="flex-1 overflow-auto"
          data-alphabet-scroll-container
        >
          <div
            style={{
              height: `${virtualizer.getTotalSize()}px`,
              width: '100%',
              position: 'relative',
            }}
          >
            {virtualizer.getVirtualItems().map((virtualRow) => {
              const track = allTracks[virtualRow.index];
              const index = virtualRow.index;

              return (
                <div
                  key={virtualRow.key}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    height: `${virtualRow.size}px`,
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                >
                  {track ? (
                    <TrackRow
                      track={track}
                      index={index}
                      isCurrentTrack={currentTrack?.id === track.id}
                      isPlaying={currentTrack?.id === track.id && isPlaying}
                      isSelected={selectedTrackIds.has(track.id)}
                      onPlay={() => handlePlayTrack(track, index)}
                      onClick={(e) => handleRowClick(track, e)}
                      onDoubleClick={() => handleRowDoubleClick(track, index)}
                      onContextMenu={(e) => handleContextMenu(track, e)}
                      visibleColumnIds={visibleColumnIds}
                      gridColumns={gridColumns}
                    />
                  ) : (
                    // Loading placeholder for items not yet loaded
                    <div
                      className="grid gap-4 px-4 py-2 rounded-md"
                      style={{ gridTemplateColumns: gridColumns }}
                    >
                      <div className="flex items-center justify-center">
                        <span className="text-zinc-600">{index + 1}</span>
                      </div>
                      <div className="flex items-center">
                        <div className="h-4 w-32 bg-zinc-800 rounded animate-pulse" />
                      </div>
                      {visibleColumnIds.map((colId) => (
                        <div key={colId} className="flex items-center">
                          <div className="h-4 w-20 bg-zinc-800/50 rounded animate-pulse" />
                        </div>
                      ))}
                      <div />
                      <div />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Loading indicator when fetching more */}
        {isFetchingNextPage && (
          <div className="flex items-center justify-center py-2 flex-shrink-0">
            <Loader2 className="w-4 h-4 animate-spin text-zinc-400 mr-2" />
            <span className="text-sm text-zinc-500">Loading more...</span>
          </div>
        )}

        {/* Desktop footer */}
        <div className="px-4 py-2 text-sm text-zinc-500 flex-shrink-0 border-t border-zinc-800/50">
          {allTracksUnfiltered.length + sparsePages.size * PAGE_SIZE} of {total} tracks loaded
        </div>
      </div>

      {/* Context menu */}
      {contextMenuElement}

      {/* Alphabet bar for quick navigation */}
      <AlphabetBar
        letterIndex={letterIndex}
        activeLetter={activeLetter}
        onLetterSelect={handleLetterSelect}
        visible={isAlphabetBarVisible}
        isJumping={isJumping}
      />
    </div>
  );
}
