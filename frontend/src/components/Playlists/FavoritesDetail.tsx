import { useState, useEffect, useCallback, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Play, Pause, Heart, Clock, Music, Search, X, Download, Check, Loader2, RotateCw } from 'lucide-react';
import { favoritesApi } from '../../api/client';
import { usePlayerStore } from '../../stores/playerStore';
import { useSelectionStore } from '../../stores/selectionStore';
import { useDownloadStore } from '../../stores/downloadStore';
import { useFavorites } from '../../hooks/useFavorites';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { useAutoDownload } from '../../hooks/useAutoDownload';
import { useAppNavigation } from '../../hooks/useAppNavigation';
import * as offlineService from '../../services/offlineService';
import { TrackContextMenu } from '../Library/TrackContextMenu';
import type { ContextMenuState } from '../Library/types';
import { initialContextMenuState } from '../Library/types';
import type { Track } from '../../types';

interface Props {
  onBack: () => void;
}

export function FavoritesDetail({ onBack }: Props) {
  const queryClient = useQueryClient();
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const setQueue = usePlayerStore((s) => s.setQueue);
  const addToQueue = usePlayerStore((s) => s.addToQueue);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const { favorites, total, toggle } = useFavorites();
  const { isOffline } = useOfflineStatus();
  const { navigateToArtist, navigateToAlbum } = useAppNavigation();
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(initialContextMenuState);
  const [searchFilter, setSearchFilter] = useState('');
  const [offlineTrackIds, setOfflineTrackIds] = useState<Set<string>>(new Set());

  // Download state
  const { jobs, startDownload } = useDownloadStore();
  const jobId = 'favorites';
  const downloadJob = jobs.get(jobId);
  const isDownloading = downloadJob?.status === 'downloading' || downloadJob?.status === 'queued';
  const downloadProgress = {
    current: downloadJob ? downloadJob.completedIds.length + (downloadJob.currentProgress > 0 ? 1 : 0) : 0,
    total: downloadJob?.trackIds.length ?? 0,
  };

  // Auto-download setting
  const { data: autoDownloadSetting } = useQuery({
    queryKey: ['favorites-auto-download'],
    queryFn: () => favoritesApi.getAutoDownload(),
    staleTime: 60000,
    retry: isOffline ? false : 3,
  });
  const autoDownloadEnabled = autoDownloadSetting?.enabled ?? false;

  // Check offline status
  useEffect(() => {
    const checkOfflineStatus = async () => {
      const ids = await offlineService.getOfflineTrackIds();
      setOfflineTrackIds(new Set(ids));
    };
    checkOfflineStatus();
  }, []);

  // Update offline track IDs when download job completes
  useEffect(() => {
    if (downloadJob?.status === 'completed' || downloadJob?.status === 'failed') {
      offlineService.getOfflineTrackIds().then((ids) => {
        setOfflineTrackIds(new Set(ids));
      });
    }
  }, [downloadJob?.status]);

  const favoriteTrackIds = useMemo(() => favorites.map(f => f.id), [favorites]);
  const allTracksOffline = favorites.length > 0 && favorites.every(f => offlineTrackIds.has(f.id));
  const offlineCount = favorites.filter(f => offlineTrackIds.has(f.id)).length;

  // Auto-download new tracks when enabled
  useAutoDownload({
    enabled: autoDownloadEnabled,
    jobId,
    jobType: 'playlist',
    jobName: 'Favorites',
    trackIds: favoriteTrackIds,
  });

  const handleDownloadFavorites = () => {
    if (favorites.length === 0) return;
    const tracksToDownload = favorites.filter(f => !offlineTrackIds.has(f.id));
    if (tracksToDownload.length === 0) return;
    startDownload(jobId, 'playlist', 'Favorites', tracksToDownload.map(f => f.id));
  };

  const filteredFavorites = useMemo(() => {
    if (!searchFilter) return favorites;
    const q = searchFilter.toLowerCase();
    return favorites.filter(t =>
      (t.title?.toLowerCase().includes(q)) ||
      (t.artist?.toLowerCase().includes(q)) ||
      (t.album?.toLowerCase().includes(q))
    );
  }, [favorites, searchFilter]);

  // Context menu handlers
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

  const handlePlay = (startIndex = 0) => {
    if (filteredFavorites.length === 0) return;

    // If clicking on the currently playing track, toggle play/pause
    const clickedTrack = filteredFavorites[startIndex];
    if (clickedTrack && currentTrack?.id === clickedTrack.id) {
      setIsPlaying(!isPlaying);
      return;
    }

    const queueTracks = filteredFavorites.map(t => ({
      id: t.id,
      file_path: '',
      title: t.title || 'Unknown',
      artist: t.artist || 'Unknown',
      album: t.album || null,
      album_artist: null,
      album_type: 'album' as const,
      track_number: null,
      disc_number: null,
      year: null,
      genre: null,
      duration_seconds: t.duration_seconds || null,
      format: null,
      analysis_version: 0,
    }));
    setQueue(queueTracks, startIndex);
  };

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const totalDuration = favorites.reduce(
    (sum, t) => sum + (t.duration_seconds || 0),
    0
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="space-y-4">
        <button
          onClick={onBack}
          className="p-2 hover:bg-zinc-800 rounded-lg transition-colors -ml-2"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>

        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Heart className="w-5 h-5 text-pink-500" fill="currentColor" />
            <h2 className="text-xl font-bold">Favorites</h2>
          </div>

          <div className="flex items-center gap-4 mt-2 text-sm text-zinc-500">
            <span>{total} tracks</span>
            <span className="flex items-center gap-1">
              <Clock className="w-4 h-4" />
              {Math.floor(totalDuration / 60)} min
            </span>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
          <button
            onClick={() => handlePlay()}
            disabled={favorites.length === 0}
            className="flex items-center justify-center gap-2 px-4 py-2 bg-pink-600 hover:bg-pink-500 disabled:opacity-50 disabled:hover:bg-pink-600 rounded-full transition-colors"
          >
            <Play className="w-4 h-4" fill="currentColor" />
            Play
          </button>

          <button
            onClick={handleDownloadFavorites}
            disabled={favorites.length === 0 || isDownloading || allTracksOffline || isOffline}
            className="flex items-center justify-center gap-2 px-4 py-2 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 disabled:hover:bg-zinc-700 rounded-full transition-colors"
            title={isOffline ? 'Cannot download while offline' : allTracksOffline ? 'All tracks downloaded' : 'Download for offline'}
          >
            {isDownloading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span className="text-sm">
                  {downloadProgress.current}/{downloadProgress.total}
                </span>
              </>
            ) : allTracksOffline ? (
              <>
                <Check className="w-4 h-4 text-green-400" />
                <span>Offline</span>
              </>
            ) : (
              <>
                <Download className="w-4 h-4" />
                <span>
                  {offlineCount > 0 ? `${offlineCount}/${favorites.length}` : 'Download'}
                </span>
              </>
            )}
          </button>

          {/* Auto-download toggle */}
          <button
            onClick={async () => {
              const newValue = !autoDownloadEnabled;
              await favoritesApi.setAutoDownload(newValue);
              queryClient.setQueryData(['favorites-auto-download'], { enabled: newValue });
            }}
            className={`flex items-center justify-center gap-2 px-4 py-2 rounded-full transition-colors ${
              autoDownloadEnabled
                ? 'bg-blue-600 hover:bg-blue-500'
                : 'bg-zinc-700 hover:bg-zinc-600'
            }`}
            title={autoDownloadEnabled ? 'Disable auto-download' : 'Auto-download new favorites'}
          >
            <RotateCw className="w-4 h-4" />
            <span className="text-sm">Auto</span>
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
        <input
          type="text"
          value={searchFilter}
          onChange={(e) => setSearchFilter(e.target.value)}
          placeholder="Search tracks..."
          className="w-full pl-9 pr-8 py-2 bg-zinc-800 rounded-lg text-sm placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-600"
        />
        {searchFilter && (
          <button
            onClick={() => setSearchFilter('')}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 text-zinc-500 hover:text-zinc-300"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Track list */}
      {filteredFavorites.length > 0 ? (
        <div className="space-y-1">
          {filteredFavorites.map((track, idx) => {
            // Convert favorite track to full Track type for context menu
            const fullTrack: Track = {
              id: track.id,
              file_path: '',
              title: track.title || null,
              artist: track.artist || null,
              album: track.album || null,
              album_artist: null,
              album_type: 'album',
              track_number: null,
              disc_number: null,
              year: null,
              genre: null,
              duration_seconds: track.duration_seconds || null,
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
                onClick={() => handlePlay(idx)}
                onContextMenu={(e) => handleContextMenu(fullTrack, e)}
                className={`group flex items-center gap-3 p-2 rounded-lg hover:bg-zinc-800/50 cursor-pointer transition-colors ${
                  currentTrack?.id === track.id ? 'bg-zinc-800/30' : ''
                }`}
              >
                {/* Track number / Play button */}
                <div className="w-8 text-center">
                  {currentTrack?.id === track.id && isPlaying ? (
                    <>
                      <div className="group-hover:hidden flex justify-center gap-0.5">
                        <div className="w-0.5 h-3 bg-pink-500 animate-pulse" />
                        <div className="w-0.5 h-3 bg-pink-500 animate-pulse [animation-delay:0.2s]" />
                        <div className="w-0.5 h-3 bg-pink-500 animate-pulse [animation-delay:0.4s]" />
                      </div>
                      <Pause
                        className="hidden group-hover:block w-4 h-4 mx-auto text-white"
                        fill="currentColor"
                      />
                    </>
                  ) : currentTrack?.id === track.id ? (
                    <>
                      <span className="group-hover:hidden text-sm text-pink-500">{idx + 1}</span>
                      <Play
                        className="hidden group-hover:block w-4 h-4 mx-auto text-white"
                        fill="currentColor"
                      />
                    </>
                  ) : (
                    <>
                      <span className="group-hover:hidden text-sm text-zinc-500">{idx + 1}</span>
                      <Play
                        className="hidden group-hover:block w-4 h-4 mx-auto text-white"
                        fill="currentColor"
                      />
                    </>
                  )}
                </div>

                {/* Track info */}
                <div className="flex-1 min-w-0">
                  <div className={`font-medium truncate ${currentTrack?.id === track.id ? 'text-pink-500' : ''}`}>
                    {track.title || 'Unknown Title'}
                  </div>
                  <div className="text-sm text-zinc-400 truncate">
                    {track.artist || 'Unknown Artist'}
                    {track.album && (
                      <span className="text-zinc-500"> • {track.album}</span>
                    )}
                  </div>
                </div>

                {/* Heart button (removes from favorites) */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    toggle(track.id);
                  }}
                  className="p-1 text-pink-500 hover:text-pink-400 transition-colors"
                  title="Remove from favorites"
                >
                  <Heart className="w-4 h-4" fill="currentColor" />
                </button>

                {/* Duration */}
                <div className="text-sm text-zinc-500">
                  {formatDuration(track.duration_seconds)}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="text-center py-12 text-zinc-500">
          <Music className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>No favorites yet</p>
          <p className="text-sm mt-1">Click the heart icon on any track to add it here</p>
        </div>
      )}

      {/* Context menu */}
      {contextMenu.isOpen && contextMenu.track && (
        <TrackContextMenu
          track={contextMenu.track}
          position={contextMenu.position}
          isSelected={false}
          onClose={closeContextMenu}
          onPlay={() => {
            const idx = filteredFavorites.findIndex(t => t.id === contextMenu.track?.id);
            if (idx !== -1) handlePlay(idx);
          }}
          onQueue={() => {
            if (contextMenu.track) {
              addToQueue(contextMenu.track);
            }
          }}
          onGoToArtist={() => {
            if (contextMenu.track?.artist) {
              navigateToArtist(contextMenu.track.artist);
            }
          }}
          onGoToAlbum={() => {
            if (contextMenu.track?.artist && contextMenu.track?.album) {
              navigateToAlbum(contextMenu.track.artist, contextMenu.track.album);
            }
          }}
          onToggleSelect={() => {
            // Not applicable in favorites
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
              useSelectionStore.getState().setEditingTrackId(contextMenu.track.id);
            }
          }}
        />
      )}
    </div>
  );
}
