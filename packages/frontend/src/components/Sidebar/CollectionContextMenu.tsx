/**
 * Context menu for collection items in the sidebar (Favorites, Downloads, Wishlist).
 */
import {
  Play,
  Shuffle,
  Download,
  ListPlus,
  Trash2,
  HardDrive,
  RefreshCw,
} from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { ContextMenuContainer, MenuItem, MenuDivider, MenuHeader } from '../ui/ContextMenu';
import { usePlayerStore } from '../../stores/playerStore';
import { useFavorites } from '../../hooks/useFavorites';
import { useDownloadedTracks } from '../../hooks/useDownloadedTracks';
import { downloadApi, favoritesApi, playlistsApi, newReleasesApi } from '../../api';
import { clearAllOfflineTracks } from '../../services/offlineService';
import { showSuccess, showError, showInfo } from '../../stores/toastStore';
import type { Track } from '../../types';

interface Props {
  collectionPath: string;
  position: { x: number; y: number };
  onClose: () => void;
}

export function CollectionContextMenu({ collectionPath, position, onClose }: Props) {
  const queryClient = useQueryClient();
  const setQueue = usePlayerStore((s) => s.setQueue);
  const { favorites, total: favoritesTotal } = useFavorites();
  const { tracks: downloadedTracks, total: downloadsTotal, totalSizeFormatted, refresh: refreshDownloads } = useDownloadedTracks();

  const handleAction = (action: () => void) => {
    action();
    onClose();
  };

  // New Releases
  if (collectionPath === '/new-releases') {
    const handleCheck = async () => {
      try {
        await newReleasesApi.check({ days_back: 90 });
        queryClient.invalidateQueries({ queryKey: ['new-releases-status'] });
        showSuccess('Checking for new releases...');
      } catch {
        showError('Failed to start check');
      }
      onClose();
    };

    return (
      <ContextMenuContainer position={position} onClose={onClose}>
        <MenuHeader title="New Releases" />

        <MenuItem
          icon={<RefreshCw className="w-4 h-4" />}
          label="Check for New Releases"
          onClick={handleCheck}
        />
      </ContextMenuContainer>
    );
  }

  // Favorites
  if (collectionPath === '/favorites') {
    const playFavorites = (shuffled: boolean) => {
      // FavoriteTrack already has all Track fields
      const tracks: Track[] = favorites.map((f) => ({
        id: f.id,
        title: f.title,
        artist: f.artist,
        album: f.album,
        duration_seconds: f.duration_seconds,
        format: f.format,
        year: f.year,
        genre: f.genre,
        track_number: f.track_number,
        disc_number: f.disc_number,
        album_artist: f.album_artist,
        album_type: f.album_type as Track['album_type'],
        analysis_version: f.analysis_version,
        file_path: f.file_path,
      }));

      if (tracks.length === 0) {
        showError('No favorites to play');
        return;
      }

      if (shuffled) {
        const s = [...tracks].sort(() => Math.random() - 0.5);
        setQueue(s, 0, { type: 'other' });
      } else {
        setQueue(tracks, 0, { type: 'other' });
      }
    };

    const handleDownloadZip = async () => {
      const trackIds = favorites.map((f) => f.id);
      if (trackIds.length === 0) {
        showError('No favorites to download');
        return;
      }
      try {
        await downloadApi.tracks(trackIds, 'Favorites');
        showSuccess('Download started');
      } catch {
        showError('Failed to download favorites');
      }
      onClose();
    };

    const handleCreatePlaylist = async () => {
      const trackIds = favorites.map((f) => f.id);
      if (trackIds.length === 0) {
        showError('No favorites to create playlist from');
        return;
      }
      try {
        await playlistsApi.create({
          name: 'My Favorites',
          description: `Playlist from ${trackIds.length} favorites`,
          track_ids: trackIds,
        });
        queryClient.invalidateQueries({ queryKey: ['playlists'] });
        showSuccess('Created playlist from favorites');
      } catch {
        showError('Failed to create playlist');
      }
      onClose();
    };

    const handleClearAll = async () => {
      if (!confirm(`Remove all ${favoritesTotal} favorites?`)) return;
      try {
        for (const f of favorites) {
          await favoritesApi.remove(f.id);
        }
        queryClient.invalidateQueries({ queryKey: ['favorites'] });
        showSuccess('Cleared all favorites');
      } catch {
        showError('Failed to clear favorites');
      }
      onClose();
    };

    return (
      <ContextMenuContainer position={position} onClose={onClose}>
        <MenuHeader title="Favorites" subtitle={`${favoritesTotal} tracks`} />

        <MenuItem
          icon={<Play className="w-4 h-4" />}
          label="Play All"
          onClick={() => handleAction(() => playFavorites(false))}
          disabled={favoritesTotal === 0}
        />
        <MenuItem
          icon={<Shuffle className="w-4 h-4" />}
          label="Shuffle"
          onClick={() => handleAction(() => playFavorites(true))}
          disabled={favoritesTotal === 0}
        />
        <MenuItem
          icon={<Download className="w-4 h-4" />}
          label="Download as ZIP"
          onClick={handleDownloadZip}
          disabled={favoritesTotal === 0}
        />
        <MenuItem
          icon={<ListPlus className="w-4 h-4" />}
          label="Create Playlist from Favorites"
          onClick={handleCreatePlaylist}
          disabled={favoritesTotal === 0}
        />

        <MenuDivider />

        <MenuItem
          icon={<Trash2 className="w-4 h-4" />}
          label="Clear All Favorites"
          onClick={handleClearAll}
          disabled={favoritesTotal === 0}
          iconClassName="text-red-400"
        />
      </ContextMenuContainer>
    );
  }

  // Downloads
  if (collectionPath === '/downloads') {
    const playDownloads = (shuffled: boolean) => {
      // OfflineTrackInfo has id, title, artist, album but not full Track fields
      // Use tracksApi.getBatch for proper playback, but for quick play cast minimally
      const tracks: Track[] = downloadedTracks.map((t) => ({
        id: t.id,
        title: t.title || 'Unknown',
        artist: t.artist || 'Unknown',
        album: t.album || null,
        duration_seconds: null,
        format: null,
        year: null,
        genre: null,
        track_number: null,
        disc_number: null,
        album_artist: null,
        album_type: 'album' as const,
        analysis_version: 0,
        file_path: '',
      }));

      if (tracks.length === 0) {
        showError('No downloaded tracks to play');
        return;
      }

      if (shuffled) {
        const s = [...tracks].sort(() => Math.random() - 0.5);
        setQueue(s, 0, { type: 'other' });
      } else {
        setQueue(tracks, 0, { type: 'other' });
      }
    };

    const handleClearAll = async () => {
      if (!confirm(`Remove all ${downloadsTotal} downloaded tracks? This will free ${totalSizeFormatted}.`)) return;
      try {
        await clearAllOfflineTracks();
        await refreshDownloads();
        showSuccess(`Cleared all downloads (${totalSizeFormatted} freed)`);
      } catch {
        showError('Failed to clear downloads');
      }
      onClose();
    };

    const handleStorageInfo = () => {
      showInfo(`${downloadsTotal} tracks \u00b7 ${totalSizeFormatted}`);
      onClose();
    };

    return (
      <ContextMenuContainer position={position} onClose={onClose}>
        <MenuHeader title="Downloads" subtitle={`${downloadsTotal} tracks \u00b7 ${totalSizeFormatted}`} />

        <MenuItem
          icon={<Play className="w-4 h-4" />}
          label="Play All"
          onClick={() => handleAction(() => playDownloads(false))}
          disabled={downloadsTotal === 0}
        />
        <MenuItem
          icon={<Shuffle className="w-4 h-4" />}
          label="Shuffle"
          onClick={() => handleAction(() => playDownloads(true))}
          disabled={downloadsTotal === 0}
        />

        <MenuDivider />

        <MenuItem
          icon={<Trash2 className="w-4 h-4" />}
          label="Clear All Downloads"
          onClick={handleClearAll}
          disabled={downloadsTotal === 0}
          iconClassName="text-red-400"
        />
        <MenuItem
          icon={<HardDrive className="w-4 h-4" />}
          label="Storage Info"
          onClick={handleStorageInfo}
        />
      </ContextMenuContainer>
    );
  }

  // Wishlist
  if (collectionPath === '/wishlist') {
    return (
      <ContextMenuContainer position={position} onClose={onClose}>
        <MenuHeader title="Wishlist" />

        <MenuItem
          icon={<Play className="w-4 h-4" />}
          label="Play All"
          onClick={() => { onClose(); }}
          disabled
        />
        <MenuItem
          icon={<Shuffle className="w-4 h-4" />}
          label="Shuffle"
          onClick={() => { onClose(); }}
          disabled
        />

        <MenuDivider />

        <MenuItem
          icon={<Trash2 className="w-4 h-4" />}
          label="Clear Wishlist"
          onClick={async () => {
            if (!confirm('Clear all wishlist items?')) return;
            try {
              const wl = await playlistsApi.getWishlist();
              for (const t of wl.tracks) {
                await playlistsApi.removeItem(wl.id, t.playlist_track_id);
              }
              queryClient.invalidateQueries({ queryKey: ['wishlist'] });
              showSuccess('Wishlist cleared');
            } catch {
              showError('Failed to clear wishlist');
            }
            onClose();
          }}
          iconClassName="text-red-400"
        />
      </ContextMenuContainer>
    );
  }

  return null;
}
