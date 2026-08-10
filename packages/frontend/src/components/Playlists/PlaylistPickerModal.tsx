/**
 * Modal for picking a playlist to add tracks to.
 * Shows existing playlists with search filter and a "Create New" option.
 */
import { useState, useEffect, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { X, Search, Plus, Loader2, ListMusic } from 'lucide-react';
import { playlistsApi, type Playlist } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { useUIStore } from '../../stores/uiStore';
import { showSuccess, showError } from '../../stores/toastStore';

interface Props {
  trackIds: string[];
}

export function PlaylistPickerModal({ trackIds }: Props) {
  const [search, setSearch] = useState('');
  const [adding, setAdding] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const closePlaylistPicker = useUIStore((s) => s.closePlaylistPicker);

  // `true` — every playlist, including auto-generated ones.
  //
  // It passed `false`, which meant "Add to playlist" silently omitted every playlist made through
  // the old chat surface. Those are real playlists a listener made deliberately, and there is no way
  // to convert one into a "regular" playlist, so the exclusion was permanent.
  //
  // It also collided: this shares `queryKeys.playlists.all` with the sidebar, which asks for `true`.
  // Same cache key, different parameters — so which set you got depended on which mounted first.
  const { data: playlists = [], isLoading } = useQuery({
    queryKey: queryKeys.playlists.all,
    queryFn: () => playlistsApi.list(true),
  });

  useEffect(() => {
    setTimeout(() => searchRef.current?.focus(), 50);
  }, []);

  const filtered = playlists.filter(
    (p: Playlist) => p.name.toLowerCase().includes(search.toLowerCase())
  );

  const handleAdd = async (playlistId: string, playlistName: string) => {
    setAdding(playlistId);
    try {
      await playlistsApi.addTracks(playlistId, trackIds);
      queryClient.invalidateQueries({ queryKey: queryKeys.playlist.detail(playlistId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.playlists.all });
      const count = trackIds.length;
      showSuccess(`Added ${count} ${count === 1 ? 'track' : 'tracks'} to "${playlistName}"`);
      closePlaylistPicker();
    } catch {
      showError('Failed to add tracks');
    } finally {
      setAdding(null);
    }
  };

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const created = await playlistsApi.create({ name: newName.trim(), track_ids: trackIds });
      queryClient.invalidateQueries({ queryKey: queryKeys.playlists.all });
      const count = trackIds.length;
      showSuccess(`Created "${created.name}" with ${count} ${count === 1 ? 'track' : 'tracks'}`);
      closePlaylistPicker();
    } catch {
      showError('Failed to create playlist');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={closePlaylistPicker}>
      <div
        className="bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl w-80 max-h-[70vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 pb-3">
          <h3 className="text-sm font-medium text-white">Add to Playlist</h3>
          <button onClick={closePlaylistPicker} className="text-zinc-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Search */}
        <div className="px-4 pb-3">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-500" />
            <input
              ref={searchRef}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search playlists..."
              className="w-full pl-7 pr-2 py-1.5 text-sm bg-zinc-900 border border-zinc-600 rounded text-white placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
              onKeyDown={(e) => e.key === 'Escape' && closePlaylistPicker()}
            />
          </div>
        </div>

        {/* Create New */}
        <div className="px-4 pb-2">
          <div className="flex items-center gap-2">
            <Plus className="w-4 h-4 text-zinc-400 shrink-0" />
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="New playlist name..."
              className="flex-1 px-2 py-1 text-sm bg-zinc-900 border border-zinc-600 rounded text-white placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleCreate();
                if (e.key === 'Escape') closePlaylistPicker();
              }}
            />
            {newName.trim() && (
              <button
                onClick={handleCreate}
                disabled={creating}
                className="px-2 py-1 text-xs bg-zinc-600 hover:bg-zinc-500 text-white rounded disabled:opacity-50 transition-colors"
              >
                {creating ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Create'}
              </button>
            )}
          </div>
        </div>

        {/* Playlist List */}
        <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-2">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-8 text-sm text-zinc-500">
              {search ? 'No matching playlists' : 'No playlists yet'}
            </div>
          ) : (
            filtered.map((playlist: Playlist) => (
              <button
                key={playlist.id}
                onClick={() => handleAdd(playlist.id, playlist.name)}
                disabled={adding !== null}
                className="w-full flex items-center gap-3 px-2 py-2 rounded hover:bg-zinc-700/50 transition-colors text-left disabled:opacity-50"
              >
                <ListMusic className="w-4 h-4 text-zinc-400 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-white truncate">{playlist.name}</div>
                  <div className="text-xs text-zinc-500">{playlist.track_count} tracks</div>
                </div>
                {adding === playlist.id && (
                  <Loader2 className="w-4 h-4 animate-spin text-zinc-400 shrink-0" />
                )}
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
