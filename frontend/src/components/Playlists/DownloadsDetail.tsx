import { useState, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Play, Trash2, HardDrive, X, Search } from 'lucide-react';
import { usePlayerStore } from '../../stores/playerStore';
import { useDownloadedTracks } from '../../hooks/useDownloadedTracks';
import { removeOfflineTrack, clearAllOfflineTracks } from '../../services/offlineService';
import type { Track } from '../../types';
import { showError, showSuccess } from '../../stores/toastStore';
import { PlaylistTrackList, type TrackRowContext } from '../shared/PlaylistTrackList';

import { createLogger } from '../../utils/logger';

const log = createLogger('DownloadsDetail');

interface Props {
  onBack?: () => void;
}

type DownloadedTrack = ReturnType<typeof useDownloadedTracks>['tracks'][number];

export function DownloadsDetail({ onBack: onBackProp }: Props) {
  const routeNavigate = useNavigate();
  const onBack = onBackProp || (() => routeNavigate(-1));
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const setQueue = usePlayerStore((s) => s.setQueue);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const { tracks, total, totalSizeFormatted, refresh } = useDownloadedTracks();

  const [searchFilter, setSearchFilter] = useState('');

  const getTrackFromDownload = useCallback(
    (t: DownloadedTrack): Track => ({
      id: t.id,
      file_path: '',
      title: t.title || null,
      artist: t.artist || null,
      album: t.album || null,
      album_artist: null,
      album_type: 'album' as const,
      track_number: null,
      disc_number: null,
      year: null,
      genre: null,
      duration_seconds: null,
      format: null,
      analysis_version: 0,
    }),
    [],
  );

  // Clear all confirmation state
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  const searchedTracks = useMemo(() => {
    if (!searchFilter) return tracks;
    const q = searchFilter.toLowerCase();
    return tracks.filter(t =>
      (t.title?.toLowerCase().includes(q)) ||
      (t.artist?.toLowerCase().includes(q)) ||
      (t.album?.toLowerCase().includes(q))
    );
  }, [tracks, searchFilter]);

  const handlePlay = useCallback((startIndex = 0) => {
    if (searchedTracks.length === 0) return;

    // If clicking on the currently playing track, toggle play/pause
    const clickedTrack = searchedTracks[startIndex];
    if (clickedTrack && currentTrack?.id === clickedTrack.id) {
      setIsPlaying(!isPlaying);
      return;
    }

    const queueTracks = searchedTracks.map(t => ({
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
      duration_seconds: null,
      format: null,
      analysis_version: 0,
    }));
    setQueue(queueTracks, startIndex);
  }, [searchedTracks, currentTrack?.id, isPlaying, setIsPlaying, setQueue]);

  const handleRemoveFromDownloads = async (trackId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await removeOfflineTrack(trackId);
      await refresh();
    } catch (error) {
      log.error('Failed to remove track from downloads:', error);
      showError('Failed to remove track from downloads');
    }
  };

  // Clear all downloads handler
  const handleClearAll = async () => {
    try {
      await clearAllOfflineTracks();
      await refresh();
      setShowClearConfirm(false);
      showSuccess('Downloads cleared');
    } catch (error) {
      log.error('Failed to clear downloads:', error);
      showError('Failed to clear downloads');
    }
  };

  // Bulk delete handler
  const handleBulkDelete = useCallback(async (selectedIds: Set<string>, clearSelection: () => void) => {
    const count = selectedIds.size;
    try {
      for (const trackId of selectedIds) {
        await removeOfflineTrack(trackId);
      }
      await refresh();
      clearSelection();
      showSuccess(`Removed ${count} track${count !== 1 ? 's' : ''} from downloads`);
    } catch (error) {
      log.error('Failed to remove selected tracks:', error);
      showError('Failed to remove selected tracks');
    }
  }, [refresh]);

  // Render props for PlaylistTrackList
  const renderDesktopTrailing = useCallback((ctx: TrackRowContext<DownloadedTrack>) => (
    <>
      {/* Size */}
      <div className="text-xs text-zinc-500 text-right">
        {ctx.item.sizeFormatted}
      </div>

      {/* Remove button */}
      <button
        onClick={(e) => handleRemoveFromDownloads(ctx.item.id, e)}
        className="p-1 text-zinc-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
        title="Remove from downloads"
      >
        <Trash2 className="w-4 h-4" />
      </button>
    </>
  ), []);

  const renderMobileTrailing = useCallback((ctx: TrackRowContext<DownloadedTrack>) => (
    <div className="flex-shrink-0 text-xs text-zinc-500">
      {ctx.item.sizeFormatted}
    </div>
  ), []);

  const renderBulkActions = useCallback((selectedIds: Set<string>, clearSelection: () => void) => (
    <button
      onClick={() => handleBulkDelete(selectedIds, clearSelection)}
      className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600/20 hover:bg-red-600/30 text-red-400 rounded-md text-sm transition-colors"
    >
      <Trash2 className="w-4 h-4" />
      Remove from Downloads
    </button>
  ), [handleBulkDelete]);

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="flex items-start gap-4">
        <button
          onClick={onBack}
          className="p-2 hover:bg-zinc-800 rounded-lg transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>

        <div className="flex-1">
          <div className="flex items-center gap-2">
            <HardDrive className="w-5 h-5 text-green-500" />
            <h2 className="text-xl font-bold">Downloads</h2>
          </div>

          <div className="flex items-center gap-4 mt-2 text-sm text-zinc-500">
            <span>{total} tracks</span>
            <span className="flex items-center gap-1">
              <HardDrive className="w-4 h-4" />
              {totalSizeFormatted}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => handlePlay()}
            disabled={tracks.length === 0}
            className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 disabled:hover:bg-green-600 rounded-full transition-colors"
          >
            <Play className="w-4 h-4" fill="currentColor" />
            Play
          </button>

          <button
            onClick={() => setShowClearConfirm(true)}
            disabled={tracks.length === 0}
            className="flex items-center gap-2 px-4 py-2 bg-red-600/20 hover:bg-red-600/30 text-red-400 disabled:opacity-50 disabled:hover:bg-red-600/20 rounded-full transition-colors"
            title="Clear all downloads"
          >
            <Trash2 className="w-4 h-4" />
            Clear All
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
      <PlaylistTrackList
        items={searchedTracks}
        getTrack={getTrackFromDownload}
        onPlay={handlePlay}
        trailingColumns={['4rem', '3rem']}
        renderDesktopTrailing={renderDesktopTrailing}
        renderMobileTrailing={renderMobileTrailing}
        renderBulkActions={renderBulkActions}
        emptyMessage="No downloaded tracks yet"
        emptySubMessage="Download tracks from playlists or the library for offline playback"
        contextMenuOptions={{
          onRemoveFromDownloads: async (track) => {
            try {
              await removeOfflineTrack(track.id);
              await refresh();
            } catch (error) {
              log.error('Failed to remove track from downloads:', error);
              showError('Failed to remove track from downloads');
            }
          },
        }}
      />

      {/* Clear all confirmation modal */}
      {showClearConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-zinc-800 rounded-lg p-6 max-w-md mx-4 shadow-xl border border-zinc-700">
            <h3 className="text-lg font-semibold mb-2">Clear All Downloads?</h3>
            <p className="text-zinc-400 mb-4">
              This will remove {total} track{total !== 1 ? 's' : ''} ({totalSizeFormatted}) from your device.
              You can re-download them later.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowClearConfirm(false)}
                className="px-4 py-2 text-zinc-300 hover:bg-zinc-700 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleClearAll}
                className="px-4 py-2 bg-red-600 hover:bg-red-500 text-white rounded-lg transition-colors"
              >
                Clear All
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
