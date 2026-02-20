/**
 * ArtistList Browser - Shows artists in a visual grid with artwork.
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
import { useInfiniteQuery } from '@tanstack/react-query';
import { Users, Loader2 } from 'lucide-react';
import { libraryApi, tracksApi, type ArtistSummary } from '../../../api';
import { registerBrowser, type BrowserProps } from '../types';
import { useIntersectionObserver } from '../../../hooks/useIntersectionObserver';
import { AlphabetBar, useAlphabetBar } from '../AlphabetBar';
import { useGridColumns } from '../../../hooks/useGridColumns';

const PAGE_SIZE = 50;

// Register this browser
registerBrowser(
  {
    id: 'artist-list',
    name: 'Artists',
    description: 'Browse artists in a visual grid with artwork',
    icon: 'Users',
    category: 'traditional',
    requiresFeatures: false,
    requiresEmbeddings: false,
  },
  ArtistList
);

export function ArtistList({
  filters,
  onGoToArtist,
}: BrowserProps) {
  const [sortBy, setSortBy] = useState<'name' | 'track_count' | 'album_count'>('name');
  const cols = useGridColumns();

  // --- Infinite query (shared by mobile & desktop) ---
  const {
    data,
    isLoading,
    error,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ['library-artists', { search: filters.search, sortBy }],
    queryFn: ({ pageParam = 1 }) =>
      libraryApi.listArtists({
        search: filters.search,
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
  const [sparsePages, setSparsePages] = useState<Map<number, ArtistSummary[]>>(new Map());

  const fetchPage = useCallback(async (pageNumber: number) => {
    if (loadedPagesRef.current.has(pageNumber)) return;
    loadedPagesRef.current.add(pageNumber);

    try {
      const result = await libraryApi.listArtists({
        search: filters.search,
        sort_by: sortBy,
        page: pageNumber,
        page_size: PAGE_SIZE,
      });
      setSparsePages(prev => new Map(prev).set(pageNumber, result.items));
    } catch {
      loadedPagesRef.current.delete(pageNumber);
    }
  }, [filters.search, sortBy]);

  // Reset sparse state on filter/sort changes
  useEffect(() => {
    loadedPagesRef.current = new Set([1]);
    setSparsePages(new Map());
  }, [filters.search, sortBy]);

  // Track pages from infinite query
  useEffect(() => {
    if (data?.pages) {
      data.pages.forEach(page => loadedPagesRef.current.add(page.page));
    }
  }, [data?.pages]);

  // Build sparse array merging infinite query + direct-fetched pages
  const allArtistsSparse = useMemo(() => {
    if (total === 0) return [];
    const arr: (ArtistSummary | undefined)[] = new Array(total);

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
  const allArtistsDense = useMemo(
    () => data?.pages.flatMap((page) => page.items) ?? [],
    [data]
  );

  // --- Desktop virtualizer (row-based) ---
  const desktopScrollRef = useRef<HTMLDivElement>(null);
  const rowCount = Math.ceil(total / cols);

  // Estimate row height: card is square (width / cols) + text area (~76px for p-3 + name + subtitle)
  const estimateRowSize = useCallback(() => {
    const scrollEl = desktopScrollRef.current;
    if (!scrollEl) return 220;
    const gap = 16; // gap-4 = 16px
    const cardWidth = (scrollEl.clientWidth - gap * (cols - 1)) / cols;
    return cardWidth + 76 + gap; // square image + text + gap between rows
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

    // Map rows to item index range
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
    entityType: 'artists',
    sortField: sortBy === 'name' ? 'name' : sortBy,
    filters: { search: filters.search },
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
        <div className="text-red-500">Error loading artists</div>
      </div>
    );
  }

  if (total === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
        <Users className="w-12 h-12 mb-4 opacity-50" />
        <p>No artists found</p>
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
          { value: 'track_count', label: 'Tracks' },
          { value: 'album_count', label: 'Albums' },
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
        {total} artist{total !== 1 ? 's' : ''}
      </span>
    </div>
  );

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Mobile view — intersection-observer infinite scroll */}
      <div className="md:hidden p-4" data-alphabet-scroll-container>
        {sortControls}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 sm:gap-4">
          {allArtistsDense.map((artist, index) => (
            <ArtistCard
              key={artist.name}
              artist={artist}
              index={index}
              onClick={() => onGoToArtist(artist.name)}
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

                      const artist = allArtistsSparse[itemIdx];
                      if (!artist) {
                        return <ArtistCardPlaceholder key={itemIdx} />;
                      }

                      return (
                        <ArtistCard
                          key={artist.name}
                          artist={artist}
                          index={itemIdx}
                          onClick={() => onGoToArtist(artist.name)}
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

interface ArtistCardProps {
  artist: {
    name: string;
    track_count: number;
    album_count: number;
    first_track_id: string;
  };
  index: number;
  onClick: () => void;
}

function ArtistCard({ artist, index, onClick }: ArtistCardProps) {
  const [imageError, setImageError] = useState(false);
  const [albumArtError, setAlbumArtError] = useState(false);

  return (
    <button
      onClick={onClick}
      data-list-index={index}
      className="group text-left bg-zinc-800/30 rounded-lg overflow-hidden hover:bg-zinc-800 transition-colors"
    >
      {/* Artist artwork - square aspect ratio */}
      <div className="aspect-square bg-zinc-700 relative overflow-hidden">
        {!imageError ? (
          <img
            src={libraryApi.getArtistImageUrl(artist.name, 'large')}
            alt={artist.name}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
            onError={() => setImageError(true)}
          />
        ) : !albumArtError ? (
          // Fallback to album artwork from first track
          <img
            src={tracksApi.getArtworkUrl(artist.first_track_id, 'thumb')}
            alt={artist.name}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
            onError={() => setAlbumArtError(true)}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <Users className="w-12 h-12 text-zinc-500" />
          </div>
        )}

        {/* Track count badge */}
        <div className="absolute bottom-2 right-2 px-2 py-0.5 bg-black/70 backdrop-blur-sm rounded text-xs text-white">
          {artist.track_count} track{artist.track_count !== 1 ? 's' : ''}
        </div>
      </div>

      {/* Artist info */}
      <div className="p-3">
        <div className="font-medium text-white truncate" title={artist.name}>
          {artist.name}
        </div>
        <div className="text-sm text-zinc-400 truncate">
          {artist.album_count} album{artist.album_count !== 1 ? 's' : ''}
        </div>
      </div>
    </button>
  );
}

function ArtistCardPlaceholder() {
  return (
    <div className="bg-zinc-800/30 rounded-lg overflow-hidden">
      <div className="aspect-square bg-zinc-700 animate-pulse" />
      <div className="p-3">
        <div className="h-4 w-24 bg-zinc-700 rounded animate-pulse mb-1" />
        <div className="h-3 w-16 bg-zinc-700/50 rounded animate-pulse" />
      </div>
    </div>
  );
}
