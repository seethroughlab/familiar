import { useState, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Play, Clock, Save, Trash2, Loader2, Music, Search, X } from 'lucide-react';
import { usePlayerStore } from '../../stores/playerStore';
import { PlayIndicator } from '../common/PlayIndicator';
import { useSelectionStore } from '../../stores/selectionStore';
import { useFavorites } from '../../hooks/useFavorites';
import { useAppNavigation } from '../../hooks/useAppNavigation';
import { Heart } from 'lucide-react';
import { TrackContextMenu } from '../Library/TrackContextMenu';
import type { ContextMenuState } from '../Library/types';
import { initialContextMenuState } from '../Library/types';
import { useColumnStore, getVisibleColumns } from '../../stores/columnStore';
import { getColumnDef } from '../Library/columnDefinitions';
import { useLocalSort, useSortedTracks, buildGridColumns } from '../shared/PlaylistColumns';
import { PlaylistColumnHeader } from '../shared/PlaylistColumnHeader';
import { useEphemeralPlaylistStore, useSaveEphemeralPlaylist } from '../../stores/ephemeralPlaylistStore';
import type { EphemeralPlaylist, EphemeralTrack } from '../../stores/ephemeralPlaylistStore';
import type { Track } from '../../types';

interface Props {
  playlist?: EphemeralPlaylist;
  onBack?: () => void;
  onSave?: () => Promise<void>;
  onDelete?: () => void;
  isSaving?: boolean;
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

export function EphemeralPlaylistDetail({ playlist: playlistProp, onBack: onBackProp, onSave: onSaveProp, onDelete: onDeleteProp, isSaving: isSavingProp }: Props) {
  // Support route params
  const routeParams = useParams<{ id: string }>();
  const routeNavigate = useNavigate();
  const ephemeralPlaylists = useEphemeralPlaylistStore((s) => s.playlists);
  const removeEphemeral = useEphemeralPlaylistStore((s) => s.removePlaylist);
  const saveEphemeralPlaylist = useSaveEphemeralPlaylist();
  const [routeSaving, setRouteSaving] = useState(false);

  const playlist = playlistProp || ephemeralPlaylists.find((p) => p.id === routeParams.id);
  const onBack = onBackProp || (() => routeNavigate(-1));
  const isSaving = isSavingProp ?? routeSaving;
  const onSave = onSaveProp || (async () => {
    if (!playlist) return;
    setRouteSaving(true);
    try {
      const savedId = await saveEphemeralPlaylist(playlist.id);
      routeNavigate(`/playlists/${savedId}`, { replace: true });
    } finally {
      setRouteSaving(false);
    }
  });
  const onDelete = onDeleteProp || (() => {
    if (playlist) {
      removeEphemeral(playlist.id);
      routeNavigate(-1);
    }
  });

  if (!playlist) {
    return (
      <div className="flex items-center justify-center py-12 text-zinc-500">
        Playlist not found or has been discarded
      </div>
    );
  }
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const setQueue = usePlayerStore((s) => s.setQueue);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const addToQueue = usePlayerStore((s) => s.addToQueue);
  const { isFavorite, toggle: toggleFavorite } = useFavorites();
  const { navigateToArtist, navigateToAlbum } = useAppNavigation();
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(initialContextMenuState);
  const [searchFilter, setSearchFilter] = useState('');

  // Column + sort state
  const columns = useColumnStore((s) => s.columns);
  const { sortBy, sortOrder, toggleSort } = useLocalSort();
  const visibleColumnIds = useMemo(() => getVisibleColumns(columns), [columns]);
  const gridColumns = useMemo(
    () => buildGridColumns(columns, ['3rem', '4.5rem']),
    [columns],
  );

  const searchedTracks = useMemo(() => {
    if (!searchFilter) return playlist.tracks;
    const q = searchFilter.toLowerCase();
    return playlist.tracks.filter(t =>
      (t.title?.toLowerCase().includes(q)) ||
      (t.artist?.toLowerCase().includes(q)) ||
      (t.album?.toLowerCase().includes(q))
    );
  }, [playlist.tracks, searchFilter]);

  const filteredTracks = useSortedTracks(searchedTracks, sortBy, sortOrder, toFullTrack);

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
        <div>
          <PlaylistColumnHeader
            columns={columns}
            gridColumns={gridColumns}
            sortBy={sortBy}
            sortOrder={sortOrder}
            toggleSort={toggleSort}
          />
          <div className="space-y-1">
            {filteredTracks.map((track, idx) => {
              const fullTrack = toFullTrack(track);
              return (
                <div key={track.id}>
                  {/* Mobile layout */}
                  <div
                    onClick={() => handlePlay(idx)}
                    onContextMenu={(e) => handleContextMenu(fullTrack, e)}
                    className={`sm:hidden flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-zinc-800/50 cursor-pointer transition-colors ${
                      currentTrack?.id === track.id ? 'bg-zinc-800/30' : ''
                    }`}
                  >
                    <div className="w-8 flex-shrink-0 text-center" onClick={(e) => { e.stopPropagation(); handlePlay(idx); }}>
                      <PlayIndicator isCurrent={currentTrack?.id === track.id} isPlaying={isPlaying} index={idx + 1} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className={`font-medium truncate ${currentTrack?.id === track.id ? 'text-green-500' : ''}`}>
                        {track.title || 'Unknown Title'}
                      </div>
                      <div className="text-sm text-zinc-400 truncate">
                        {track.artist || 'Unknown Artist'}
                        {track.album && <span className="text-zinc-500"> • {track.album}</span>}
                      </div>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleFavorite(track.id);
                      }}
                      className={`flex-shrink-0 p-1 transition-colors ${
                        isFavorite(track.id)
                          ? 'text-pink-500 hover:text-pink-400'
                          : 'text-zinc-500 hover:text-pink-400'
                      }`}
                    >
                      <Heart className="w-4 h-4" fill={isFavorite(track.id) ? 'currentColor' : 'none'} />
                    </button>
                    <div className="flex-shrink-0 text-sm text-zinc-500">
                      {formatDuration(track.duration_seconds)}
                    </div>
                  </div>
                  {/* Desktop layout */}
                  <div
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData('application/track-id', track.id);
                      e.dataTransfer.effectAllowed = 'copy';
                    }}
                    onClick={() => handlePlay(idx)}
                    onContextMenu={(e) => handleContextMenu(fullTrack, e)}
                    className={`hidden sm:grid group gap-4 px-4 py-2 items-center rounded-lg hover:bg-zinc-800/50 cursor-pointer transition-all ${
                      currentTrack?.id === track.id ? 'bg-zinc-800/30' : ''
                    }`}
                    style={{ gridTemplateColumns: gridColumns }}
                  >
                  {/* Track number / Play button */}
                  <div className="text-center cursor-pointer" onClick={(e) => { e.stopPropagation(); handlePlay(idx); }}>
                    <PlayIndicator isCurrent={currentTrack?.id === track.id} isPlaying={isPlaying} index={idx + 1} />
                  </div>

                  {/* Title + artist (mobile: shows artist/album inline) */}
                  <div className="min-w-0">
                    <div className={`font-medium truncate ${currentTrack?.id === track.id ? 'text-green-500' : ''}`}>
                      {track.title || 'Unknown Title'}
                    </div>
                    <div className="text-sm text-zinc-400 truncate sm:hidden">
                      {track.artist || 'Unknown Artist'}
                      {track.album && <span className="text-zinc-500"> • {track.album}</span>}
                    </div>
                  </div>

                  {/* Dynamic columns (hidden on mobile) */}
                  {visibleColumnIds.map((colId) => {
                    const colDef = getColumnDef(colId);
                    if (!colDef) return <div key={colId} />;
                    const raw = colDef.getValue(fullTrack);
                    const display = colDef.format ? colDef.format(raw) : (raw ?? '-');
                    return (
                      <div
                        key={colId}
                        className={`hidden sm:block text-sm text-zinc-400 truncate ${
                          colDef.align === 'right' ? 'text-right' : colDef.align === 'center' ? 'text-center' : ''
                        }`}
                      >
                        {String(display)}
                      </div>
                    );
                  })}

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
                  <div className="text-sm text-zinc-500 text-right">
                    {formatDuration(track.duration_seconds)}
                  </div>
                  </div>
                </div>
              );
            })}
          </div>
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
