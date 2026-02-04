import { useState, useCallback } from 'react';
import { ArrowLeft, Play, Pause, Download, Music, Trash2, HardDrive, X } from 'lucide-react';
import { usePlayerStore } from '../../stores/playerStore';
import { useSelectionStore } from '../../stores/selectionStore';
import { useDownloadedTracks } from '../../hooks/useDownloadedTracks';
import { useAppNavigation } from '../../hooks/useAppNavigation';
import { removeOfflineTrack, clearAllOfflineTracks } from '../../services/offlineService';
import { TrackContextMenu } from '../Library/TrackContextMenu';
import type { ContextMenuState } from '../Library/types';
import { initialContextMenuState } from '../Library/types';
import type { Track } from '../../types';
import { showError, showSuccess } from '../../stores/toastStore';

interface Props {
  onBack: () => void;
}

export function DownloadsDetail({ onBack }: Props) {
  const { currentTrack, isPlaying, setQueue, addToQueue, setIsPlaying } = usePlayerStore();
  const { tracks, total, totalSizeFormatted, refresh } = useDownloadedTracks();
  const { navigateToArtist, navigateToAlbum } = useAppNavigation();
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(initialContextMenuState);

  // Clear all confirmation state
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  // Selection state for bulk delete
  const [selectedTrackIds, setSelectedTrackIds] = useState<Set<string>>(new Set());
  const [lastClickedId, setLastClickedId] = useState<string | null>(null);

  // Context menu handlers
  const handleContextMenu = useCallback((track: Track, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({
      isOpen: true,
      track,
      position: { x: e.clientX, y: e.clientY },
    });
  }, []);

  const closeContextMenu = useCallback(() => {
    setContextMenu(initialContextMenuState);
  }, []);

  const handlePlay = useCallback((startIndex = 0) => {
    if (tracks.length === 0) return;

    // If clicking on the currently playing track, toggle play/pause
    const clickedTrack = tracks[startIndex];
    if (clickedTrack && currentTrack?.id === clickedTrack.id) {
      setIsPlaying(!isPlaying);
      return;
    }

    const queueTracks = tracks.map(t => ({
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
  }, [tracks, currentTrack?.id, isPlaying, setIsPlaying, setQueue]);

  const handleRemoveFromDownloads = async (trackId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await removeOfflineTrack(trackId);
      await refresh();
    } catch (error) {
      console.error('Failed to remove track from downloads:', error);
      showError('Failed to remove track from downloads');
    }
  };

  // Clear all downloads handler
  const handleClearAll = async () => {
    try {
      await clearAllOfflineTracks();
      await refresh();
      setShowClearConfirm(false);
      setSelectedTrackIds(new Set());
      showSuccess('Downloads cleared');
    } catch (error) {
      console.error('Failed to clear downloads:', error);
      showError('Failed to clear downloads');
    }
  };

  // Selection handlers
  const handleTrackClick = useCallback((trackId: string, idx: number, e: React.MouseEvent) => {
    if (e.shiftKey && lastClickedId) {
      // Shift-click: select range
      const lastIdx = tracks.findIndex(t => t.id === lastClickedId);
      const currentIdx = idx;
      const [start, end] = [Math.min(lastIdx, currentIdx), Math.max(lastIdx, currentIdx)];
      const rangeIds = tracks.slice(start, end + 1).map(t => t.id);
      setSelectedTrackIds(new Set([...selectedTrackIds, ...rangeIds]));
    } else if (e.metaKey || e.ctrlKey) {
      // Cmd/Ctrl-click: toggle single selection
      const newSet = new Set(selectedTrackIds);
      if (newSet.has(trackId)) {
        newSet.delete(trackId);
      } else {
        newSet.add(trackId);
      }
      setSelectedTrackIds(newSet);
      setLastClickedId(trackId);
    } else {
      // Normal click: play track
      handlePlay(idx);
      setSelectedTrackIds(new Set());
      setLastClickedId(trackId);
    }
  }, [tracks, lastClickedId, selectedTrackIds, handlePlay]);

  // Bulk delete handler
  const handleBulkDelete = async () => {
    const count = selectedTrackIds.size;
    try {
      for (const trackId of selectedTrackIds) {
        await removeOfflineTrack(trackId);
      }
      await refresh();
      setSelectedTrackIds(new Set());
      showSuccess(`Removed ${count} track${count !== 1 ? 's' : ''} from downloads`);
    } catch (error) {
      console.error('Failed to remove selected tracks:', error);
      showError('Failed to remove selected tracks');
    }
  };

  // Checkbox click handler (separate from row click)
  const handleCheckboxClick = useCallback((trackId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const newSet = new Set(selectedTrackIds);
    if (newSet.has(trackId)) {
      newSet.delete(trackId);
    } else {
      newSet.add(trackId);
    }
    setSelectedTrackIds(newSet);
    setLastClickedId(trackId);
  }, [selectedTrackIds]);

  return (
    <div className="space-y-4">
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
            <Download className="w-5 h-5 text-green-500" />
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

      {/* Bulk action toolbar */}
      {selectedTrackIds.size > 0 && (
        <div className="sticky top-0 z-10 bg-zinc-900/95 backdrop-blur-sm p-3 rounded-lg flex items-center gap-3 border border-zinc-700">
          <span className="text-sm text-zinc-300 font-medium">
            {selectedTrackIds.size} track{selectedTrackIds.size !== 1 ? 's' : ''} selected
          </span>
          <div className="flex-1" />
          <button
            onClick={handleBulkDelete}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600/20 hover:bg-red-600/30 text-red-400 rounded-md text-sm transition-colors"
          >
            <Trash2 className="w-4 h-4" />
            Remove from Downloads
          </button>
          <button
            onClick={() => setSelectedTrackIds(new Set())}
            className="p-1.5 hover:bg-zinc-700 rounded-md transition-colors"
            title="Clear selection"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Track list */}
      {tracks.length > 0 ? (
        <div className="space-y-1">
          {tracks.map((track, idx) => {
            // Convert offline track to full Track type for context menu
            const fullTrack: Track = {
              id: track.id,
              file_path: '',
              title: track.title || null,
              artist: track.artist || null,
              album: track.album || null,
              album_artist: null,
              album_type: 'album',
              track_number: null,
              disc_number: null,
              year: null,
              genre: null,
              duration_seconds: null,
              format: null,
              analysis_version: 0,
            };
            const isSelected = selectedTrackIds.has(track.id);
            return (
              <div
                key={track.id}
                onClick={(e) => handleTrackClick(track.id, idx, e)}
                onContextMenu={(e) => handleContextMenu(fullTrack, e)}
                className={`group flex items-center gap-3 p-2 rounded-lg hover:bg-zinc-800/50 cursor-pointer transition-colors ${
                  currentTrack?.id === track.id ? 'bg-zinc-800/30' : ''
                } ${isSelected ? 'bg-green-900/30 ring-1 ring-green-500/50' : ''}`}
              >
                {/* Checkbox */}
                <div
                  onClick={(e) => handleCheckboxClick(track.id, e)}
                  className={`w-5 h-5 flex-shrink-0 rounded border cursor-pointer transition-colors ${
                    isSelected
                      ? 'bg-green-500 border-green-500'
                      : 'border-zinc-600 hover:border-zinc-500'
                  }`}
                >
                  {isSelected && (
                    <svg className="w-5 h-5 text-white" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  )}
                </div>
                {/* Track number / Play button */}
                <div className="w-8 text-center">
                  {currentTrack?.id === track.id && isPlaying ? (
                    <>
                      <div className="group-hover:hidden flex justify-center gap-0.5">
                        <div className="w-0.5 h-3 bg-green-500 animate-pulse" />
                        <div className="w-0.5 h-3 bg-green-500 animate-pulse [animation-delay:0.2s]" />
                        <div className="w-0.5 h-3 bg-green-500 animate-pulse [animation-delay:0.4s]" />
                      </div>
                      <Pause
                        className="hidden group-hover:block w-4 h-4 mx-auto text-white"
                        fill="currentColor"
                      />
                    </>
                  ) : currentTrack?.id === track.id ? (
                    <>
                      <span className="group-hover:hidden text-sm text-green-500">{idx + 1}</span>
                      <Play
                        className="hidden group-hover:block w-4 h-4 mx-auto text-white"
                        fill="currentColor"
                      />
                    </>
                  ) : (
                    <>
                      <span className="group-hover:hidden text-sm text-zinc-500">{idx + 1}</span>
                      <Play
                        className="hidden group-hover:block w-4 h-4 mx-auto text-white"
                        fill="currentColor"
                      />
                    </>
                  )}
                </div>

                {/* Track info */}
                <div className="flex-1 min-w-0">
                  <div className={`font-medium truncate ${currentTrack?.id === track.id ? 'text-green-500' : ''}`}>
                    {track.title || 'Unknown Title'}
                  </div>
                  <div className="text-sm text-zinc-400 truncate">
                    {track.artist || 'Unknown Artist'}
                    {track.album && (
                      <span className="text-zinc-500"> • {track.album}</span>
                    )}
                  </div>
                </div>

                {/* Size */}
                <div className="text-xs text-zinc-500">
                  {track.sizeFormatted}
                </div>

                {/* Remove button */}
                <button
                  onClick={(e) => handleRemoveFromDownloads(track.id, e)}
                  className="p-1 text-zinc-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                  title="Remove from downloads"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="text-center py-12 text-zinc-500">
          <Music className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>No downloaded tracks yet</p>
          <p className="text-sm mt-1">Download tracks from playlists or the library for offline playback</p>
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
            const idx = tracks.findIndex(t => t.id === contextMenu.track?.id);
            if (idx !== -1) handlePlay(idx);
          }}
          onQueue={() => {
            if (contextMenu.track) {
              addToQueue(contextMenu.track);
            }
          }}
          onGoToArtist={() => {
            if (contextMenu.track?.artist) {
              navigateToArtist(contextMenu.track.artist);
            }
          }}
          onGoToAlbum={() => {
            if (contextMenu.track?.artist && contextMenu.track?.album) {
              navigateToAlbum(contextMenu.track.artist, contextMenu.track.album);
            }
          }}
          onToggleSelect={() => {
            // Not applicable in downloads
          }}
          onAddToPlaylist={() => {
            // TODO: Open playlist picker modal
          }}
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
          onRemoveFromDownloads={async () => {
            if (contextMenu.track) {
              try {
                await removeOfflineTrack(contextMenu.track.id);
                await refresh();
              } catch (error) {
                console.error('Failed to remove track from downloads:', error);
                showError('Failed to remove track from downloads');
              }
            }
          }}
        />
      )}

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
