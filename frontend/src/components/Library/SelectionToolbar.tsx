/**
 * Toolbar that appears when tracks are selected.
 *
 * Shows selection count and actions like "Add to Playlist" and "Clear".
 */
import { useState } from 'react';
import { X, ListPlus, Play, Loader2 } from 'lucide-react';
import { playlistsApi } from '../../api/client';
import type { Track } from '../../types';

interface SelectionToolbarProps {
  selectedCount: number;
  onClear: () => void;
  onPlaySelected: () => void;
  getSelectedTracks: () => Track[];
}

export function SelectionToolbar({
  selectedCount,
  onClear,
  onPlaySelected,
  getSelectedTracks,
}: SelectionToolbarProps) {
  const [showPlaylistMenu, setShowPlaylistMenu] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [playlistName, setPlaylistName] = useState('');

  if (selectedCount === 0) {
    return null;
  }

  const handleCreatePlaylist = async () => {
    if (!playlistName.trim()) return;

    setIsCreating(true);
    try {
      const tracks = getSelectedTracks();
      await playlistsApi.create({
        name: playlistName.trim(),
        track_ids: tracks.map((t) => t.id),
      });
      setPlaylistName('');
      setShowPlaylistMenu(false);
      onClear(); // Clear selection after adding to playlist
    } catch (err) {
      console.error('Failed to create playlist:', err);
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="sticky top-0 z-10 hidden md:flex items-center justify-between gap-4 px-4 py-2 bg-purple-900/90 backdrop-blur-sm border-b border-purple-700">
      <div className="flex items-center gap-4">
        <span className="text-sm font-medium text-white">
          {selectedCount} track{selectedCount !== 1 ? 's' : ''} selected
        </span>

        {/* Play selected */}
        <button
          onClick={onPlaySelected}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-white/10 hover:bg-white/20 rounded-md transition-colors"
        >
          <Play className="w-4 h-4" />
          Play
        </button>

        {/* Add to playlist */}
        <div className="relative">
          <button
            onClick={() => setShowPlaylistMenu(!showPlaylistMenu)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-white/10 hover:bg-white/20 rounded-md transition-colors"
          >
            <ListPlus className="w-4 h-4" />
            Add to Playlist
          </button>

          {showPlaylistMenu && (
            <div className="absolute top-full left-0 mt-1 w-64 p-3 bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl">
              <div className="text-xs text-zinc-400 mb-2">Create new playlist</div>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={playlistName}
                  onChange={(e) => setPlaylistName(e.target.value)}
                  placeholder="Playlist name..."
                  className="flex-1 px-2 py-1.5 text-base bg-zinc-700 border border-zinc-600 rounded focus:outline-none focus:border-purple-500"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleCreatePlaylist();
                    if (e.key === 'Escape') setShowPlaylistMenu(false);
                  }}
                />
                <button
                  onClick={handleCreatePlaylist}
                  disabled={isCreating || !playlistName.trim()}
                  className="px-3 py-1.5 text-sm bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed rounded transition-colors"
                >
                  {isCreating ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    'Create'
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Clear button */}
      <button
        onClick={onClear}
        className="p-1.5 text-white/70 hover:text-white hover:bg-white/10 rounded transition-colors"
        title="Clear selection"
      >
        <X className="w-5 h-5" />
      </button>
    </div>
  );
}
