/**
 * AlbumGrid Browser - Shows albums in a responsive grid with artwork.
 *
 * Uses infinite scroll to load albums progressively as you scroll.
 * Clicking an album filters the library to show its tracks.
 */
import { useState, useCallback, useEffect } from 'react';
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { Grid3X3, Loader2 } from 'lucide-react';
import { libraryApi } from '../../../api/client';
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
  const { setQueue, addToQueue } = usePlayerStore();
  const { startDownload } = useDownloadStore();
  const queryClient = useQueryClient();

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
  const allAlbums = data?.pages.flatMap((page) => page.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;

  // Alphabet bar for quick navigation (only when sorted by name or artist)
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
    loadedItemCount: allAlbums.length,
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
        <div className="text-red-500">Error loading albums</div>
      </div>
    );
  }

  if (!allAlbums.length) {
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

  return (
    <div className="p-4" data-alphabet-scroll-container>
      {/* Sort controls */}
      <div className="flex items-center gap-2 mb-4">
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
          {allAlbums.length} of {total} album{total !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Album grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2 sm:gap-4">
        {allAlbums.map((album, index) => (
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

      {/* Loading indicator and sentinel for infinite scroll */}
      {isFetchingNextPage && (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
        </div>
      )}

      {/* Invisible sentinel element that triggers loading when scrolled into view */}
      {hasNextPage && <div ref={sentinelRef} className="h-4" />}

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
            // Shuffle the tracks before setting queue
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
            // Refresh offline IDs
            const ids = await getOfflineTrackIds();
            setOfflineTrackIds(new Set(ids));
          }}
          hasDownloadedTracks={(() => {
            // Check if any album tracks are downloaded
            // This is approximate - we check if any track from this artist/album combo is offline
            // A more accurate check would require fetching album tracks
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
