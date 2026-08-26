/**
 * Context menu for album actions.
 *
 * Shows on right-click with options like Play, Shuffle, Queue, Go to Artist, etc.
 */
import {
  Play,
  Shuffle,
  ListPlus,
  User,
  Disc,
  Download,
  Trash2,
  Sparkles,
} from 'lucide-react';
import { ContextMenuContainer, MenuItem, MenuDivider, MenuHeader } from '../ui/ContextMenu';

interface AlbumContextMenuProps {
  album: { name: string; artist: string; year: number | null; first_track_id: string };
  position: { x: number; y: number };
  onClose: () => void;
  onPlay: () => void;
  onShuffle: () => void;
  onQueue: () => void;
  onGoToArtist: () => void;
  onGoToAlbum: () => void;
  onDownload: () => void;
  onRemoveDownload: () => void;
  hasDownloadedTracks: boolean;
  onAddToPlaylist: () => void;
  onMakePlaylist: () => void;
}

export function AlbumContextMenu({
  album,
  position,
  onClose,
  onPlay,
  onShuffle,
  onQueue,
  onGoToArtist,
  onGoToAlbum,
  onDownload,
  onRemoveDownload,
  hasDownloadedTracks,
  onAddToPlaylist,
  onMakePlaylist,
}: AlbumContextMenuProps) {
  const handleAction = (action: () => void) => {
    action();
    onClose();
  };

  return (
    <ContextMenuContainer position={position} onClose={onClose}>
      {/* Album info header */}
      <MenuHeader
        title={album.name}
        subtitle={`${album.artist}${album.year ? ` \u00b7 ${album.year}` : ''}`}
      />

      {/* Playback actions */}
      <MenuItem
        icon={<Play className="w-4 h-4" />}
        label="Play Album"
        onClick={() => handleAction(onPlay)}
      />
      <MenuItem
        icon={<Shuffle className="w-4 h-4" />}
        label="Shuffle Album"
        onClick={() => handleAction(onShuffle)}
      />
      <MenuItem
        icon={<ListPlus className="w-4 h-4" />}
        label="Add to Queue"
        onClick={() => handleAction(onQueue)}
      />

      <MenuDivider />

      {/* Navigation actions */}
      <MenuItem
        icon={<User className="w-4 h-4" />}
        label="Go to Artist"
        onClick={() => handleAction(onGoToArtist)}
      />
      <MenuItem
        icon={<Disc className="w-4 h-4" />}
        label="Go to Album"
        onClick={() => handleAction(onGoToAlbum)}
      />

      <MenuDivider />

      {/* Downloads */}
      <MenuItem
        icon={<Download className="w-4 h-4" />}
        label="Download Album"
        onClick={() => handleAction(onDownload)}
      />
      {hasDownloadedTracks && (
        <MenuItem
          icon={<Trash2 className="w-4 h-4" />}
          label="Remove Downloaded"
          onClick={() => handleAction(onRemoveDownload)}
        />
      )}

      {/* Playlist */}
      <MenuItem
        icon={<ListPlus className="w-4 h-4" />}
        label="Add to Playlist..."
        onClick={() => handleAction(onAddToPlaylist)}
      />

      <MenuDivider />

      {/* AI Actions. Absent without a provider: this item only ever opens the chat panel. */}
      {/* Not gated on chat since ADR-0048 — see TrackContextMenu. */}
      <MenuItem
        icon={<Sparkles className="w-4 h-4" />}
        label="Make Playlist From This..."
        onClick={() => handleAction(onMakePlaylist)}
      />
    </ContextMenuContainer>
  );
}
