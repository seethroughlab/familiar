/**
 * Context menu for AI-generated (static) playlists in the sidebar.
 */
import { useState } from 'react';
import {
  Play,
  Shuffle,
  ListPlus,
  Download,
  Copy,
  Edit3,
  Trash2,
  Loader2,
  CassetteTape,
} from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { ContextMenuContainer, MenuItem, MenuDivider, MenuHeader } from '../ui/ContextMenu';
import { playlistsApi, downloadApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import type { Playlist } from '../../api';
import { usePlayerStore } from '../../stores/playerStore';
import { showSuccess, showError } from '../../stores/toastStore';
import type { Track } from '../../types';

interface Props {
  playlist: Playlist;
  position: { x: number; y: number };
  onClose: () => void;
  onRename: () => void;
  onMakeMixTape: () => void;
}

export function PlaylistContextMenu({ playlist, position, onClose, onRename, onMakeMixTape }: Props) {
  const [downloading, setDownloading] = useState(false);
  const queryClient = useQueryClient();
  const setQueue = usePlayerStore((s) => s.setQueue);
  const addToQueue = usePlayerStore((s) => s.addToQueue);

  const handleAction = (action: () => void) => {
    action();
    onClose();
  };

  const loadTracks = async () => {
    const detail = await playlistsApi.get(playlist.id);
    return detail.tracks
      .filter((t) => t.type === 'local')
      .map((t) => ({
        id: t.id,
        title: t.title,
        artist: t.artist,
        album: t.album,
        duration_seconds: t.duration_seconds,
        format: t.format || null,
        year: t.year || null,
        genre: t.genre || null,
        track_number: t.track_number || null,
        disc_number: t.disc_number || null,
        album_artist: t.album_artist || null,
        album_type: (t.album_type || 'album') as Track['album_type'],
        analysis_version: t.analysis_version || 0,
        file_path: '',
      }));
  };

  const loadAndPlay = async (shuffled: boolean) => {
    try {
      const tracks = await loadTracks();
      if (tracks.length === 0) {
        showError('No playable tracks in playlist');
        return;
      }
      if (shuffled) {
        const shuffledTracks = [...tracks].sort(() => Math.random() - 0.5);
        setQueue(shuffledTracks, 0, { type: 'playlist', id: playlist.id });
      } else {
        setQueue(tracks, 0, { type: 'playlist', id: playlist.id });
      }
    } catch {
      showError('Failed to load playlist');
    }
  };

  const handleAddAllToQueue = async () => {
    try {
      const tracks = await loadTracks();
      if (tracks.length === 0) {
        showError('No playable tracks in playlist');
        return;
      }
      for (const track of tracks) {
        addToQueue(track);
      }
      showSuccess(`Added ${tracks.length} tracks to queue`);
    } catch {
      showError('Failed to add to queue');
    }
    onClose();
  };

  const handleDownloadZip = async () => {
    setDownloading(true);
    try {
      await downloadApi.playlist(playlist.id, playlist.name);
      showSuccess('Download started');
    } catch {
      showError('Failed to download playlist');
    } finally {
      setDownloading(false);
      onClose();
    }
  };

  const handleDuplicate = async () => {
    try {
      const dup = await playlistsApi.duplicate(playlist.id);
      queryClient.invalidateQueries({ queryKey: queryKeys.playlists.all });
      showSuccess(`Duplicated as "${dup.name}"`);
    } catch {
      showError('Failed to duplicate playlist');
    }
    onClose();
  };

  const handleDelete = async () => {
    if (!confirm(`Delete "${playlist.name}"?`)) return;
    try {
      await playlistsApi.delete(playlist.id);
      queryClient.invalidateQueries({ queryKey: queryKeys.playlists.all });
      showSuccess(`Deleted "${playlist.name}"`);
    } catch {
      showError('Failed to delete playlist');
    }
    onClose();
  };

  return (
    <ContextMenuContainer position={position} onClose={onClose}>
      <MenuHeader title={playlist.name} subtitle={`${playlist.track_count} tracks`} />

      <MenuItem
        icon={<Play className="w-4 h-4" />}
        label="Play All"
        onClick={() => handleAction(() => { loadAndPlay(false); })}
      />
      <MenuItem
        icon={<Shuffle className="w-4 h-4" />}
        label="Shuffle"
        onClick={() => handleAction(() => { loadAndPlay(true); })}
      />
      <MenuItem
        icon={<ListPlus className="w-4 h-4" />}
        label="Add All to Queue"
        onClick={handleAddAllToQueue}
      />
      <MenuItem
        icon={downloading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
        label="Download as ZIP"
        onClick={handleDownloadZip}
        disabled={downloading}
      />
      {/* Mixtapes are capped at 15 source tracks; fewer than 2 isn't a mixtape. */}
      <MenuItem
        icon={<CassetteTape className="w-4 h-4 text-orange-400" />}
        label="Make Mix Tape…"
        onClick={() => handleAction(onMakeMixTape)}
        disabled={playlist.track_count < 2 || playlist.track_count > 15}
      />

      <MenuDivider />

      <MenuItem
        icon={<Edit3 className="w-4 h-4" />}
        label="Edit Details..."
        onClick={() => handleAction(onRename)}
      />
      <MenuItem
        icon={<Copy className="w-4 h-4" />}
        label="Duplicate"
        onClick={handleDuplicate}
      />

      <MenuDivider />

      <MenuItem
        icon={<Trash2 className="w-4 h-4" />}
        label="Delete"
        onClick={handleDelete}
        iconClassName="text-red-400"
      />
    </ContextMenuContainer>
  );
}
