import { useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Play, Clock, Save, Trash2, Loader2 } from 'lucide-react';
import { TrackSearchInput } from '../shared/TrackSearchInput';
import { usePlayerStore } from '../../stores/playerStore';
import { useEphemeralPlaylistStore, useSaveEphemeralPlaylist } from '../../stores/ephemeralPlaylistStore';
import type { EphemeralPlaylist, EphemeralTrack } from '../../stores/ephemeralPlaylistStore';
import type { Track } from '../../types';
import { useTrackSearch } from '../../hooks/useTrackSearch';
import { PlaylistTrackList } from '../shared/PlaylistTrackList';

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

  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const setQueueByTrackId = usePlayerStore((s) => s.setQueueByTrackId);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);

  const playlistTracks = playlist?.tracks ?? [];
  const { searchFilter, setSearchFilter, filteredTracks: searchedTracks } = useTrackSearch(playlistTracks);

  const handlePlay = useCallback((startIndex = 0, sortedItems?: EphemeralTrack[]) => {
    const items = sortedItems ?? searchedTracks;
    if (items.length === 0 || !playlist) return;

    // If clicking on the currently playing track, toggle play/pause
    const clickedTrack = items[startIndex];
    if (!clickedTrack) return;
    if (currentTrack?.id === clickedTrack.id) {
      setIsPlaying(!isPlaying);
      return;
    }

    const queueTracks = items.map(toFullTrack);
    setQueueByTrackId(queueTracks, clickedTrack.id, { type: 'ephemeral', id: playlist.id });
  }, [searchedTracks, playlist, currentTrack?.id, isPlaying, setIsPlaying, setQueueByTrackId]);

  if (!playlist) {
    return (
      <div className="flex items-center justify-center py-12 text-zinc-500">
        Playlist not found or has been discarded
      </div>
    );
  }

  const totalDuration = playlist.tracks.reduce(
    (sum, t) => sum + (t.duration_seconds || 0),
    0
  );

  return (
    <div className="flex flex-col gap-4 p-4 min-h-full">
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
      <TrackSearchInput value={searchFilter} onChange={setSearchFilter} />

      {/* Track list */}
      <PlaylistTrackList
        items={searchedTracks}
        getTrack={toFullTrack}
        onPlay={handlePlay}
        emptyMessage="No tracks in this playlist"
        sortPersistKey="ephemeral"
      />
    </div>
  );
}
