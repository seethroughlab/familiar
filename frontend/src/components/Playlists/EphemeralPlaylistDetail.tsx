import { useState, useCallback, useMemo } from 'react';
import { ArrowLeft, Play, Pause, Clock, Save, Trash2, Loader2, Music, Search, X } from 'lucide-react';
import { usePlayerStore } from '../../stores/playerStore';
import { useSelectionStore } from '../../stores/selectionStore';
import { useFavorites } from '../../hooks/useFavorites';
import { useAppNavigation } from '../../hooks/useAppNavigation';
import { Heart } from 'lucide-react';
import { TrackContextMenu } from '../Library/TrackContextMenu';
import type { ContextMenuState } from '../Library/types';
import { initialContextMenuState } from '../Library/types';
import type { EphemeralPlaylist, EphemeralTrack } from '../../stores/ephemeralPlaylistStore';
import type { Track } from '../../types';

interface Props {
  playlist: EphemeralPlaylist;
  onBack: () => void;
  onSave: () => Promise<void>;
  onDelete: () => void;
  isSaving: boolean;
}

function toFullTrack(t: EphemeralTrack): Track {
  return {
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
  };
}

export function EphemeralPlaylistDetail({ playlist, onBack, onSave, onDelete, isSaving }: Props) {
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const setQueue = usePlayerStore((s) => s.setQueue);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const addToQueue = usePlayerStore((s) => s.addToQueue);
  const { isFavorite, toggle: toggleFavorite } = useFavorites();
  const { navigateToArtist, navigateToAlbum } = useAppNavigation();
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(initialContextMenuState);
  const [searchFilter, setSearchFilter] = useState('');

  const filteredTracks = useMemo(() => {
    if (!searchFilter) return playlist.tracks;
    const q = searchFilter.toLowerCase();
    return playlist.tracks.filter(t =>
      (t.title?.toLowerCase().includes(q)) ||
      (t.artist?.toLowerCase().includes(q)) ||
      (t.album?.toLowerCase().includes(q))
    );
  }, [playlist.tracks, searchFilter]);

  const handlePlay = useCallback((startIndex = 0) => {
    if (filteredTracks.length === 0) return;

    // If clicking on the currently playing track, toggle play/pause
    const clickedTrack = filteredTracks[startIndex];
    if (clickedTrack && currentTrack?.id === clickedTrack.id) {
      setIsPlaying(!isPlaying);
      return;
    }

    const queueTracks = filteredTracks.map(toFullTrack);
    setQueue(queueTracks, startIndex, { type: 'ephemeral', id: playlist.id });
  }, [filteredTracks, playlist.id, currentTrack?.id, isPlaying, setIsPlaying, setQueue]);

  // Context menu handlers
  const handleContextMenu = useCallback((track: Track, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ isOpen: true, track, position: { x: e.clientX, y: e.clientY } });
  }, []);

  const closeContextMenu = useCallback(() => {
    setContextMenu(initialContextMenuState);
  }, []);

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const totalDuration = playlist.tracks.reduce(
    (sum, t) => sum + (t.duration_seconds || 0),
    0
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="space-y-4">
        {/* Back button row */}
        <button
          onClick={onBack}
          className="p-2 hover:bg-zinc-800 rounded-lg transition-colors -ml-2"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>

        {/* Playlist info */}
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 text-xs bg-amber-500/20 text-amber-400 rounded-full border border-dashed border-amber-500/50">
              Unsaved
            </span>
            <h2 className="text-xl font-bold truncate">{playlist.name}</h2>
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 text-sm text-zinc-500">
            <span>{playlist.tracks.length} tracks</span>
            <span className="flex items-center gap-1">
              <Clock className="w-4 h-4" />
              {Math.floor(totalDuration / 60)} min
            </span>
            {playlist.generationPrompt && (
              <span className="text-amber-400/70 truncate max-w-full sm:max-w-xs">
                "{playlist.generationPrompt}"
              </span>
            )}
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
          <button
            onClick={() => handlePlay()}
            disabled={playlist.tracks.length === 0}
            className="flex items-center justify-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 disabled:hover:bg-green-600 rounded-full transition-colors"
          >
            <Play className="w-4 h-4" fill="currentColor" />
            Play
          </button>

          <button
            onClick={onSave}
            disabled={isSaving}
            className="flex items-center justify-center gap-2 px-4 py-2 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 rounded-full transition-colors"
          >
            {isSaving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            Save Playlist
          </button>

          <button
            onClick={onDelete}
            disabled={isSaving}
            className="flex items-center justify-center gap-2 px-4 py-2 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 rounded-full transition-colors text-red-400"
          >
            <Trash2 className="w-4 h-4" />
            Discard
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
      {filteredTracks.length > 0 ? (
        <div className="space-y-1">
          {filteredTracks.map((track, idx) => (
            <div
              key={track.id}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData('application/track-id', track.id);
                e.dataTransfer.effectAllowed = 'copy';
              }}
              onClick={() => handlePlay(idx)}
              onContextMenu={(e) => handleContextMenu(toFullTrack(track), e)}
              className={`group flex items-center gap-3 p-2 rounded-lg hover:bg-zinc-800/50 cursor-pointer transition-all ${
                currentTrack?.id === track.id ? 'bg-zinc-800/30' : ''
              }`}
            >
              {/* Track number / Play button */}
              <div className="w-8 text-center">
                {currentTrack?.id === track.id && isPlaying ? (
                  <>
                    <div className="group-hover:hidden flex justify-center gap-0.5">
                      <div className="w-0.5 h-3 bg-green-500 animate-pulse" />
                      <div className="w-0.5 h-3 bg-green-500 animate-pulse [animation-delay:0.2s]" />
                      <div className="w-0.5 h-3 bg-green-500 animate-pulse [animation-delay:0.4s]" />
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); handlePlay(idx); }}
                      className="hidden group-hover:block"
                    >
                      <Pause className="w-4 h-4 mx-auto text-white" fill="currentColor" />
                    </button>
                  </>
                ) : currentTrack?.id === track.id ? (
                  <>
                    <span className="group-hover:hidden text-sm text-green-500">{idx + 1}</span>
                    <button
                      onClick={(e) => { e.stopPropagation(); handlePlay(idx); }}
                      className="hidden group-hover:block"
                    >
                      <Play className="w-4 h-4 mx-auto text-white" fill="currentColor" />
                    </button>
                  </>
                ) : (
                  <>
                    <span className="group-hover:hidden text-sm text-zinc-500">{idx + 1}</span>
                    <button
                      onClick={(e) => { e.stopPropagation(); handlePlay(idx); }}
                      className="hidden group-hover:block"
                    >
                      <Play className="w-4 h-4 mx-auto text-white" fill="currentColor" />
                    </button>
                  </>
                )}
              </div>

              {/* Track info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`font-medium truncate ${currentTrack?.id === track.id ? 'text-green-500' : ''}`}>
                    {track.title || 'Unknown Title'}
                  </span>
                </div>
                <div className="text-sm text-zinc-400 truncate">
                  {track.artist || 'Unknown Artist'}
                  {track.album && (
                    <span className="text-zinc-500"> • {track.album}</span>
                  )}
                </div>
              </div>

              {/* Favorite button */}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  toggleFavorite(track.id);
                }}
                className={`p-1 transition-colors ${
                  isFavorite(track.id)
                    ? 'text-pink-500 hover:text-pink-400'
                    : 'text-zinc-500 hover:text-pink-400 opacity-100 sm:opacity-0 sm:group-hover:opacity-100'
                }`}
                title={isFavorite(track.id) ? 'Remove from favorites' : 'Add to favorites'}
              >
                <Heart className="w-4 h-4" fill={isFavorite(track.id) ? 'currentColor' : 'none'} />
              </button>

              {/* Duration */}
              <div className="text-sm text-zinc-500">
                {formatDuration(track.duration_seconds)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-12 text-zinc-500">
          <Music className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>No tracks in this playlist</p>
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
            const idx = filteredTracks.findIndex(t => t.id === contextMenu.track?.id);
            if (idx !== -1) handlePlay(idx);
          }}
          onQueue={() => {
            if (contextMenu.track) addToQueue(contextMenu.track);
          }}
          onGoToArtist={() => {
            if (contextMenu.track?.artist) navigateToArtist(contextMenu.track.artist);
          }}
          onGoToAlbum={() => {
            if (contextMenu.track?.artist && contextMenu.track?.album) {
              navigateToAlbum(contextMenu.track.artist, contextMenu.track.album);
            }
          }}
          onToggleSelect={() => {}}
          onAddToPlaylist={() => {}}
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
          isFavorite={contextMenu.track ? isFavorite(contextMenu.track.id) : false}
          onToggleFavorite={() => {
            if (contextMenu.track) toggleFavorite(contextMenu.track.id);
          }}
        />
      )}
    </div>
  );
}
