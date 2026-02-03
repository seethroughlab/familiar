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
import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useSearchParams } from 'react-router-dom';
import { useInfiniteQuery } from '@tanstack/react-query';
import { Play, Pause, Download, Check, Loader2, Heart, Music, FolderOpen, Clock, Disc } from 'lucide-react';
import { tracksApi } from '../../../api/client';
import { usePlayerStore } from '../../../stores/playerStore';
import { useSelectionStore } from '../../../stores/selectionStore';
import { useVisibleTracksStore } from '../../../stores/visibleTracksStore';
import { useFavorites } from '../../../hooks/useFavorites';
import { useArtworkPrefetchBatch } from '../../../hooks/useArtworkPrefetch';
import { useLongPress } from '../../../hooks/useLongPress';
import { useColumnStore, getVisibleColumns } from '../../../stores/columnStore';
import { COLUMN_DEFINITIONS, getColumnDef, getAnalysisColumns } from '../columnDefinitions';
import { useOfflineTrack } from '../../../hooks/useOfflineTrack';
import { useOfflineAlbum } from '../../../hooks/useOfflineAlbum';
import { useIntersectionObserver } from '../../../hooks/useIntersectionObserver'; // Still used for mobile view
import { registerBrowser, type BrowserProps, type ContextMenuState, initialContextMenuState } from '../types';
import { TrackContextMenu } from '../TrackContextMenu';
import { AlbumArtwork } from '../../AlbumArtwork';
import { AlphabetBar, useAlphabetBar } from '../AlphabetBar';
import type { Track } from '../../../types';

const PAGE_SIZE = 50;
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

function OfflineButton({ trackId }: { trackId: string }) {
  const { isOffline, isDownloading, downloadProgress, download, remove } = useOfflineTrack(trackId);

  if (isDownloading) {
    return (
      <div
        className="relative p-1 text-purple-400"
        title={`Downloading... ${downloadProgress}%`}
      >
        <Loader2 className="w-4 h-4 animate-spin" />
        {downloadProgress > 0 && downloadProgress < 100 && (
          <span className="absolute -bottom-1 left-1/2 -translate-x-1/2 text-[8px] font-medium">
            {downloadProgress}%
          </span>
        )}
      </div>
    );
  }

  if (isOffline) {
    return (
      <button
        onClick={(e) => {
          e.stopPropagation();
          remove();
        }}
        className="p-1 text-green-500 hover:text-red-400 transition-colors"
        title="Remove offline copy"
      >
        <Check className="w-4 h-4" />
      </button>
    );
  }

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        download();
      }}
      className="p-1 text-zinc-500 hover:text-white transition-colors opacity-100 sm:opacity-0 sm:group-hover:opacity-100"
      title="Download for offline"
    >
      <Download className="w-4 h-4" />
    </button>
  );
}

function FavoriteButton({ trackId }: { trackId: string }) {
  const { isFavorite, toggle } = useFavorites();
  const favorited = isFavorite(trackId);

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        toggle(trackId);
      }}
      className={`p-1 transition-colors ${
        favorited
          ? 'text-pink-500 hover:text-pink-400'
          : 'text-zinc-500 hover:text-pink-400 opacity-100 sm:opacity-0 sm:group-hover:opacity-100'
      }`}
      title={favorited ? 'Remove from favorites' : 'Add to favorites'}
    >
      <Heart className="w-4 h-4" fill={favorited ? 'currentColor' : 'none'} />
    </button>
  );
}

interface AlbumTrack {
  id: string;
}

interface AlbumOfflineButtonProps {
  tracks: AlbumTrack[];
  artist: string;
  album: string;
}

