/**
 * Context menu for smart playlists in the sidebar.
 */
import { useState } from 'react';
import {
  Play,
  Shuffle,
  ListPlus,
  Download,
  FileDown,
  ArrowRightLeft,
  Settings2,
  Trash2,
  Loader2,
} from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { ContextMenuContainer, MenuItem, MenuDivider, MenuHeader } from '../ui/ContextMenu';
import { smartPlaylistsApi, downloadApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import type { SmartPlaylist } from '../../api';
import { usePlayerStore } from '../../stores/playerStore';
import { showSuccess, showError } from '../../stores/toastStore';
import type { FamiliarPlaylist } from '../../types';

interface Props {
  playlist: SmartPlaylist;
  position: { x: number; y: number };
  onClose: () => void;
  onEditRules: () => void;
}

export function SmartPlaylistContextMenu({ playlist, position, onClose, onEditRules }: Props) {
  const [downloading, setDownloading] = useState(false);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const setQueue = usePlayerStore((s) => s.setQueue);
  const addToQueue = usePlayerStore((s) => s.addToQueue);

  const handleAction = (action: () => void) => {
    action();
    onClose();
  };

  const loadTracks = async () => {
    const response = await smartPlaylistsApi.getTracks(playlist.id, 500);
    return response.tracks
      .filter((t) => !('source' in t && t.source))
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
        album_type: 'album' as const,
        analysis_version: 0,
        file_path: '',
      }));
  };

  const loadAndPlay = async (shuffled: boolean) => {
    try {
      const tracks = await loadTracks();
      if (tracks.length === 0) {
        showError('No playable tracks in smart playlist');
        return;
      }
      if (shuffled) {
        const shuffledTracks = [...tracks].sort(() => Math.random() - 0.5);
        setQueue(shuffledTracks, 0, { type: 'playlist', id: playlist.id });
      } else {
        setQueue(tracks, 0, { type: 'playlist', id: playlist.id });
      }
    } catch {
      showError('Failed to load smart playlist');
    }
  };

  const handleAddAllToQueue = async () => {
    try {
      const tracks = await loadTracks();
      if (tracks.length === 0) {
        showError('No playable tracks in smart playlist');
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
      await downloadApi.smartPlaylist(playlist.id, playlist.name);
      showSuccess('Download started');
    } catch {
      showError('Failed to download smart playlist');
    } finally {
      setDownloading(false);
      onClose();
    }
  };

  const handleExport = async () => {
    try {
      const response = await smartPlaylistsApi.getTracks(playlist.id, 10000);
      const familiarPlaylist: FamiliarPlaylist = {
        format: 'familiar-playlist',
        version: 1,
        exported_at: new Date().toISOString(),
        playlist: {
          name: playlist.name,
          description: playlist.description,
          type: 'smart',
          rules: playlist.rules,
          match_mode: playlist.match_mode,
          tracks: response.tracks.map((t) => ({
            title: t.title || 'Unknown',
            artist: t.artist || 'Unknown',
            album: t.album,
            duration_seconds: t.duration_seconds,
            track_number: null,
          })),
        },
      };

      const blob = new Blob([JSON.stringify(familiarPlaylist, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${playlist.name.replace(/[^a-z0-9]/gi, '_')}.familiar`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      showSuccess('Exported .familiar file');
    } catch {
      showError('Export failed');
    }
    onClose();
  };

  const handleConvertToStatic = async () => {
    try {
      const result = await smartPlaylistsApi.convertToStatic(playlist.id);
      queryClient.invalidateQueries({ queryKey: queryKeys.playlists.all });
      showSuccess(`Created static playlist "${result.name}" with ${result.track_count} tracks`);
      navigate(`/playlists/${result.playlist_id}`);
    } catch {
      showError('Failed to convert to static playlist');
    }
    onClose();
  };

  const handleDelete = async () => {
    if (!confirm(`Delete "${playlist.name}"?`)) return;
    try {
      await smartPlaylistsApi.delete(playlist.id);
      queryClient.invalidateQueries({ queryKey: queryKeys.smartPlaylists.all });
      showSuccess(`Deleted "${playlist.name}"`);
    } catch {
      showError('Failed to delete smart playlist');
    }
    onClose();
  };

  return (
    <ContextMenuContainer position={position} onClose={onClose}>
      <MenuHeader
        title={playlist.name}
        subtitle={`${playlist.cached_track_count} tracks`}
      />

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
      <MenuItem
        icon={<FileDown className="w-4 h-4" />}
        label="Export .familiar"
        onClick={handleExport}
      />

      <MenuDivider />

      <MenuItem
        icon={<ArrowRightLeft className="w-4 h-4" />}
        label="Convert to Static Playlist"
        onClick={handleConvertToStatic}
      />
      <MenuItem
        icon={<Settings2 className="w-4 h-4" />}
        label="Edit Rules..."
        onClick={onEditRules}
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
