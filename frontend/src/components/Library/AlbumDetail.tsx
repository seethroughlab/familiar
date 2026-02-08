import { useState, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowLeft,
  Play,
  Pause,
  Loader2,
  Music,
  Clock,
  Heart,
  Download,
  Check,
} from 'lucide-react';
import { libraryApi, playlistsApi } from '../../api/client';
import { AlbumArtwork } from '../AlbumArtwork';
import { usePlayerStore } from '../../stores/playerStore';
import { useSelectionStore } from '../../stores/selectionStore';
import { useFavorites } from '../../hooks/useFavorites';
import { useOfflineTrack } from '../../hooks/useOfflineTrack';
import { useOfflineAlbum } from '../../hooks/useOfflineAlbum';
import { TrackContextMenu } from './TrackContextMenu';
import type { ContextMenuState } from './types';
import { initialContextMenuState } from './types';
import type { Track } from '../../types';
import { DiscoveryPanel, useAlbumDiscovery, type DiscoveryItem } from '../Discovery';

import { createLogger } from '../../utils/logger';

const log = createLogger('AlbumDetail');

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

// Album Discovery Section using unified components
function AlbumDiscoverySection({
  album,
  onGoToAlbum,
  onPlayAlbum,
}: {
  album: {
    artist: string;
    other_albums_by_artist: Array<{
      name: string;
      artist: string;
      year: number | null;
      track_count: number;
      first_track_id: string;
    }>;
    similar_albums: Array<{
      name: string;
      artist: string;
      year: number | null;
      track_count: number;
      first_track_id: string;
      similarity_score: number;
    }>;
    discover_albums: Array<{
      name: string;
      artist: string;
      image_url: string | null;
      lastfm_url: string | null;
      bandcamp_url: string | null;
    }>;
  };
  onGoToAlbum?: (artistName: string, albumName: string) => void;
  onPlayAlbum: (artistName: string, albumName: string) => void;
}) {
  const { sections, hasDiscovery } = useAlbumDiscovery({ album });

  if (!hasDiscovery) return null;

  const handleItemClick = (item: DiscoveryItem) => {
    if (item.inLibrary && item.playbackContext) {
      onGoToAlbum?.(item.playbackContext.artist, item.playbackContext.album || item.name);
    }
  };

  const handleItemPlay = (item: DiscoveryItem) => {
    if (item.playbackContext) {
      onPlayAlbum(item.playbackContext.artist, item.playbackContext.album || item.name);
    }
  };

  const handleAddToWishlist = async (item: DiscoveryItem) => {
    if (!item.inLibrary && item.name) {
      try {
        await playlistsApi.addToWishlist({
          title: item.name,
          artist: item.subtitle || 'Unknown Artist',
        });
      } catch (err) {
        log.error('Failed to add to wishlist:', err);
      }
    }
  };

  return (
    <DiscoveryPanel
      sections={sections}
      collapsible
      onItemClick={handleItemClick}
      onItemPlay={handleItemPlay}
      onAddToWishlist={handleAddToWishlist}
    />
  );
}

interface Props {
  artistName: string;
  albumName: string;
  onBack: () => void;
  onGoToArtist?: (artistName: string) => void;
  onGoToAlbum?: (artistName: string, albumName: string) => void;
  onGoToYear?: (year: number) => void;
  onGoToGenre?: (genre: string) => void;
}