function AlbumOfflineButton({ tracks, artist, album }: AlbumOfflineButtonProps) {
  const {
    offlineCount,
    totalCount,
    isFullyOffline,
    isPartiallyOffline,
    isDownloading,
    currentTrack,
    overallProgress,
    download,
    remove,
  } = useOfflineAlbum(tracks, { artist, album });

  if (isDownloading) {
    return (
      <button
        className="flex items-center gap-2 px-4 py-2 bg-zinc-700 rounded-full transition-colors"
        title={`Downloading track ${currentTrack} of ${totalCount}...`}
      >
        <Loader2 className="w-4 h-4 animate-spin text-purple-400" />
        <span className="text-sm">{overallProgress}%</span>
      </button>
    );
  }

  if (isFullyOffline) {
    return (
      <button
        onClick={remove}
        className="flex items-center gap-2 px-4 py-2 bg-zinc-700 hover:bg-zinc-600 rounded-full transition-colors"
        title="Remove offline copies"
      >
        <Check className="w-4 h-4 text-green-500" />
        <span className="text-sm">Downloaded</span>
      </button>
    );
  }

  return (
    <button
      onClick={download}
      className="flex items-center gap-2 px-4 py-2 bg-zinc-700 hover:bg-zinc-600 rounded-full transition-colors"
      title={isPartiallyOffline ? `Download remaining ${totalCount - offlineCount} tracks` : 'Download album for offline'}
    >
      <Download className="w-4 h-4" />
      <span className="text-sm">
        {isPartiallyOffline ? `${offlineCount}/${totalCount}` : 'Download'}
      </span>
    </button>
  );
}

interface TrackRowProps {
  track: Track;
  index: number;
  isCurrentTrack: boolean;
  isPlaying: boolean;
  isSelected: boolean;
  onPlay: () => void;
  onClick: (e: React.MouseEvent) => void;
  onContextMenu: (e: React.MouseEvent) => void;
  visibleColumnIds: string[];
  gridColumns: string;
}

// Mobile card component for small screens
function MobileTrackCard({
  track,
  index,
  isCurrentTrack,
  isPlaying,
  isSelected,
  onPlay,
  onClick,
  onContextMenu,
  onLongPress,
}: {
  track: Track;
  index: number;
  isCurrentTrack: boolean;
  isPlaying: boolean;
  isSelected: boolean;
  onPlay: () => void;
  onClick: (e: React.MouseEvent) => void;
  onContextMenu: (e: React.MouseEvent) => void;
  onLongPress: (position: { x: number; y: number }) => void;
}) {
  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const longPressHandlers = useLongPress(onLongPress);

  return (
    <div
      data-testid="track-row"
      data-list-index={index}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('application/track-id', track.id);
        e.dataTransfer.effectAllowed = 'copy';
      }}
      onClick={onClick}
      onContextMenu={onContextMenu}
      {...longPressHandlers}
      className={`group flex items-center gap-3 px-4 py-3 cursor-pointer border-b border-zinc-800/30 ${
        isSelected
          ? 'bg-purple-500/20'
          : isCurrentTrack
          ? 'bg-zinc-800/50'
          : 'hover:bg-zinc-800/50'
      }`}
    >
      {/* Play button / index - show play icon on mobile when selected, number otherwise */}
      <button
        onClick={(e) => { e.stopPropagation(); onPlay(); }}
        className="w-8 flex-shrink-0 flex items-center justify-center text-zinc-400"
      >
        {isCurrentTrack && isPlaying ? (
          <>
            {/* Equalizer animation - always show when playing */}
            <div className="flex gap-0.5 md:group-hover:hidden">
              <div className="w-0.5 h-3 bg-green-500 animate-pulse" />
              <div className="w-0.5 h-2 bg-green-500 animate-pulse delay-75" />
              <div className="w-0.5 h-4 bg-green-500 animate-pulse delay-150" />
            </div>
            {/* Desktop: pause on hover */}
            <Pause className="hidden md:group-hover:block w-4 h-4" fill="currentColor" />
          </>
        ) : (
          <>
            {/* Mobile: show play icon when selected, number otherwise */}
            {isSelected ? (
              <Play className="md:hidden w-4 h-4" fill="currentColor" />
            ) : (
              <span className="md:hidden text-sm">{index + 1}</span>
            )}
            {/* Desktop: show number, play on hover */}
            <span className="hidden md:block md:group-hover:hidden text-sm">{index + 1}</span>
            <Play className="hidden md:group-hover:block w-4 h-4" fill="currentColor" />
          </>
        )}
      </button>

      {/* Track info */}
      <div className="flex-1 min-w-0">
        <div className={`truncate font-medium ${isCurrentTrack ? 'text-green-500' : 'text-white'}`}>
          {track.title || 'Unknown'}
        </div>
        <div className="text-sm text-zinc-400 truncate">
          {track.artist || 'Unknown Artist'}
          {track.album && <span className="text-zinc-500"> • {track.album}</span>}
        </div>
      </div>

      {/* Duration */}
      <div className="text-sm text-zinc-400 flex-shrink-0">
        {formatDuration(track.duration_seconds)}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 flex-shrink-0">
        <FavoriteButton trackId={track.id} />
        <OfflineButton trackId={track.id} />
      </div>
    </div>
  );
}

