/**
 * AlbumGrid Browser - Shows albums in a responsive grid with artwork.
 *
 * Desktop: Uses @tanstack/react-virtual for row-based virtualization, enabling:
 * - Instant scroll-to-index for alphabet bar navigation (works for any index, even unloaded)
 * - Efficient rendering of large grids (only visible rows + overscan are rendered)
 * - Progressive page loading as user scrolls
 *
 * Mobile: Uses intersection observer for simpler infinite scroll.
 */
import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { Grid3X3, Loader2 } from 'lucide-react';
import { libraryApi, type AlbumSummary } from '../../../api/client';
import {
  registerBrowser,
  type BrowserProps,
  type AlbumContextMenuState,
  initialAlbumContextMenuState,
} from '../types';
import { useIntersectionObserver } from '../../../hooks/useIntersectionObserver';
import { AlbumArtwork } from '../../AlbumArtwork';
import { AlbumContextMenu } from '../AlbumContextMenu';
import { AlphabetBar, useAlphabetBar } from '../AlphabetBar';
import { usePlayerStore } from '../../../stores/playerStore';
import { useDownloadStore, getAlbumJobId } from '../../../stores/downloadStore';
import { getOfflineTrackIds, removeOfflineTrack } from '../../../services/offlineService';
import { useGridColumns } from '../../../hooks/useGridColumns';

const PAGE_SIZE = 50;

// Register this browser
registerBrowser(
  {
    id: 'album-grid',
    name: 'Albums',
    description: 'Browse albums in a visual grid with artwork',
    icon: 'Grid3X3',
    category: 'traditional',
    requiresFeatures: false,
    requiresEmbeddings: false,
  },
  AlbumGrid
);