export function AlbumDetail({
  artistName,
  albumName,
  onBack,
  onGoToArtist,
  onGoToAlbum,
  onGoToYear,
  onGoToGenre,
}: Props) {
  const { currentTrack, isPlaying, setQueue, addToQueue, setIsPlaying } =
    usePlayerStore();
  const [contextMenu, setContextMenu] =
    useState<ContextMenuState>(initialContextMenuState);
  const [selectedTrackIds, setSelectedTrackIds] = useState<Set<string>>(new Set());
  const [lastClickedId, setLastClickedId] = useState<string | null>(null);

  const handleContextMenu = useCallback((track: Track, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({
      isOpen: true,
      track,
      position: { x: e.clientX, y: e.clientY },
    });
  }, []);

  const closeContextMenu = useCallback(() => {
    setContextMenu(initialContextMenuState);
  }, []);

  const { data: album, isLoading } = useQuery({
    queryKey: ['album', artistName, albumName],
    queryFn: () => libraryApi.getAlbum(artistName, albumName),
  });

  const handlePlayAll = () => {
    if (!album || album.tracks.length === 0) return;

    const queueTracks = album.tracks.map((t) => ({
      id: t.id,
      file_path: '',
      title: t.title || 'Unknown',
      artist: album.artist,
      album: album.name,
      album_artist: album.album_artist,
      album_type: 'album' as const,
      track_number: t.track_number,
      disc_number: t.disc_number,
      year: album.year,
      genre: album.genre,
      duration_seconds: t.duration_seconds,
      format: null,
      analysis_version: 0,
    }));
    setQueue(queueTracks, 0);
  };

  const handlePlayTrack = (trackIndex: number) => {
    if (!album || album.tracks.length === 0) return;

    const clickedTrack = album.tracks[trackIndex];
    if (clickedTrack && currentTrack?.id === clickedTrack.id) {
      setIsPlaying(!isPlaying);
      return;
    }

    const queueTracks = album.tracks.map((t) => ({
      id: t.id,
      file_path: '',
      title: t.title || 'Unknown',
      artist: album.artist,
      album: album.name,
      album_artist: album.album_artist,
      album_type: 'album' as const,
      track_number: t.track_number,
      disc_number: t.disc_number,
      year: album.year,
      genre: album.genre,
      duration_seconds: t.duration_seconds,
      format: null,
      analysis_version: 0,
    }));
    setQueue(queueTracks, trackIndex);
  };

  const handleTrackClick = useCallback((trackId: string, idx: number, e: React.MouseEvent) => {
    if (!album) return;

    if (e.shiftKey && lastClickedId) {
      // Shift-click: select range
      const lastIdx = album.tracks.findIndex(t => t.id === lastClickedId);
      const [start, end] = [Math.min(lastIdx, idx), Math.max(lastIdx, idx)];
      const rangeIds = album.tracks.slice(start, end + 1).map(t => t.id);
      setSelectedTrackIds(new Set([...selectedTrackIds, ...rangeIds]));
    } else if (e.metaKey || e.ctrlKey) {
      // Cmd/Ctrl-click: toggle single selection
      const newSet = new Set(selectedTrackIds);
      if (newSet.has(trackId)) newSet.delete(trackId);
      else newSet.add(trackId);
      setSelectedTrackIds(newSet);
    } else {
      // Plain click: select only this track
      setSelectedTrackIds(new Set([trackId]));
    }
    setLastClickedId(trackId);
  }, [album, lastClickedId, selectedTrackIds]);

  const handlePlayOtherAlbum = async (artistName: string, albumName: string) => {
    try {
      const otherAlbum = await libraryApi.getAlbum(artistName, albumName);
      if (otherAlbum.tracks.length === 0) return;

      const queueTracks = otherAlbum.tracks.map((t) => ({
        id: t.id,
        file_path: '',
        title: t.title || 'Unknown',
        artist: otherAlbum.artist,
        album: otherAlbum.name,
        album_artist: otherAlbum.album_artist,
        album_type: 'album' as const,
        track_number: t.track_number,
        disc_number: t.disc_number,
        year: otherAlbum.year,
        genre: otherAlbum.genre,
        duration_seconds: t.duration_seconds,
        format: null,
        analysis_version: 0,
      }));
      setQueue(queueTracks, 0);
    } catch (error) {
      log.error('Failed to play album:', error);
    }
  };

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const formatTotalDuration = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    if (hours > 0) {
      return `${hours}h ${mins}m`;
    }
    return `${mins} min`;
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }

  if (!album) {
    return (
      <div className="text-center py-12 text-zinc-500">
        <p>Album not found</p>
        <button
          onClick={onBack}
          className="mt-4 text-green-500 hover:text-green-400"
        >
          Go back
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-6 px-4 md:px-0">
      {/* Header - stacks vertically on mobile */}
      <div className="space-y-4">
        {/* Back button */}
        <button
          onClick={onBack}
          className="p-2 hover:bg-zinc-800 rounded-lg transition-colors -ml-2"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>

        {/* Album info row - horizontal on desktop, adapts on mobile */}
        <div className="flex flex-col sm:flex-row gap-4">
          {/* Album artwork */}
          <div className="w-32 h-32 sm:w-40 sm:h-40 rounded-lg bg-zinc-800 overflow-hidden flex-shrink-0 mx-auto sm:mx-0">
            <AlbumArtwork
              artist={album.artist}
              album={album.name}
              trackId={album.first_track_id}
              size="full"
              className="w-full h-full"
            />
          </div>

          <div className="flex-1 min-w-0 text-center sm:text-left">
            <h2 className="text-xl sm:text-2xl font-bold">{album.name}</h2>

            {/* Artist link */}
            <button
              onClick={() => onGoToArtist?.(album.artist)}
              className="text-base sm:text-lg text-zinc-400 hover:text-white hover:underline transition-colors"
            >
              {album.artist}
            </button>

            {/* Stats row - wraps on mobile */}
            <div className="flex flex-wrap items-center justify-center sm:justify-start gap-x-4 gap-y-1 mt-2 text-sm text-zinc-400">
              {album.year && (
                <button
                  onClick={() => onGoToYear?.(album.year!)}
                  className="flex items-center gap-1 hover:text-white hover:underline transition-colors"
                >
                  {album.year}
                </button>
              )}
              <span className="flex items-center gap-1">
                <Music className="w-4 h-4" />
                {album.track_count} tracks
              </span>
              <span className="flex items-center gap-1">
                <Clock className="w-4 h-4" />
                {formatTotalDuration(album.total_duration_seconds)}
              </span>
            </div>

            {/* Genre */}
            {album.genre && (
              <div className="mt-2">
                <button
                  onClick={() => onGoToGenre?.(album.genre!)}
                  className="px-2 py-0.5 text-xs bg-zinc-800 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded transition-colors"
                >
                  {album.genre}
                </button>
              </div>
            )}

            {/* Desktop actions */}
            <div className="hidden sm:flex items-center gap-2 mt-3">
              <button
                onClick={handlePlayAll}
                disabled={album.tracks.length === 0}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded-full transition-colors"
              >
                <Play className="w-4 h-4" fill="currentColor" />
                Play
              </button>
              <AlbumOfflineButton tracks={album.tracks} artist={album.artist} album={album.name} />
            </div>
          </div>
        </div>

        {/* Mobile-only actions row */}
        <div className="flex sm:hidden items-center justify-center gap-3">
          <button
            onClick={handlePlayAll}
            disabled={album.tracks.length === 0}
            className="flex items-center gap-2 px-6 py-2.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded-full transition-colors"
          >
            <Play className="w-5 h-5" fill="currentColor" />
            Play
          </button>
          <AlbumOfflineButton tracks={album.tracks} artist={album.artist} album={album.name} />
        </div>
      </div>

      {/* Tracks */}
      <div>
        <h3 className="text-lg font-semibold mb-3">Tracks</h3>
        <div className="space-y-1">
          {album.tracks.map((track, idx) => {
            const fullTrack: Track = {
              id: track.id,
              file_path: '',
              title: track.title || null,
              artist: album.artist,
              album: album.name,
              album_artist: album.album_artist,
              album_type: 'album',
              track_number: track.track_number,
              disc_number: track.disc_number,
              year: album.year,
              genre: album.genre,
              duration_seconds: track.duration_seconds,
              format: null,
              analysis_version: 0,
            };
            return (
              <div
                key={track.id}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData('application/track-id', track.id);
                  e.dataTransfer.effectAllowed = 'copy';
                }}
                onClick={(e) => handleTrackClick(track.id, idx, e)}
                onDoubleClick={() => handlePlayTrack(idx)}
                onMouseDown={(e) => {
                  if (e.shiftKey || e.metaKey || e.ctrlKey) e.preventDefault();
                }}
                onContextMenu={(e) => handleContextMenu(fullTrack, e)}
                className={`group flex items-center gap-3 p-2 rounded-lg hover:bg-zinc-800/50 cursor-pointer transition-colors ${
                  selectedTrackIds.has(track.id)
                    ? 'bg-purple-500/20 hover:bg-purple-500/30'
                    : currentTrack?.id === track.id
                      ? 'bg-zinc-800/30'
                      : ''
                }`}
              >
                <div className="w-8 text-center">
                  {currentTrack?.id === track.id && isPlaying ? (
                    <>
                      <div className="group-hover:hidden flex justify-center gap-0.5">
                        <div className="w-0.5 h-3 bg-green-500 animate-pulse" />
                        <div className="w-0.5 h-3 bg-green-500 animate-pulse [animation-delay:0.2s]" />
                        <div className="w-0.5 h-3 bg-green-500 animate-pulse [animation-delay:0.4s]" />
                      </div>
                      <button
                        onClick={(e) => { e.stopPropagation(); handlePlayTrack(idx); }}
                        className="hidden group-hover:block"
                      >
                        <Pause className="w-4 h-4 mx-auto text-white" fill="currentColor" />
                      </button>
                    </>
                  ) : currentTrack?.id === track.id ? (
                    <>
                      <span className="group-hover:hidden text-sm text-green-500">
                        {track.track_number || idx + 1}
                      </span>
                      <button
                        onClick={(e) => { e.stopPropagation(); handlePlayTrack(idx); }}
                        className="hidden group-hover:block"
                      >
                        <Play className="w-4 h-4 mx-auto text-white" fill="currentColor" />
                      </button>
                    </>
                  ) : (
                    <>
                      <span className="group-hover:hidden text-sm text-zinc-500">
                        {track.track_number || idx + 1}
                      </span>
                      <button
                        onClick={(e) => { e.stopPropagation(); handlePlayTrack(idx); }}
                        className="hidden group-hover:block"
                      >
                        <Play className="w-4 h-4 mx-auto text-white" fill="currentColor" />
                      </button>
                    </>
                  )}
                </div>

                <div className="flex-1 min-w-0">
                  <div
                    className={`font-medium truncate ${currentTrack?.id === track.id ? 'text-green-500' : ''}`}
                  >
                    {track.title || 'Unknown Title'}
                  </div>
                </div>

                <div className="text-sm text-zinc-500">
                  {formatDuration(track.duration_seconds)}
                </div>

                <FavoriteButton trackId={track.id} />
                <OfflineButton trackId={track.id} />
              </div>
            );
          })}
        </div>
      </div>

      {/* Discovery section - More from Artist + Similar Albums */}
      <AlbumDiscoverySection
        album={album}
        onGoToAlbum={onGoToAlbum}
        onPlayAlbum={handlePlayOtherAlbum}
      />

      {/* Context menu */}
      {contextMenu.isOpen && contextMenu.track && (
        <TrackContextMenu
          track={contextMenu.track}
          position={contextMenu.position}
          isSelected={selectedTrackIds.has(contextMenu.track.id)}
          selectedCount={selectedTrackIds.size}
          onClose={closeContextMenu}
          onPlay={() => {
            const idx = album.tracks.findIndex(
              (t) => t.id === contextMenu.track?.id
            );
            if (idx !== -1) handlePlayTrack(idx);
          }}
          onQueue={() => {
            if (contextMenu.track) {
              addToQueue(contextMenu.track);
            }
          }}
          onGoToArtist={() => {
            onGoToArtist?.(album.artist);
          }}
          onGoToAlbum={() => {
            // Already on this album
          }}
          onToggleSelect={() => {
            if (contextMenu.track) {
              const newSet = new Set(selectedTrackIds);
              if (newSet.has(contextMenu.track.id)) {
                newSet.delete(contextMenu.track.id);
              } else {
                newSet.add(contextMenu.track.id);
              }
              setSelectedTrackIds(newSet);
            }
          }}
          onClearSelection={() => setSelectedTrackIds(new Set())}
          onAddToPlaylist={() => {
            
          }}
          onMakePlaylist={() => {
            if (contextMenu.track) {
              const track = contextMenu.track;
              const message = `Make me a playlist based on "${track.title || 'this track'}" by ${track.artist || 'Unknown Artist'}`;
              window.dispatchEvent(
                new CustomEvent('trigger-chat', { detail: { message } })
              );
            }
          }}
          onEditMetadata={() => {
            if (contextMenu.track) {
              if (selectedTrackIds.size > 1 && selectedTrackIds.has(contextMenu.track.id)) {
                useSelectionStore.getState().selectAll(Array.from(selectedTrackIds));
              }
              useSelectionStore.getState().setEditingTrackId(contextMenu.track.id);
            }
          }}
        />
      )}
    </div>
  );
}