function TrackRow({
  track,
  index,
  isCurrentTrack,
  isPlaying,
  isSelected,
  onPlay,
  onClick,
  onContextMenu,
  visibleColumnIds,
  gridColumns,
}: TrackRowProps) {
  return (
    <div
      data-testid="track-row"
      data-list-index={index}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('application/track-id', track.id);
        e.dataTransfer.effectAllowed = 'copy';
      }}
      onClick={onClick}
      onContextMenu={onContextMenu}
      onMouseDown={(e) => {
        // Prevent text selection when using modifier keys for multi-select
        if (e.shiftKey || e.metaKey || e.ctrlKey) {
          e.preventDefault();
        }
      }}
      className={`group grid gap-4 px-4 py-2 rounded-md cursor-pointer select-none ${
        isSelected
          ? 'bg-purple-500/20 hover:bg-purple-500/30'
          : isCurrentTrack
          ? 'bg-zinc-800/50 hover:bg-zinc-800/70'
          : 'hover:bg-zinc-800/50'
      }`}
      style={{ gridTemplateColumns: gridColumns }}
    >
      {/* Index / Play button column */}
      <div className="flex items-center justify-center">
        <span className="group-hover:hidden text-zinc-400">
          {isCurrentTrack && isPlaying ? (
            <div className="w-4 h-4 flex items-center justify-center">
              <div className="flex gap-0.5">
                <div className="w-0.5 h-3 bg-green-500 animate-pulse" />
                <div className="w-0.5 h-2 bg-green-500 animate-pulse delay-75" />
                <div className="w-0.5 h-4 bg-green-500 animate-pulse delay-150" />
              </div>
            </div>
          ) : (
            index + 1
          )}
        </span>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onPlay();
          }}
          className="hidden group-hover:flex items-center justify-center"
        >
          {isCurrentTrack && isPlaying ? (
            <Pause className="w-4 h-4" fill="currentColor" />
          ) : (
            <Play className="w-4 h-4" fill="currentColor" />
          )}
        </button>
      </div>

      {/* Title column (always visible) */}
      <div className="min-w-0">
        <div className={`truncate ${isCurrentTrack ? 'text-green-500' : ''}`}>
          {track.title || 'Unknown'}
        </div>
      </div>

      {/* Dynamic columns */}
      {visibleColumnIds.map((colId) => {
        const colDef = getColumnDef(colId);
        if (!colDef) return null;

        const rawValue = colDef.getValue(track);
        const displayValue =
          colDef.format && rawValue != null ? colDef.format(rawValue) : rawValue ?? '-';

        return (
          <div
            key={colId}
            className={`text-zinc-400 truncate ${
              colDef.align === 'right'
                ? 'text-right'
                : colDef.align === 'center'
                ? 'text-center'
                : ''
            }`}
          >
            {displayValue}
          </div>
        );
      })}

      {/* Favorite button */}
      <div className="flex items-center justify-center">
        <FavoriteButton trackId={track.id} />
      </div>

      {/* Offline button */}
      <div className="flex items-center justify-center">
        <OfflineButton trackId={track.id} />
      </div>
    </div>
  );
}

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
  const [, setSearchParams] = useSearchParams();
  const { currentTrack, isPlaying, shuffle, setIsPlaying, setQueue, setLazyQueue, lazyQueueIds } = usePlayerStore();
  const selectRange = useSelectionStore((state) => state.selectRange);
  const columns = useColumnStore((state) => state.columns);
  const reorderColumns = useColumnStore((state) => state.reorderColumns);
  const { isFavorite, toggle } = useFavorites();

  // Context menu state
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(initialContextMenuState);

  // Navigate to ego music map with artist
  const handleExploreSimilarArtists = useCallback(
    (artistName: string) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set('browser', 'ego-music-map');
        next.set('center', artistName);
        return next;
      });
    },
    [setSearchParams]
  );

  // Drag & drop state for columns
  const [draggedColId, setDraggedColId] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null);

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

  // Build grid template columns
  const gridColumns = useMemo(() => {
    const cols: string[] = ['3rem']; // Index column
    cols.push('1fr'); // Title (always visible)

    for (const colId of visibleColumnIds) {
      const colDef = COLUMN_DEFINITIONS.find((d) => d.id === colId);
      cols.push(colDef?.width || '1fr');
    }

    cols.push('3rem', '3rem'); // Favorite, Offline
    return cols.join(' ');
  }, [visibleColumnIds]);

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

  const {
    data,
    isLoading,
    error,
    hasNextPage,
    fetchNextPage,
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
      }),
    getNextPageParam: (lastPage) => {
      const totalPages = Math.ceil(lastPage.total / PAGE_SIZE);
      return lastPage.page < totalPages ? lastPage.page + 1 : undefined;
    },
    initialPageParam: 1,
  });

  const handleLoadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Mobile still uses intersection observer for infinite scroll
  // Desktop uses virtualization which handles loading automatically
  const mobileSentinelRef = useIntersectionObserver({
    onIntersect: handleLoadMore,
    enabled: hasNextPage && !isFetchingNextPage,
  });

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
      });

      setSparsePages(prev => new Map(prev).set(pageNumber, result.items));
    } catch (error) {
      // Remove from loaded set so it can be retried
      loadedPagesRef.current.delete(pageNumber);
      console.error(`Failed to fetch page ${pageNumber}:`, error);
    }
  }, [filters.search, filters.artist, filters.album, filters.yearFrom, filters.yearTo,
      filters.energyMin, filters.energyMax, filters.valenceMin, filters.valenceMax, needsFeatures]);

  // Reset sparse pages and loaded tracking when filters change
  useEffect(() => {
    loadedPagesRef.current = new Set([1]);
    setSparsePages(new Map());
  }, [filters.search, filters.artist, filters.album, filters.yearFrom, filters.yearTo,
      filters.energyMin, filters.energyMax, filters.valenceMin, filters.valenceMax]);

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

  // Callback for alphabet bar to use virtualizer's scrollToIndex
  const scrollToIndex = useCallback((index: number) => {
    virtualizer.scrollToIndex(index, { align: 'start', behavior: 'smooth' });
  }, [virtualizer]);

  // Auto-scroll to current track when it changes or on mount (desktop only)
  useEffect(() => {
    if (!currentTrack) return;

    const scrollToCurrentTrack = async () => {
      // Fast path: check if track is already loaded in sparse array
      const loadedIndex = allTracks.findIndex(t => t?.id === currentTrack.id);
      if (loadedIndex >= 0) {
        virtualizer.scrollToIndex(loadedIndex, { align: 'center', behavior: 'smooth' });
        return;
      }

      // Slow path: fetch index from server (track might be on an unloaded page)
      try {
        const { index } = await tracksApi.getIndex(currentTrack.id, {
          search: filters.search,
          artist: filters.artist,
          album: filters.album,
        });
        if (index >= 0) {
          virtualizer.scrollToIndex(index, { align: 'center', behavior: 'smooth' });
        }
      } catch {
        // Track might not match current filters - ignore silently
      }
    };

    scrollToCurrentTrack();
  }, [currentTrack?.id, allTracks, virtualizer, filters.search, filters.artist, filters.album]);

  // Alphabet bar for quick navigation
  const {
    letterIndex,
    activeLetter,
    isVisible: isAlphabetBarVisible,
    jumpToLetter,
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

  // Update visible tracks store when tracks change (for LLM context)
  // Use allTracksUnfiltered (dense array) for this since we only want loaded tracks
  const setVisibleTracks = useVisibleTracksStore((state) => state.setVisibleTracks);
  useEffect(() => {
    if (allTracksUnfiltered.length > 0) {
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
  }), [filters]);

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
        try {
          const response = await tracksApi.getIds({
            shuffle: shuffle,
            start_with: track.id,  // Clicked track plays first
            ...queueFilters,
          });
          if (response.ids.length > 0) {
            await setLazyQueue(response.ids, {
              type: 'library',
              filters: queueFilters,
            });
          }
        } catch (error) {
          console.error('Failed to play track:', error);
        } finally {
          setIsLoadingPlayAll(false);
        }
        return;
      }

      // For smaller result sets, use regular queue (use dense array)
      if (allTracksUnfiltered.length > 0) {
        setQueue(allTracksUnfiltered as Track[], index);
      }
    },
    [currentTrack, isPlaying, setIsPlaying, allTracksUnfiltered, setQueue, total, shuffle, queueFilters, setLazyQueue]
  );

  const handleRowClick = useCallback(
    (track: Track, e: React.MouseEvent) => {
      if (e.shiftKey) {
        // Shift+click: select range from last clicked to this track
        // Use dense array for shift-select to work correctly
        const allIds = allTracksUnfiltered.map((t) => t.id);
        selectRange(track.id, allIds);
      } else if (e.metaKey || e.ctrlKey) {
        // Cmd/Ctrl+click: toggle individual track selection
        onSelectTrack(track.id, true);
      } else {
        // Plain click: select only this track
        onSelectTrack(track.id, false);
      }
    },
    [onSelectTrack, selectRange, allTracksUnfiltered]
  );

  const handleRowDoubleClick = useCallback(
    (track: Track, index: number) => {
      handlePlayTrack(track, index);
    },
    [handlePlayTrack]
  );

  const handleContextMenu = useCallback((track: Track, e: React.MouseEvent) => {
    e.preventDefault();
    setContextMenu({
      isOpen: true,
      track,
      position: { x: e.clientX, y: e.clientY },
    });
  }, []);

  const closeContextMenu = useCallback(() => {
    setContextMenu(initialContextMenuState);
  }, []);

  // Track loading state for play all (must be before early returns)
  const [isLoadingPlayAll, setIsLoadingPlayAll] = useState(false);

  const handlePlayAll = useCallback(async () => {
    if (total === 0) return;

    // For large result sets, use lazy queue mode with server-side ordering
    // Pass global shuffle state so server returns shuffled IDs if enabled
    if (total >= LAZY_QUEUE_THRESHOLD) {
      setIsLoadingPlayAll(true);
      try {
        const response = await tracksApi.getIds({
          shuffle: shuffle,
          ...queueFilters,
        });
        if (response.ids.length > 0) {
          await setLazyQueue(response.ids, {
            type: 'library',
            filters: queueFilters,
          });
        }
      } catch (error) {
        console.error('Failed to play all tracks:', error);
      } finally {
        setIsLoadingPlayAll(false);
      }
      return;
    }

    // For smaller result sets, use regular queue (use dense array)
    // setQueue() already respects the global shuffle toggle
    if (allTracksUnfiltered.length > 0) {
      setQueue(allTracksUnfiltered as Track[], 0);
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
      )}

      {/* Mobile view - card layout (visible below md breakpoint) */}
      {/* Mobile uses dense array (allTracksUnfiltered) since it doesn't support sparse loading */}
      <div className="md:hidden">
        {allTracksUnfiltered.map((track, index) => (
          <MobileTrackCard
            key={track.id}
            track={track}
            index={index}
            isCurrentTrack={currentTrack?.id === track.id}
            isPlaying={currentTrack?.id === track.id && isPlaying}
            isSelected={selectedTrackIds.has(track.id)}
            onPlay={() => handlePlayTrack(track, index)}
            onClick={(e) => {
              if (e.detail === 2) {
                handleRowDoubleClick(track, index);
              } else {
                handleRowClick(track, e);
              }
            }}
            onContextMenu={(e) => handleContextMenu(track, e)}
            onLongPress={(position) => {
              setContextMenu({
                isOpen: true,
                track,
                position,
              });
            }}
          />
        ))}
        {/* Loading indicator for infinite scroll */}
        {isFetchingNextPage && (
          <div className="flex items-center justify-center py-4">
            <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
          </div>
        )}
        {/* Sentinel for infinite scroll */}
        {hasNextPage && <div ref={mobileSentinelRef} className="h-4" />}
        {/* Mobile footer */}
        <div className="px-4 py-4 text-sm text-zinc-500">
          {allTracksUnfiltered.length} of {total} tracks
        </div>
      </div>

      {/* Desktop view - virtualized grid layout (visible at md and above) */}
      <div className="hidden md:flex md:flex-col md:h-full">
        {/* Header - fixed outside scroll area */}
        <div
          className="grid gap-4 px-4 py-2 text-sm text-zinc-400 border-b border-zinc-800 flex-shrink-0"
          style={{ gridTemplateColumns: gridColumns }}
        >
          <div>#</div>
          <div>Title</div>
          {visibleColumnIds.map((colId) => {
            const colDef = getColumnDef(colId);
            if (!colDef) return null;
            const isDragging = draggedColId === colId;
            const isDropTarget = dropTargetId === colId;
            return (
              <div
                key={colId}
                draggable
                onDragStart={() => handleDragStart(colId)}
                onDragOver={(e) => handleDragOver(e, colId)}
                onDragLeave={handleDragLeave}
                onDrop={(e) => handleDrop(e, colId)}
                onDragEnd={handleDragEnd}
                className={`cursor-grab select-none ${
                  colDef.align === 'right'
                    ? 'text-right'
                    : colDef.align === 'center'
                    ? 'text-center'
                    : ''
                } ${isDragging ? 'opacity-50' : ''} ${
                  isDropTarget ? 'border-l-2 border-green-500' : ''
                }`}
                title={`${colDef.label} (drag to reorder)`}
              >
                {colDef.shortLabel || colDef.label}
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
                      onClick={(e) => {
                        if (e.detail === 2) {
                          handleRowDoubleClick(track, index);
                        } else {
                          handleRowClick(track, e);
                        }
                      }}
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
      {contextMenu.isOpen && contextMenu.track && (
        <TrackContextMenu
          track={contextMenu.track}
          position={contextMenu.position}
          isSelected={selectedTrackIds.has(contextMenu.track.id)}
          onClose={closeContextMenu}
          onPlay={() => {
            const index = allTracksUnfiltered.findIndex((t) => t.id === contextMenu.track?.id);
            if (contextMenu.track && index !== -1) {
              handlePlayTrack(contextMenu.track, index);
            }
          }}
          onQueue={() => {
            if (contextMenu.track) {
              onQueueTrack(contextMenu.track.id);
            }
          }}
          onGoToArtist={() => {
            if (contextMenu.track?.artist) {
              onGoToArtist(contextMenu.track.artist);
            }
          }}
          onGoToAlbum={() => {
            if (contextMenu.track?.album) {
              // Use album_artist if available (for compilations), fallback to artist
              const albumArtist = contextMenu.track.album_artist || contextMenu.track.artist;
              if (albumArtist) {
                onGoToAlbum(albumArtist, contextMenu.track.album);
              }
            }
          }}
          onExploreSimilarArtists={() => {
            if (contextMenu.track?.artist) {
              handleExploreSimilarArtists(contextMenu.track.artist);
            }
          }}
          onToggleSelect={() => {
            if (contextMenu.track) {
              onSelectTrack(contextMenu.track.id, true);
            }
          }}
          onAddToPlaylist={() => {
            // TODO: Open playlist picker modal

          }}
          onMakePlaylist={() => {
            if (contextMenu.track) {
              const track = contextMenu.track;
              const message = `Make me a playlist based on "${track.title || 'this track'}" by ${track.artist || 'Unknown Artist'}`;
              window.dispatchEvent(new CustomEvent('trigger-chat', { detail: { message } }));
            }
          }}
          onEditMetadata={() => {
            if (contextMenu.track) {
              onEditTrack(contextMenu.track.id);
            }
          }}
          isFavorite={contextMenu.track ? isFavorite(contextMenu.track.id) : false}
          onToggleFavorite={() => {
            if (contextMenu.track) {
              toggle(contextMenu.track.id);
            }
          }}
          // Bulk selection props for mobile
          selectedCount={selectedTrackIds.size}
          onPlaySelected={() => {
            // Play selected tracks - get tracks from dense array by IDs
            const selectedTracks = allTracksUnfiltered.filter((t) => selectedTrackIds.has(t.id));
            if (selectedTracks.length > 0) {
              setQueue(selectedTracks, 0);
              onClearSelection();
            }
          }}
          onClearSelection={onClearSelection}
        />
      )}

      {/* Alphabet bar for quick navigation */}
      <AlphabetBar
        letterIndex={letterIndex}
        activeLetter={activeLetter}
        onLetterSelect={jumpToLetter}
        visible={isAlphabetBarVisible}
      />
    </div>
  );
}
