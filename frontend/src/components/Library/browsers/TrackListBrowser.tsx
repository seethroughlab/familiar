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
import { useState, useMemo, useCallback, useEffect, useLayoutEffect, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useNavigate } from 'react-router-dom';
import { useInfiniteQuery } from '@tanstack/react-query';
import { Play, Download, Check, Loader2, Music, FolderOpen, Clock, Disc, ChevronUp, ChevronDown, ExternalLink } from 'lucide-react';
import { tracksApi } from '../../../api';
import { usePlayerStore } from '../../../stores/playerStore';
import { useAudioSettingsStore } from '../../../stores/audioSettingsStore';
import { PlayIndicator, MobilePlayIndicator } from '../../common/PlayIndicator';
import { useSelectionStore } from '../../../stores/selectionStore';
import { useVisibleTracksStore } from '../../../stores/visibleTracksStore';
import { useTrackContextMenu } from '../../../hooks/useTrackContextMenu';
import { useArtworkPrefetchBatch } from '../../../hooks/useArtworkPrefetch';
import { useLongPress } from '../../../hooks/useLongPress';
import { useColumnStore, getVisibleColumns } from '../../../stores/columnStore';
import { COLUMN_DEFINITIONS, getColumnDef, getAnalysisColumns, COLUMN_MAP } from '../columnDefinitions';
import { OfflineButton } from './trackList/OfflineButton';
import { FavoriteButton } from './trackList/FavoriteButton';
import { useOfflineAlbum } from '../../../hooks/useOfflineAlbum';
import { useIntersectionObserver } from '../../../hooks/useIntersectionObserver'; // Still used for mobile view
import { registerBrowser, type BrowserProps } from '../types';
import { AlbumArtwork } from '../../AlbumArtwork';
import { AlphabetBar, useAlphabetBar } from '../AlphabetBar';
import type { Track } from '../../../types';
import { isExternalTrack } from '../../../types';

import { createLogger } from '../../../utils/logger';

const log = createLogger('TrackListBrowser');

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

