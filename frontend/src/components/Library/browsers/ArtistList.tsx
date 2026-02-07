/**
 * ArtistList Browser - Shows artists in a visual grid with artwork.
 *
 * Uses infinite scroll to load artists progressively as you scroll.
 * Clicking an artist opens the artist detail view.
 */
import { useState, useCallback } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { Users, Loader2 } from 'lucide-react';
import { libraryApi, tracksApi } from '../../../api/client';
import { registerBrowser, type BrowserProps } from '../types';
import { useIntersectionObserver } from '../../../hooks/useIntersectionObserver';
import { AlphabetBar, useAlphabetBar } from '../AlphabetBar';

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

  const handleLoadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const sentinelRef = useIntersectionObserver({
    onIntersect: handleLoadMore,
    enabled: hasNextPage && !isFetchingNextPage,
  });

  // Flatten all pages into a single array
  const allArtists = data?.pages.flatMap((page) => page.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;

  // Alphabet bar for quick navigation (only when sorted by name)
  const {
    letterIndex,
    activeLetter,
    isVisible: isAlphabetBarVisible,
    isJumping,
    jumpToLetter,
  } = useAlphabetBar({
    entityType: 'artists',
    sortField: sortBy === 'name' ? 'name' : sortBy, // Only alphabetic nav for name sort
    filters: {
      search: filters.search,
    },
    total,
    pageSize: PAGE_SIZE,
    fetchNextPage,
    hasNextPage: hasNextPage ?? false,
    loadedItemCount: allArtists.length,
  });

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

  if (!allArtists.length) {
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

  return (
    <div className="p-4" data-alphabet-scroll-container>
      {/* Sort controls */}
      <div className="flex items-center gap-2 mb-4">
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
          {allArtists.length} of {total} artist{total !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Artist grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2 sm:gap-4">
        {allArtists.map((artist, index) => (
          <ArtistCard
            key={artist.name}
            artist={artist}
            index={index}
            onClick={() => onGoToArtist(artist.name)}
          />
        ))}
      </div>

      {/* Loading indicator and sentinel for infinite scroll */}
      {isFetchingNextPage && (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
        </div>
      )}

      {/* Invisible sentinel element that triggers loading when scrolled into view */}
      {hasNextPage && <div ref={sentinelRef} className="h-4" />}

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
