import { useState, useEffect } from 'react';
import {
  Download,
  Trash2,
  Loader2,
  Music,
  Search,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import * as offlineService from '../../services/offlineService';
import type { OfflineTrackInfo } from '../../services/offlineService';

import { createLogger } from '../../utils/logger';

const log = createLogger('OfflineTracksPanel');

type SortField = 'title' | 'artist' | 'album' | 'size' | 'date';
type SortDirection = 'asc' | 'desc';

interface Props {
  onTracksChanged?: () => void;
}

export function OfflineTracksPanel({ onTracksChanged }: Props) {
  const [tracks, setTracks] = useState<OfflineTrackInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [removingIds, setRemovingIds] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const [sortField, setSortField] = useState<SortField>('date');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [isExpanded, setIsExpanded] = useState(false);

  const loadTracks = async () => {
    setIsLoading(true);
    try {
      const info = await offlineService.getOfflineTracksWithInfo();
      setTracks(info);
    } catch (error) {
      log.error('Failed to load offline tracks:', error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadTracks();
  }, []);

  const handleRemoveTrack = async (trackId: string) => {
    setRemovingIds((prev) => new Set([...prev, trackId]));
    try {
      await offlineService.removeOfflineTrack(trackId);
      setTracks((prev) => prev.filter((t) => t.id !== trackId));
      onTracksChanged?.();
    } catch (error) {
      log.error('Failed to remove track:', error);
    } finally {
      setRemovingIds((prev) => {
        const next = new Set(prev);
        next.delete(trackId);
        return next;
      });
    }
  };

  const handleRemoveAll = async () => {
    if (!confirm(`Remove all ${tracks.length} downloaded tracks?`)) {
      return;
    }
    setIsLoading(true);
    try {
      await offlineService.clearAllOfflineTracks();
      setTracks([]);
      onTracksChanged?.();
    } catch (error) {
      log.error('Failed to clear offline tracks:', error);
    } finally {
      setIsLoading(false);
    }
  };

  // Filter and sort tracks
  const filteredTracks = tracks
    .filter((track) => {
      if (!searchQuery) return true;
      const query = searchQuery.toLowerCase();
      return (
        track.title.toLowerCase().includes(query) ||
        track.artist.toLowerCase().includes(query) ||
        track.album.toLowerCase().includes(query)
      );
    })
    .sort((a, b) => {
      let comparison = 0;
      switch (sortField) {
        case 'title':
          comparison = a.title.localeCompare(b.title);
          break;
        case 'artist':
          comparison = a.artist.localeCompare(b.artist);
          break;
        case 'album':
          comparison = a.album.localeCompare(b.album);
          break;
        case 'size':
          comparison = a.sizeBytes - b.sizeBytes;
          break;
        case 'date':
          comparison =
            new Date(a.cachedAt).getTime() - new Date(b.cachedAt).getTime();
          break;
      }
      return sortDirection === 'asc' ? comparison : -comparison;
    });

  const totalSize = tracks.reduce((sum, t) => sum + t.sizeBytes, 0);

  if (isLoading && tracks.length === 0) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
      </div>
    );
  }

  if (tracks.length === 0) {
    return (
      <div className="text-center py-8 text-zinc-500">
        <Download className="w-8 h-8 mx-auto mb-2 opacity-50" />
        <p className="text-sm">No tracks downloaded yet</p>
        <p className="text-xs mt-1">
          Download tracks from the library or playlists for offline playback
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Header with toggle */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between text-left"
      >
        <div className="flex items-center gap-2">
          <Music className="w-4 h-4 text-zinc-400" />
          <span className="text-sm text-zinc-300">
            {tracks.length} track{tracks.length !== 1 ? 's' : ''} (
            {offlineService.formatBytes(totalSize)})
          </span>
        </div>
        {isExpanded ? (
          <ChevronUp className="w-4 h-4 text-zinc-400" />
        ) : (
          <ChevronDown className="w-4 h-4 text-zinc-400" />
        )}
      </button>

      {isExpanded && (
        <>
          {/* Search and actions */}
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search downloaded tracks..."
                className="w-full pl-8 pr-3 py-1.5 text-sm bg-zinc-700/50 border border-zinc-600 rounded-md focus:outline-none focus:border-purple-500"
              />
            </div>
            <button
              onClick={handleRemoveAll}
              disabled={isLoading}
              className="p-1.5 text-red-400 hover:text-red-300 hover:bg-red-400/10 rounded transition-colors disabled:opacity-50"
              title="Remove all"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>

          {/* Sort options */}
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <span>Sort by:</span>
            {(['date', 'title', 'artist', 'size'] as SortField[]).map(
              (field) => (
                <button
                  key={field}
                  onClick={() => {
                    if (sortField === field) {
                      setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'));
                    } else {
                      setSortField(field);
                      setSortDirection(field === 'date' ? 'desc' : 'asc');
                    }
                  }}
                  className={`px-2 py-0.5 rounded ${
                    sortField === field
                      ? 'bg-purple-500/20 text-purple-400'
                      : 'hover:bg-zinc-700'
                  }`}
                >
                  {field.charAt(0).toUpperCase() + field.slice(1)}
                  {sortField === field && (sortDirection === 'asc' ? ' ↑' : ' ↓')}
                </button>
              )
            )}
          </div>

          {/* Track list */}
          <div className="max-h-64 overflow-y-auto space-y-1">
            {filteredTracks.map((track) => (
              <div
                key={track.id}
                className="group flex items-center gap-3 p-2 rounded-md hover:bg-zinc-700/30"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-zinc-200 truncate">
                    {track.title}
                  </div>
                  <div className="text-xs text-zinc-500 truncate">
                    {track.artist} • {track.album}
                  </div>
                </div>
                <div className="text-xs text-zinc-500 whitespace-nowrap">
                  {track.sizeFormatted}
                </div>
                <button
                  onClick={() => handleRemoveTrack(track.id)}
                  disabled={removingIds.has(track.id)}
                  className="p-1 text-zinc-500 hover:text-red-400 transition-colors disabled:opacity-50"
                  title="Remove"
                >
                  {removingIds.has(track.id) ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Trash2 className="w-4 h-4" />
                  )}
                </button>
              </div>
            ))}

            {filteredTracks.length === 0 && searchQuery && (
              <div className="text-center py-4 text-zinc-500 text-sm">
                No tracks match "{searchQuery}"
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
