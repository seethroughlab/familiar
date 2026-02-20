/**
 * Context menu for unsaved (ephemeral) playlists in the sidebar.
 */
import {
  Play,
  Shuffle,
  Save,
  Trash2,
} from 'lucide-react';
import { ContextMenuContainer, MenuItem, MenuDivider, MenuHeader } from '../ui/ContextMenu';
import { useEphemeralPlaylistStore, useSaveEphemeralPlaylist } from '../../stores/ephemeralPlaylistStore';
import { usePlayerStore } from '../../stores/playerStore';
import { tracksApi } from '../../api/client';
import { showSuccess, showError } from '../../stores/toastStore';
import { useNavigate } from 'react-router-dom';

interface Props {
  playlistId: string;
  position: { x: number; y: number };
  onClose: () => void;
}

export function EphemeralPlaylistContextMenu({ playlistId, position, onClose }: Props) {
  const playlist = useEphemeralPlaylistStore((s) => s.getPlaylist(playlistId));
  const removePlaylist = useEphemeralPlaylistStore((s) => s.removePlaylist);
  const saveEphemeral = useSaveEphemeralPlaylist();
  const setQueue = usePlayerStore((s) => s.setQueue);
  const navigate = useNavigate();

  if (!playlist) return null;

  const handleAction = (action: () => void) => {
    action();
    onClose();
  };

  const loadAndPlay = async (shuffled: boolean) => {
    try {
      const tracks = await tracksApi.getBatch(playlist.trackIds);

      if (tracks.length === 0) {
        showError('No playable tracks');
        return;
      }

      if (shuffled) {
        const shuffledTracks = [...tracks].sort(() => Math.random() - 0.5);
        setQueue(shuffledTracks, 0, { type: 'ephemeral', id: playlist.id });
      } else {
        setQueue(tracks, 0, { type: 'ephemeral', id: playlist.id });
      }
    } catch {
      showError('Failed to load tracks');
    }
  };

  const handleSave = async () => {
    try {
      const savedId = await saveEphemeral(playlistId);
      showSuccess(`Saved "${playlist.name}"`);
      navigate(`/playlists/${savedId}`);
    } catch {
      showError('Failed to save playlist');
    }
    onClose();
  };

  const handleDiscard = () => {
    removePlaylist(playlistId);
    showSuccess('Playlist discarded');
    onClose();
  };

  return (
    <ContextMenuContainer position={position} onClose={onClose}>
      <MenuHeader
        title={playlist.name}
        subtitle={`${playlist.tracks.length} tracks \u00b7 Unsaved`}
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

      <MenuDivider />

      <MenuItem
        icon={<Save className="w-4 h-4" />}
        label="Save to Library"
        onClick={handleSave}
      />
      <MenuItem
        icon={<Trash2 className="w-4 h-4" />}
        label="Discard"
        onClick={handleDiscard}
        iconClassName="text-red-400"
      />
    </ContextMenuContainer>
  );
}
