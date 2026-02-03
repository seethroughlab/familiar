/**
 * TrackList Browser - Traditional track list view.
 *
 * Uses infinite scroll to load tracks progressively as you scroll.
 * Wraps TrackList with BrowserProps interface for the pluggable browser system.
 */
import { useState, useMemo, useCallback, useEffect } from 'react';
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
import { useIntersectionObserver } from '../../../hooks/useIntersectionObserver';
import { registerBrowser, type BrowserProps, type ContextMenuState, initialContextMenuState } from '../types';
import { TrackContextMenu } from '../TrackContextMenu';
import { AlbumArtwork } from '../../AlbumArtwork';
import type { Track } from '../../../types';

const PAGE_SIZE = 50;

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

  // Separate refs for mobile and desktop sentinels
  // Both views render but are hidden via CSS, so a single ref would only attach
  // to the last rendered element (desktop), breaking infinite scroll on mobile
  const mobileSentinelRef = useIntersectionObserver({
    onIntersect: handleLoadMore,
    enabled: hasNextPage && !isFetchingNextPage,
  });

  const desktopSentinelRef = useIntersectionObserver({
    onIntersect: handleLoadMore,
    enabled: hasNextPage && !isFetchingNextPage,
  });

  // Flatten all pages into a single array
  const allTracksUnfiltered = useMemo(
    () => data?.pages.flatMap((page) => page.items) ?? [],
    [data]
  );

  // Filter by downloaded tracks if downloadedOnly is enabled
  const allTracks = useMemo(() => {
    if (filters.downloadedOnly && offlineTrackIds && offlineTrackIds.size > 0) {
      return allTracksUnfiltered.filter(track => offlineTrackIds.has(track.id));
    }
    return allTracksUnfiltered;
  }, [allTracksUnfiltered, filters.downloadedOnly, offlineTrackIds]);

  const total = filters.downloadedOnly && offlineTrackIds
    ? allTracks.length
    : data?.pages[0]?.total ?? 0;

  // Update visible tracks store when tracks change (for LLM context)
  const setVisibleTracks = useVisibleTracksStore((state) => state.setVisibleTracks);
  useEffect(() => {
    if (allTracks.length > 0) {
      const visibleTracks = allTracks.map((t) => ({
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
  }, [allTracks, total, filters, setVisibleTracks]);

  // Prefetch artwork for visible albums
  const prefetchArtworkBatch = useArtworkPrefetchBatch();
  useEffect(() => {
    if (allTracks.length > 0) {
      prefetchArtworkBatch(
        allTracks.map((t) => ({
          artist: t.artist,
          album: t.album,
          trackId: t.id,
        }))
      );
    }
  }, [allTracks, prefetchArtworkBatch]);

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

      // For smaller result sets, use regular queue
      if (allTracks.length > 0) {
        setQueue(allTracks, index);
      }
    },
    [currentTrack, isPlaying, setIsPlaying, allTracks, setQueue, total, shuffle, queueFilters, setLazyQueue]
  );

  const handleRowClick = useCallback(
    (track: Track, e: React.MouseEvent) => {
      if (e.shiftKey) {
        // Shift+click: select range from last clicked to this track
        const allIds = allTracks.map((t) => t.id);
        selectRange(track.id, allIds);
      } else if (e.metaKey || e.ctrlKey) {
        // Cmd/Ctrl+click: toggle individual track selection
        onSelectTrack(track.id, true);
      } else {
        // Plain click: select only this track
        onSelectTrack(track.id, false);
      }
    },
    [onSelectTrack, selectRange, allTracks]
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

    // For smaller result sets, use regular queue
    // setQueue() already respects the global shuffle toggle
    if (allTracks.length > 0) {
      setQueue(allTracks, 0);
    }
  }, [total, shuffle, queueFilters, setLazyQueue, allTracks, setQueue]);

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

  if (!allTracks.length) {
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

  // Compute album stats from tracks
  const isAlbumView = filters.album && allTracks.length > 0;
  const albumStats = isAlbumView ? {
    artist: filters.artist || allTracks[0]?.album_artist || allTracks[0]?.artist || 'Unknown Artist',
    album: filters.album,
    year: allTracks.find(t => t.year)?.year || null,
    trackCount: total,
    totalDuration: allTracks.reduce((sum, t) => sum + (t.duration_seconds || 0), 0),
    firstTrackId: allTracks[0]?.id,
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
    <div>
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

            {/* Play button */}
            <div className="mt-4">
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
            </div>
          </div>
        </div>
      )}

      {/* Toolbar for non-album view */}
      {!albumStats && allTracks.length > 0 && (
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
      <div className="md:hidden">
        {allTracks.map((track, index) => (
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
          {allTracks.length} of {total} tracks
        </div>
      </div>

      {/* Desktop view - grid layout (visible at md and above) */}
      <div className="hidden md:block">
        {/* Header */}
        <div
          className="grid gap-4 px-4 py-2 text-sm text-zinc-400 border-b border-zinc-800"
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

        {/* Tracks */}
        <div className="mt-2">
          {allTracks.map((track, index) => (
            <TrackRow
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
              visibleColumnIds={visibleColumnIds}
              gridColumns={gridColumns}
            />
          ))}
        </div>

        {/* Loading indicator for infinite scroll */}
        {isFetchingNextPage && (
          <div className="flex items-center justify-center py-4">
            <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
          </div>
        )}

        {/* Sentinel for infinite scroll */}
        {hasNextPage && <div ref={desktopSentinelRef} className="h-4" />}

        {/* Desktop footer */}
        <div className="px-4 py-4 text-sm text-zinc-500">
          {allTracks.length} of {total} tracks
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
            const index = allTracks.findIndex((t) => t.id === contextMenu.track?.id);
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
          // Bulk selection props for mobile
          selectedCount={selectedTrackIds.size}
          onPlaySelected={() => {
            // Play selected tracks - get tracks from allTracks by IDs
            const selectedTracks = allTracks.filter((t) => selectedTrackIds.has(t.id));
            if (selectedTracks.length > 0) {
              setQueue(selectedTracks, 0);
              onClearSelection();
            }
          }}
          onClearSelection={onClearSelection}
        />
      )}
    </div>
  );
}