function ExternalLinkButton({ track }: { track: Track }) {
  const spotifyUrl = track.spotify_id
    ? `https://open.spotify.com/track/${track.spotify_id}`
    : null;

  if (!spotifyUrl) return null;

  return (
    <a
      href={spotifyUrl}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => e.stopPropagation()}
      className="p-1 text-zinc-500 hover:text-green-400 transition-colors opacity-100 sm:opacity-0 sm:group-hover:opacity-100"
      title="Open in Spotify"
    >
      <ExternalLink className="w-4 h-4" />
    </a>
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
        <MobilePlayIndicator isCurrent={isCurrentTrack} isPlaying={isPlaying} isSelected={isSelected} index={index + 1} />
      </button>

      {/* Track info */}
      <div className="flex-1 min-w-0">
        <div className={`truncate font-medium flex items-center gap-1.5 ${isCurrentTrack ? 'text-green-500' : 'text-white'}`}>
          <span className="truncate">{track.title || 'Unknown'}</span>
          {isExternalTrack(track) && (
            <span className="inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded bg-amber-500/20 text-amber-400 flex-shrink-0">
              External
            </span>
          )}
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
        <FavoriteButton trackId={track.id} isExternal={isExternalTrack(track)} />
        {isExternalTrack(track) ? (
          <ExternalLinkButton track={track} />
        ) : (
          <OfflineButton trackId={track.id} />
        )}
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
      <div className="flex items-center justify-center"
        onClick={(e) => { e.stopPropagation(); onPlay(); }}
        role="button"
      >
        <PlayIndicator isCurrent={isCurrentTrack} isPlaying={isPlaying} index={index + 1} />
      </div>

      {/* Title column (always visible) */}
      <div className="min-w-0">
        <div className={`truncate flex items-center gap-1.5 ${isCurrentTrack ? 'text-green-500' : ''}`}>
          {track.title || 'Unknown'}
          {isExternalTrack(track) && (
            <span className="inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded bg-amber-500/20 text-amber-400 flex-shrink-0">
              External
            </span>
          )}
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
        <FavoriteButton trackId={track.id} isExternal={isExternalTrack(track)} />
      </div>

      {/* Offline / External link button */}
      <div className="flex items-center justify-center">
        {isExternalTrack(track) ? (
          <ExternalLinkButton track={track} />
        ) : (
          <OfflineButton trackId={track.id} />
        )}
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
  const playExternalPreviews = useAudioSettingsStore((s) => s.playExternalPreviews);
  const setPlayExternalPreviews = useAudioSettingsStore((s) => s.setPlayExternalPreviews);
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
  const setColumnWidth = useColumnStore((state) => state.setColumnWidth);
  const resetColumnWidth = useColumnStore((state) => state.resetColumnWidth);
  const [resizing, setResizing] = useState<{
    columnId: string;
    headerEl: HTMLElement;
  } | null>(null);

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

  // Minimum column width in pixels
  const MIN_COLUMN_WIDTH = 50;

  // Resize handlers
  const handleResizeStart = useCallback((columnId: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();

    const headerEl = e.currentTarget.parentElement;
    if (!headerEl) return;

    setResizing({ columnId, headerEl });
  }, []);

  // Handle resize mouse move and mouse up
  useEffect(() => {
    if (!resizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      const left = resizing.headerEl.getBoundingClientRect().left;
      const newWidth = Math.max(MIN_COLUMN_WIDTH, e.clientX - left);
      setColumnWidth(resizing.columnId, newWidth);
    };

    const handleMouseUp = () => {
      setResizing(null);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [resizing, setColumnWidth]);

  // Apply resize cursor and prevent text selection during resize
  useEffect(() => {
    if (resizing) {
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      return () => {
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      };
    }
  }, [resizing]);

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
        fx: filters.fx,
        fxMin: filters.fxMin,
        fxMax: filters.fxMax,
        fy: filters.fy,
        fyMin: filters.fyMin,
        fyMax: filters.fyMax,
        include_features: needsFeatures,
        include_external: true,
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
        fx: filters.fx,
        fx_min: filters.fxMin,
        fx_max: filters.fxMax,
        fy: filters.fy,
        fy_min: filters.fyMin,
        fy_max: filters.fyMax,
        page: pageParam,
        page_size: PAGE_SIZE,
        include_features: needsFeatures,
        include_external: true,
        sort_by: sortField,
        sort_order: sortOrder,
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
        fx: filters.fx,
        fx_min: filters.fxMin,
        fx_max: filters.fxMax,
        fy: filters.fy,
        fy_min: filters.fyMin,
        fy_max: filters.fyMax,
        include_features: needsFeatures,
        include_external: true,
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
      filters.energyMin, filters.energyMax, filters.valenceMin, filters.valenceMax,
      filters.fx, filters.fxMin, filters.fxMax, filters.fy, filters.fyMin, filters.fyMax,
      needsFeatures, sortField, sortOrder]);

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
          include_external: true,
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

  // Mobile jump-fetch state: when a letter is tapped on mobile, we fetch just that page
  // and render from there instead of loading all pages from 1 to N.
  const [mobileJump, setMobileJump] = useState<{
    letter: string;
    tracks: Track[];
    nextPage: number;
    hasMore: boolean;
    isLoading: boolean;
    prevPage: number;
    hasPrevious: boolean;
    isLoadingPrev: boolean;
  } | null>(null);

  // Guard: after a jump, don't fire the top sentinel until user scrolls down past threshold
  const [prevSentinelReady, setPrevSentinelReady] = useState(false);
  // For scroll position maintenance when prepending tracks
  const prevLoadScrollRef = useRef<number | null>(null);

  const handleMobileJumpToLetter = useCallback(async (letter: string) => {
    if (!letterIndex || !(letter in letterIndex)) return;

    const targetIndex = letterIndex[letter];
    const targetPage = Math.floor(targetIndex / PAGE_SIZE) + 1;

    setActiveLetter(letter);
    setPrevSentinelReady(false);
    setMobileJump(prev => ({
      letter,
      tracks: prev?.tracks ?? [],
      nextPage: targetPage + 1,
      hasMore: true,
      isLoading: true,
      prevPage: targetPage - 1,
      hasPrevious: targetPage > 1,
      isLoadingPrev: false,
    }));

    try {
      const result = await tracksApi.list({
        page: targetPage,
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
        fx: filters.fx,
        fx_min: filters.fxMin,
        fx_max: filters.fxMax,
        fy: filters.fy,
        fy_min: filters.fyMin,
        fy_max: filters.fyMax,
        include_features: needsFeatures,
        include_external: true,
        sort_by: sortField,
        sort_order: sortOrder,
      });

      const totalPages = Math.ceil(result.total / PAGE_SIZE);
      setMobileJump({
        letter,
        tracks: result.items,
        nextPage: targetPage + 1,
        hasMore: targetPage < totalPages,
        isLoading: false,
        prevPage: targetPage - 1,
        hasPrevious: targetPage > 1,
        isLoadingPrev: false,
      });

      // Scroll mobile view to top
      window.scrollTo({ top: 0 });
    } catch (err) {
      log.error('Failed to jump to letter:', err);
      setMobileJump(null);
    }
  }, [letterIndex, filters, needsFeatures, sortField, sortOrder, setActiveLetter]);

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
        fx: filters.fx,
        fx_min: filters.fxMin,
        fx_max: filters.fxMax,
        fy: filters.fy,
        fy_min: filters.fyMin,
        fy_max: filters.fyMax,
        include_features: needsFeatures,
        include_external: true,
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

  // Load previous pages when scrolling up after a mobile jump
  const handleMobileJumpLoadPrevious = useCallback(async () => {
    if (!mobileJump || mobileJump.isLoadingPrev || !mobileJump.hasPrevious) return;

    setMobileJump(prev => prev ? { ...prev, isLoadingPrev: true } : null);

    // Save scroll height before prepending so we can maintain position
    prevLoadScrollRef.current = document.documentElement.scrollHeight;

    try {
      const result = await tracksApi.list({
        page: mobileJump.prevPage,
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
        fx: filters.fx,
        fx_min: filters.fxMin,
        fx_max: filters.fxMax,
        fy: filters.fy,
        fy_min: filters.fyMin,
        fy_max: filters.fyMax,
        include_features: needsFeatures,
        include_external: true,
        sort_by: sortField,
        sort_order: sortOrder,
      });

      setMobileJump(prev => prev ? {
        ...prev,
        tracks: [...result.items, ...prev.tracks],
        prevPage: prev.prevPage - 1,
        hasPrevious: prev.prevPage > 1,
        isLoadingPrev: false,
      } : null);
    } catch (err) {
      log.error('Failed to load previous jump tracks:', err);
      setMobileJump(prev => prev ? { ...prev, isLoadingPrev: false } : null);
    }
  }, [mobileJump, filters, needsFeatures, sortField, sortOrder]);

  // After prepending tracks, adjust scroll position so user doesn't jump
  useLayoutEffect(() => {
    if (prevLoadScrollRef.current !== null) {
      const heightAfter = document.documentElement.scrollHeight;
      const diff = heightAfter - prevLoadScrollRef.current;
      if (diff > 0) window.scrollBy(0, diff);
      prevLoadScrollRef.current = null;
    }
  });

  // Arm the top sentinel only after user scrolls down past threshold (avoids
  // immediate trigger right after a jump scrolls to top)
  useEffect(() => {
    if (!mobileJump?.hasPrevious || prevSentinelReady) return;

    const handleScroll = () => {
      if (window.scrollY > 200) {
        setPrevSentinelReady(true);
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, [mobileJump?.hasPrevious, prevSentinelReady]);

  // Letter select routing: mobile uses jump-fetch, desktop uses virtualizer
  const handleLetterSelect = useCallback((letter: string) => {
    if (window.innerWidth < 768) {
      handleMobileJumpToLetter(letter);
    } else {
      jumpToLetter(letter);
    }
  }, [handleMobileJumpToLetter, jumpToLetter]);

  // Reset mobileJump when filters/sort change
  useEffect(() => {
    setMobileJump(null);
    setPrevSentinelReady(false);
  }, [filters.search, filters.artist, filters.album, filters.yearFrom, filters.yearTo,
      filters.energyMin, filters.energyMax, filters.valenceMin, filters.valenceMax,
      filters.fx, filters.fxMin, filters.fxMax, filters.fy, filters.fyMin, filters.fyMax,
      sortField, sortOrder]);

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
    fx: filters.fx,
    fx_min: filters.fxMin,
    fx_max: filters.fxMax,
    fy: filters.fy,
    fy_min: filters.fyMin,
    fy_max: filters.fyMax,
    include_external: true,
    sort_by: sortField,
    sort_order: sortOrder,
  }), [filters, sortField, sortOrder]);

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
            start_with: isExternalTrack(track) ? `ext:${track.id}` : track.id,  // Clicked track plays first
            ...queueFilters,
          });
          if (response.ids.length > 0) {
            await setLazyQueue(response.ids, {
              type: 'library',
              filters: queueFilters,
            });
          }
        } catch (error) {
          log.error('Failed to play track:', error);
        } finally {
          setIsLoadingPlayAll(false);
        }
        return;
      }

      // For smaller result sets, use regular queue (use dense array)
      // Attach _externalInfo for external tracks so the audio engine uses preview URLs
      if (allTracksUnfiltered.length > 0) {
        const queueTracks = allTracksUnfiltered.map(t => ({
          ...t,
          _externalInfo: isExternalTrack(t) ? {
            type: 'external' as const,
            previewUrl: t.preview_url || null,
            matchedTrackId: t.matched_track_id || null,
            originalId: t.id,
          } : undefined,
        }));
        setQueue(queueTracks as Track[], index);
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
        log.error('Failed to play all tracks:', error);
      } finally {
        setIsLoadingPlayAll(false);
      }
      return;
    }

    // For smaller result sets, use regular queue (use dense array)
    // setQueue() already respects the global shuffle toggle
    if (allTracksUnfiltered.length > 0) {
      const queueTracks = allTracksUnfiltered.map(t => ({
        ...t,
        _externalInfo: isExternalTrack(t) ? {
          type: 'external' as const,
          previewUrl: t.preview_url || null,
          matchedTrackId: t.matched_track_id || null,
          originalId: t.id,
        } : undefined,
      }));
      setQueue(queueTracks as Track[], 0);
    }
  }, [total, shuffle, queueFilters, setLazyQueue, allTracksUnfiltered, setQueue]);

  // Check if any external tracks are loaded
  const hasExternalTracks = useMemo(
    () => allTracksUnfiltered.some(t => isExternalTrack(t)),
    [allTracksUnfiltered]
  );

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
            {hasExternalTracks && (
              <button
                onClick={() => setPlayExternalPreviews(!playExternalPreviews)}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-full transition-colors ${
                  playExternalPreviews
                    ? 'bg-amber-600 hover:bg-amber-500'
                    : 'bg-zinc-700 hover:bg-zinc-600'
                }`}
                title={playExternalPreviews ? 'Disable external track previews' : 'Enable external track previews'}
              >
                <ExternalLink className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Previews</span>
              </button>
            )}
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

      {/* Mobile view - card layout (visible below md breakpoint) */}
      {/* Uses unified mobileTracks: either jump-fetched page or normal infinite query */}
      <div className="md:hidden">
        {mobileJump?.hasPrevious && (
          <div ref={mobilePrevSentinelRef} className="h-4" />
        )}
        {mobileJump?.isLoadingPrev && (
          <div className="flex items-center justify-center py-4">
            <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
          </div>
        )}
        {mobileTracks.map((track, index) => (
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
            onLongPress={(position) => openContextMenu(track, position)}
          />
        ))}
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
      <div className="hidden md:flex md:flex-col md:h-full">
        {/* Header - fixed outside scroll area */}
        <div
          className="grid gap-4 px-4 py-2 text-sm text-zinc-400 border-b border-zinc-800 flex-shrink-0"
          style={{ gridTemplateColumns: gridColumns }}
        >
          <div>#</div>
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
                             ${resizing?.columnId === colId ? 'border-zinc-400 bg-zinc-500/30' : ''}`}
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
