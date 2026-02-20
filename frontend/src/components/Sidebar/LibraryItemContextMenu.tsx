/**
 * Context menu for library navigation items in the sidebar.
 * Switches behavior based on the item's path.
 */
import {
  Play,
  Shuffle,
  Disc,
  ExternalLink,
  CheckCheck,
  XCircle,
} from 'lucide-react';
import { ContextMenuContainer, MenuItem, MenuHeader } from '../ui/ContextMenu';
import { usePlayerStore } from '../../stores/playerStore';
import { tracksApi } from '../../api';
import { showSuccess, showError } from '../../stores/toastStore';

interface Props {
  path: string;
  position: { x: number; y: number };
  onClose: () => void;
}

const LABELS: Record<string, string> = {
  '/library/tracks': 'Tracks',
  '/library/artists': 'Artists',
  '/library/albums': 'Albums',
  '/library/mood-grid': 'Mood Grid',
  '/library/music-map': 'Music Map',
  '/library/explorer': '3D Explorer',
  '/library/discover': 'Discover',
  '/library/proposed-changes': 'Changes',
};

export function LibraryItemContextMenu({ path, position, onClose }: Props) {
  const setLazyQueue = usePlayerStore((s) => s.setLazyQueue);

  const handleAction = (action: () => void) => {
    action();
    onClose();
  };

  const label = LABELS[path] || 'Library';

  // Tracks, Artists, Albums — Play All / Shuffle All
  if (path === '/library/tracks' || path === '/library/artists' || path === '/library/albums') {
    const playAll = async (shuffled: boolean) => {
      try {
        const response = await tracksApi.getIds({ shuffle: shuffled });
        if (response.ids.length === 0) {
          showError('No tracks in library');
          return;
        }
        await setLazyQueue(response.ids, { type: 'library' });
      } catch {
        showError('Failed to load tracks');
      }
    };

    const playRandomAlbum = async () => {
      try {
        const response = await tracksApi.getIds({ shuffle: true });
        if (response.ids.length === 0) {
          showError('No tracks in library');
          return;
        }
        // Get a random track to find its album
        const randomTrack = await tracksApi.get(response.ids[0]);
        if (randomTrack.album) {
          const albumTracks = await tracksApi.getIds({
            album: randomTrack.album,
            sort_by: 'track_number',
            sort_order: 'asc',
          });
          if (albumTracks.ids.length > 0) {
            await setLazyQueue(albumTracks.ids, { type: 'album', id: randomTrack.album });
            showSuccess(`Playing: ${randomTrack.album}`);
            return;
          }
        }
        // Fallback: just play the random track
        await setLazyQueue([response.ids[0]], { type: 'library' });
      } catch {
        showError('Failed to play random album');
      }
    };

    return (
      <ContextMenuContainer position={position} onClose={onClose}>
        <MenuHeader title={label} />

        <MenuItem
          icon={<Play className="w-4 h-4" />}
          label="Play All"
          onClick={() => handleAction(() => { playAll(false); })}
        />
        <MenuItem
          icon={<Shuffle className="w-4 h-4" />}
          label="Shuffle All"
          onClick={() => handleAction(() => { playAll(true); })}
        />
        {path === '/library/albums' && (
          <MenuItem
            icon={<Disc className="w-4 h-4" />}
            label="Play Random Album"
            onClick={() => handleAction(() => { playRandomAlbum(); })}
          />
        )}
      </ContextMenuContainer>
    );
  }

  // Mood Grid, Music Map, 3D Explorer, Discover — Open in New Tab
  if (['/library/mood-grid', '/library/music-map', '/library/explorer', '/library/discover'].includes(path)) {
    return (
      <ContextMenuContainer position={position} onClose={onClose}>
        <MenuHeader title={label} />

        <MenuItem
          icon={<ExternalLink className="w-4 h-4" />}
          label="Open in New Tab"
          onClick={() => {
            window.open(path, '_blank');
            onClose();
          }}
        />
      </ContextMenuContainer>
    );
  }

  // Proposed Changes
  if (path === '/library/proposed-changes') {
    return (
      <ContextMenuContainer position={position} onClose={onClose}>
        <MenuHeader title="Changes" />

        <MenuItem
          icon={<CheckCheck className="w-4 h-4" />}
          label="Apply All Pending"
          onClick={() => {
            // Navigate to the page - the apply-all action is there
            window.location.href = path;
            onClose();
          }}
        />
        <MenuItem
          icon={<XCircle className="w-4 h-4" />}
          label="Dismiss All"
          onClick={() => {
            window.location.href = path;
            onClose();
          }}
        />
      </ContextMenuContainer>
    );
  }

  // Fallback
  return null;
}