export function AlbumGrid({
  filters,
  onGoToAlbum,
  onGoToArtist,
  onGoToYear,
}: BrowserProps) {
  const [sortBy, setSortBy] = useState<'name' | 'year' | 'artist' | 'track_count'>('name');
  const [albumContextMenu, setAlbumContextMenu] = useState<AlbumContextMenuState>(initialAlbumContextMenuState);
  const [offlineTrackIds, setOfflineTrackIds] = useState<Set<string>>(new Set());
  const setQueue = usePlayerStore((s) => s.setQueue);
  const addToQueue = usePlayerStore((s) => s.addToQueue);
  const { startDownload } = useDownloadStore();
  const queryClient = useQueryClient();
  const cols = useGridColumns();

  // Load offline track IDs on mount
  useEffect(() => {
    getOfflineTrackIds().then((ids) => setOfflineTrackIds(new Set(ids)));
  }, []);

  const closeAlbumContextMenu = useCallback(() => {
    setAlbumContextMenu(initialAlbumContextMenuState);
  }, []);

  const handleAlbumContextMenu = useCallback(
    (
      album: { name: string; artist: string; year: number | null; first_track_id: string },
      e: React.MouseEvent
    ) => {
      e.preventDefault();
      e.stopPropagation();
      setAlbumContextMenu({
        isOpen: true,
        album,
        position: { x: e.clientX, y: e.clientY },
      });
    },
    []
  );

  // --- Infinite query (shared by mobile & desktop) ---
  const {
    data,
    isLoading,
    error,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ['library-albums', { search: filters.search, artist: filters.artist, sortBy }],
    queryFn: ({ pageParam = 1 }) =>
      libraryApi.listAlbums({
        search: filters.search,
        artist: filters.artist,
        sort_by: sortBy,
        page: pageParam,
        page_size: PAGE_SIZE,
      }),
    getNextPageParam: (lastPage) => {
      const totalPages = Math.ceil(lastPage.total / PAGE_SIZE);
      return lastPage.page < totalPages ? lastPage.page + 1 : undefined;
    },
    initialPageParam: 1,
  });

  const total = data?.pages[0]?.total ?? 0;

  // --- Sparse page loading (desktop virtualizer) ---
  const loadedPagesRef = useRef<Set<number>>(new Set([1]));
  const [sparsePages, setSparsePages] = useState<Map<number, AlbumSummary[]>>(new Map());

  const fetchPage = useCallback(async (pageNumber: number) => {
    if (loadedPagesRef.current.has(pageNumber)) return;
    loadedPagesRef.current.add(pageNumber);

    try {
      const result = await libraryApi.listAlbums({
        search: filters.search,
        artist: filters.artist,
        sort_by: sortBy,
        page: pageNumber,
        page_size: PAGE_SIZE,
      });
      setSparsePages(prev => new Map(prev).set(pageNumber, result.items));
    } catch {
      loadedPagesRef.current.delete(pageNumber);
    }
  }, [filters.search, filters.artist, sortBy]);

  // Reset sparse state on filter/sort changes
  useEffect(() => {
    loadedPagesRef.current = new Set([1]);
    setSparsePages(new Map());
  }, [filters.search, filters.artist, sortBy]);

  // Track pages from infinite query
  useEffect(() => {
    if (data?.pages) {
      data.pages.forEach(page => loadedPagesRef.current.add(page.page));
    }
  }, [data?.pages]);

  // Build sparse array merging infinite query + direct-fetched pages
  const allAlbumsSparse = useMemo(() => {
    if (total === 0) return [];
    const arr: (AlbumSummary | undefined)[] = new Array(total);

    data?.pages.forEach(page => {
      const startIdx = (page.page - 1) * PAGE_SIZE;
      page.items.forEach((item, i) => { arr[startIdx + i] = item; });
    });

    sparsePages.forEach((items, pageNum) => {
      const startIdx = (pageNum - 1) * PAGE_SIZE;
      items.forEach((item, i) => { arr[startIdx + i] = item; });
    });

    return arr;
  }, [data?.pages, sparsePages, total]);

  // Dense array for mobile view
  const allAlbumsDense = useMemo(
    () => data?.pages.flatMap((page) => page.items) ?? [],
    [data]
  );

  // --- Desktop virtualizer (row-based) ---
  const desktopScrollRef = useRef<HTMLDivElement>(null);
  const rowCount = Math.ceil(total / cols);

  // Estimate row height: card is square (width / cols) + text area (~92px for p-3 + name + artist + year)
  const estimateRowSize = useCallback(() => {
    const scrollEl = desktopScrollRef.current;
    if (!scrollEl) return 240;
    const gap = 16; // gap-4 = 16px
    const cardWidth = (scrollEl.clientWidth - gap * (cols - 1)) / cols;
    return cardWidth + 92 + gap; // square image + text area + gap
  }, [cols]);

  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => desktopScrollRef.current,
    estimateSize: estimateRowSize,
    overscan: 3,
  });

  // Re-measure when column count changes
  useEffect(() => {
    virtualizer.measure();
  }, [cols, virtualizer]);

  // Fetch pages for visible rows
  useEffect(() => {
    const virtualItems = virtualizer.getVirtualItems();
    if (virtualItems.length === 0) return;

    const firstRow = virtualItems[0].index;
    const lastRow = virtualItems[virtualItems.length - 1].index;

    const firstItemIdx = firstRow * cols;
    const lastItemIdx = Math.min(lastRow * cols + cols - 1, total - 1);

    const firstPage = Math.floor(firstItemIdx / PAGE_SIZE) + 1;
    const lastPage = Math.floor(lastItemIdx / PAGE_SIZE) + 1;

    const missingPages: number[] = [];
    for (let p = firstPage; p <= lastPage; p++) {
      if (!loadedPagesRef.current.has(p)) {
        missingPages.push(p);
      }
    }

    if (missingPages.length > 0) {
      missingPages.forEach(p => fetchPage(p));
    } else if (lastItemIdx >= total - 1 && hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [virtualizer.getVirtualItems(), cols, total, hasNextPage, isFetchingNextPage, fetchNextPage, fetchPage]);

  // scrollToIndex for alphabet bar: convert item index to row index
  const scrollToIndex = useCallback((itemIndex: number) => {
    const rowIndex = Math.floor(itemIndex / cols);
    virtualizer.scrollToIndex(rowIndex, { align: 'start', behavior: 'auto' });
  }, [cols, virtualizer]);

  // --- Alphabet bar ---
  const {
    letterIndex,
    activeLetter,
    isVisible: isAlphabetBarVisible,
    isJumping,
    jumpToLetter,
  } = useAlphabetBar({
    entityType: 'albums',
    sortField: sortBy === 'name' ? 'name' : sortBy === 'artist' ? 'artist' : sortBy,
    filters: {
      search: filters.search,
      artist: filters.artist,
    },
    total,
    pageSize: PAGE_SIZE,
    fetchNextPage,
    hasNextPage: hasNextPage ?? false,
    loadedItemCount: total, // Sparse array covers full total
    scrollToIndex,
  });

  // --- Mobile infinite scroll ---
  const handleLoadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const sentinelRef = useIntersectionObserver({
    onIntersect: handleLoadMore,
    enabled: hasNextPage && !isFetchingNextPage,
  });

  // --- Render ---
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-red-500">Error loading albums</div>
      </div>
    );
  }

  if (total === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
        <Grid3X3 className="w-12 h-12 mb-4 opacity-50" />
        <p>No albums found</p>
        {filters.search && (
          <p className="text-sm mt-1">Try adjusting your search</p>
        )}
      </div>
    );
  }

  const sortControls = (
    <div className="flex items-center gap-2 mb-4 flex-shrink-0">
      <span className="text-sm text-zinc-400">Sort by:</span>
      <div className="flex gap-1">
        {[
          { value: 'name', label: 'Name' },
          { value: 'artist', label: 'Artist' },
          { value: 'year', label: 'Year' },
          { value: 'track_count', label: 'Tracks' },
        ].map((option) => (
          <button
            key={option.value}
            onClick={() => setSortBy(option.value as typeof sortBy)}
            className={`px-3 py-1 text-sm rounded-md transition-colors ${
              sortBy === option.value
                ? 'bg-purple-500/30 text-purple-300'
                : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-white'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
      <span className="ml-auto text-sm text-zinc-500">
        {total} album{total !== 1 ? 's' : ''}
      </span>
    </div>
  );

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Mobile view — intersection-observer infinite scroll */}
      <div className="md:hidden p-4" data-alphabet-scroll-container>
        {sortControls}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 sm:gap-4">
          {allAlbumsDense.map((album, index) => (
            <AlbumCard
              key={`${album.artist}-${album.name}`}
              album={album}
              index={index}
              onClick={() => onGoToAlbum(album.artist, album.name)}
              onGoToYear={onGoToYear}
              onContextMenu={(e) => handleAlbumContextMenu(album, e)}
            />
          ))}
        </div>
        {isFetchingNextPage && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
          </div>
        )}
        {hasNextPage && <div ref={sentinelRef} className="h-4" />}
      </div>

      {/* Desktop view — virtualized grid */}
      <div className="hidden md:flex md:flex-col md:h-full md:min-h-0 p-4">
        {sortControls}
        <div
          ref={desktopScrollRef}
          className="flex-1 overflow-auto min-h-0"
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
              const rowStartIdx = virtualRow.index * cols;

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
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2 sm:gap-4">
                    {Array.from({ length: cols }, (_, colIdx) => {
                      const itemIdx = rowStartIdx + colIdx;
                      if (itemIdx >= total) return null;

                      const album = allAlbumsSparse[itemIdx];
                      if (!album) {
                        return <AlbumCardPlaceholder key={itemIdx} />;
                      }

                      return (
                        <AlbumCard
                          key={`${album.artist}-${album.name}`}
                          album={album}
                          index={itemIdx}
                          onClick={() => onGoToAlbum(album.artist, album.name)}
                          onGoToYear={onGoToYear}
                          onContextMenu={(e) => handleAlbumContextMenu(album, e)}
                        />
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Album context menu */}
      {albumContextMenu.isOpen && albumContextMenu.album && (
        <AlbumContextMenu
          album={albumContextMenu.album}
          position={albumContextMenu.position}
          onClose={closeAlbumContextMenu}
          onPlay={async () => {
            const album = albumContextMenu.album!;
            const albumData = await queryClient.fetchQuery({
              queryKey: ['album', album.artist, album.name],
              queryFn: () => libraryApi.getAlbum(album.artist, album.name),
            });
            const tracks = albumData.tracks.map((t) => ({
              id: t.id,
              file_path: '',
              title: t.title || null,
              artist: albumData.artist,
              album: albumData.name,
              album_artist: albumData.album_artist,
              album_type: 'album' as const,
              track_number: t.track_number,
              disc_number: t.disc_number,
              year: albumData.year,
              genre: albumData.genre,
              duration_seconds: t.duration_seconds || null,
              format: null,
              analysis_version: 0,
            }));
            setQueue(tracks, 0);
          }}
          onShuffle={async () => {
            const album = albumContextMenu.album!;
            const albumData = await queryClient.fetchQuery({
              queryKey: ['album', album.artist, album.name],
              queryFn: () => libraryApi.getAlbum(album.artist, album.name),
            });
            const tracks = albumData.tracks.map((t) => ({
              id: t.id,
              file_path: '',
              title: t.title || null,
              artist: albumData.artist,
              album: albumData.name,
              album_artist: albumData.album_artist,
              album_type: 'album' as const,
              track_number: t.track_number,
              disc_number: t.disc_number,
              year: albumData.year,
              genre: albumData.genre,
              duration_seconds: t.duration_seconds || null,
              format: null,
              analysis_version: 0,
            }));
            const shuffled = [...tracks].sort(() => Math.random() - 0.5);
            setQueue(shuffled, 0);
          }}
          onQueue={async () => {
            const album = albumContextMenu.album!;
            const albumData = await queryClient.fetchQuery({
              queryKey: ['album', album.artist, album.name],
              queryFn: () => libraryApi.getAlbum(album.artist, album.name),
            });
            for (const t of albumData.tracks) {
              addToQueue({
                id: t.id,
                file_path: '',
                title: t.title || null,
                artist: albumData.artist,
                album: albumData.name,
                album_artist: albumData.album_artist,
                album_type: 'album',
                track_number: t.track_number,
                disc_number: t.disc_number,
                year: albumData.year,
                genre: albumData.genre,
                duration_seconds: t.duration_seconds || null,
                format: null,
                analysis_version: 0,
              });
            }
          }}
          onGoToArtist={() => {
            if (albumContextMenu.album) {
              onGoToArtist(albumContextMenu.album.artist);
            }
          }}
          onGoToAlbum={() => {
            if (albumContextMenu.album) {
              onGoToAlbum(albumContextMenu.album.artist, albumContextMenu.album.name);
            }
          }}
          onDownload={async () => {
            const album = albumContextMenu.album!;
            const albumData = await queryClient.fetchQuery({
              queryKey: ['album', album.artist, album.name],
              queryFn: () => libraryApi.getAlbum(album.artist, album.name),
            });
            const trackIds = albumData.tracks.map((t) => t.id);
            const jobId = getAlbumJobId(album.artist, album.name);
            startDownload(
              jobId,
              'album',
              `${album.artist} - ${album.name}`,
              trackIds
            );
          }}
          onRemoveDownload={async () => {
            const album = albumContextMenu.album!;
            const albumData = await queryClient.fetchQuery({
              queryKey: ['album', album.artist, album.name],
              queryFn: () => libraryApi.getAlbum(album.artist, album.name),
            });
            for (const t of albumData.tracks) {
              if (offlineTrackIds.has(t.id)) {
                await removeOfflineTrack(t.id);
              }
            }
            const ids = await getOfflineTrackIds();
            setOfflineTrackIds(new Set(ids));
          }}
          hasDownloadedTracks={(() => {
            return offlineTrackIds.size > 0;
          })()}
          onAddToPlaylist={() => {
            // TODO: Open playlist picker modal
          }}
          onMakePlaylist={() => {
            if (albumContextMenu.album) {
              const album = albumContextMenu.album;
              const message = `Make me a playlist based on the album "${album.name}" by ${album.artist}`;
              window.dispatchEvent(new CustomEvent('trigger-chat', { detail: { message } }));
            }
          }}
        />
      )}

      {/* Alphabet bar for quick navigation */}
      <AlphabetBar
        letterIndex={letterIndex}
        activeLetter={activeLetter}
        onLetterSelect={jumpToLetter}
        visible={isAlphabetBarVisible}
        isJumping={isJumping}
      />
    </div>
  );
}

interface AlbumCardProps {
  album: {
    name: string;
    artist: string;
    year: number | null;
    track_count: number;
    first_track_id: string;
  };
  index: number;
  onClick: () => void;
  onGoToYear: (year: number) => void;
  onContextMenu: (e: React.MouseEvent) => void;
}

function AlbumCard({ album, index, onClick, onGoToYear, onContextMenu }: AlbumCardProps) {
  return (
    <div
      role="button"
      tabIndex={0}
      data-list-index={index}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick();
        }
      }}
      onContextMenu={onContextMenu}
      className="group text-left bg-zinc-800/30 rounded-lg overflow-hidden hover:bg-zinc-800 transition-colors cursor-pointer"
    >
      {/* Album artwork */}
      <div className="aspect-square relative overflow-hidden">
        <AlbumArtwork
          artist={album.artist}
          album={album.name}
          trackId={album.first_track_id}
          size="thumb"
          className="w-full h-full group-hover:scale-105 transition-transform duration-300"
        />

        {/* Track count badge */}
        <div className="absolute bottom-2 right-2 px-2 py-0.5 bg-black/70 backdrop-blur-sm rounded text-xs text-white z-10">
          {album.track_count} track{album.track_count !== 1 ? 's' : ''}
        </div>
      </div>

      {/* Album info */}
      <div className="p-3">
        <div className="font-medium text-white truncate" title={album.name}>
          {album.name}
        </div>
        <div className="text-sm text-zinc-400 truncate" title={album.artist}>
          {album.artist}
        </div>
        {album.year && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onGoToYear(album.year!);
            }}
            className="text-xs text-zinc-500 mt-1 hover:text-white hover:underline transition-colors"
          >
            {album.year}
          </button>
        )}
      </div>
    </div>
  );
}

function AlbumCardPlaceholder() {
  return (
    <div className="bg-zinc-800/30 rounded-lg overflow-hidden">
      <div className="aspect-square bg-zinc-700 animate-pulse" />
      <div className="p-3">
        <div className="h-4 w-24 bg-zinc-700 rounded animate-pulse mb-1" />
        <div className="h-3 w-20 bg-zinc-700/50 rounded animate-pulse mb-1" />
        <div className="h-3 w-10 bg-zinc-700/30 rounded animate-pulse" />
      </div>
    </div>
  );
}
