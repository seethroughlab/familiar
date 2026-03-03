import { useState, useEffect } from 'react';
import {
  AlertTriangle,
  Trash2,
  Search,
  MapPin,
  Loader2,
  FolderSearch,
  CheckCircle,
  XCircle,
  Clock,
} from 'lucide-react';
import { getApiUrl } from '../../api/base';

import { createLogger } from '../../utils/logger';

const log = createLogger('MissingTracksPanel');

interface MissingTrack {
  id: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  file_path: string;
  status: 'missing' | 'pending_deletion';
  missing_since: string | null;
  days_missing: number;
}

interface MissingTracksResponse {
  tracks: MissingTrack[];
  total_missing: number;
  total_pending_deletion: number;
}

export function MissingTracksPanel() {
  const [tracks, setTracks] = useState<MissingTrack[]>([]);
  const [totalMissing, setTotalMissing] = useState(0);
  const [totalPending, setTotalPending] = useState(0);
  const [loading, setLoading] = useState(true);
  const [relocating, setRelocating] = useState(false);
  const [searchPath, setSearchPath] = useState('');
  const [showSearchInput, setShowSearchInput] = useState(false);
  const [status, setStatus] = useState<{ type: 'success' | 'error' | 'info'; message: string } | null>(null);
  const [selectedTracks, setSelectedTracks] = useState<Set<string>>(new Set());
  const [locatingTrackId, setLocatingTrackId] = useState<string | null>(null);
  const [newPath, setNewPath] = useState('');
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());

  const fetchMissingTracks = async () => {
    try {
      const response = await fetch(getApiUrl('/library/missing'));
      if (response.ok) {
        const data: MissingTracksResponse = await response.json();
        setTracks(data.tracks);
        setTotalMissing(data.total_missing);
        setTotalPending(data.total_pending_deletion);
      }
    } catch (error) {
      log.error('Failed to fetch missing tracks:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMissingTracks();
  }, []);

  const handleBatchRelocate = async () => {
    if (!searchPath.trim()) return;

    setRelocating(true);
    setStatus(null);

    try {
      const response = await fetch(getApiUrl('/library/missing/relocate'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ search_path: searchPath.trim() }),
      });

      if (response.ok) {
        const result = await response.json();
        setStatus({
          type: result.found > 0 ? 'success' : 'info',
          message: `Found ${result.found} of ${result.found + result.not_found} missing tracks`,
        });
        await fetchMissingTracks();
        setShowSearchInput(false);
        setSearchPath('');
      } else {
        const error = await response.json();
        setStatus({ type: 'error', message: error.detail || 'Failed to search' });
      }
    } catch {
      setStatus({ type: 'error', message: 'Failed to search folder' });
    } finally {
      setRelocating(false);
      setTimeout(() => setStatus(null), 5000);
    }
  };

  const handleLocateTrack = async (trackId: string) => {
    if (!newPath.trim()) return;

    try {
      const response = await fetch(getApiUrl(`/library/missing/${trackId}/locate`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_path: newPath.trim() }),
      });

      if (response.ok) {
        setStatus({ type: 'success', message: 'Track relocated successfully' });
        await fetchMissingTracks();
        setLocatingTrackId(null);
        setNewPath('');
      } else {
        const error = await response.json();
        setStatus({ type: 'error', message: error.detail || 'Failed to locate' });
      }
    } catch {
      setStatus({ type: 'error', message: 'Failed to locate track' });
    } finally {
      setTimeout(() => setStatus(null), 5000);
    }
  };

  const handleDeleteTrack = async (trackId: string) => {
    setDeletingIds((prev) => new Set(prev).add(trackId));

    try {
      const response = await fetch(getApiUrl(`/library/missing/${trackId}`), {
        method: 'DELETE',
      });

      if (response.ok) {
        await fetchMissingTracks();
        setSelectedTracks((prev) => {
          const next = new Set(prev);
          next.delete(trackId);
          return next;
        });
      } else {
        const error = await response.json();
        setStatus({ type: 'error', message: error.detail || 'Failed to delete' });
        setTimeout(() => setStatus(null), 5000);
      }
    } finally {
      setDeletingIds((prev) => {
        const next = new Set(prev);
        next.delete(trackId);
        return next;
      });
    }
  };

  const handleBatchDelete = async () => {
    if (selectedTracks.size === 0) return;

    const confirmed = window.confirm(
      `Are you sure you want to permanently delete ${selectedTracks.size} track(s)? This cannot be undone.`
    );
    if (!confirmed) return;

    try {
      const response = await fetch(getApiUrl('/library/missing/batch'), {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ track_ids: Array.from(selectedTracks) }),
      });

      if (response.ok) {
        const result = await response.json();
        setStatus({
          type: result.deleted > 0 ? 'success' : 'info',
          message: `Deleted ${result.deleted} track(s)`,
        });
        await fetchMissingTracks();
        setSelectedTracks(new Set());
      } else {
        setStatus({ type: 'error', message: 'Failed to delete tracks' });
      }
    } catch {
      setStatus({ type: 'error', message: 'Failed to delete tracks' });
    } finally {
      setTimeout(() => setStatus(null), 5000);
    }
  };

  const toggleTrackSelection = (trackId: string) => {
    setSelectedTracks((prev) => {
      const next = new Set(prev);
      if (next.has(trackId)) {
        next.delete(trackId);
      } else {
        next.add(trackId);
      }
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedTracks.size === tracks.length) {
      setSelectedTracks(new Set());
    } else {
      setSelectedTracks(new Set(tracks.map((t) => t.id)));
    }
  };

  if (loading) {
    return (
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <div className="flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin text-zinc-400" />
          <span className="text-sm text-zinc-400">Loading missing tracks...</span>
        </div>
      </div>
    );
  }

  if (tracks.length === 0) {
    return (
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <div className="flex items-center gap-2 mb-2">
          <CheckCircle className="w-5 h-5 text-green-400" />
          <h4 className="font-medium text-white">No Missing Tracks</h4>
        </div>
        <p className="text-sm text-zinc-400">All tracks in your library are accounted for.</p>
      </div>
    );
  }

  // Group tracks by album
  const tracksByAlbum = tracks.reduce(
    (acc, track) => {
      const key = track.album || 'Unknown Album';
      if (!acc[key]) acc[key] = [];
      acc[key].push(track);
      return acc;
    },
    {} as Record<string, MissingTrack[]>
  );

  return (
    <div className="bg-zinc-800/50 rounded-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-amber-400" />
          <h4 className="font-medium text-white">Missing Tracks</h4>
          <span className="text-sm text-zinc-400">
            ({totalMissing} missing, {totalPending} pending deletion)
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowSearchInput(!showSearchInput)}
            className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm transition-colors"
          >
            <FolderSearch className="w-4 h-4" />
            Search Folder
          </button>
          {selectedTracks.size > 0 && (
            <button
              onClick={handleBatchDelete}
              className="flex items-center gap-1 px-3 py-1.5 bg-red-600 hover:bg-red-700 rounded-lg text-sm transition-colors"
            >
              <Trash2 className="w-4 h-4" />
              Delete ({selectedTracks.size})
            </button>
          )}
        </div>
      </div>

      {/* Status message */}
      {status && (
        <div
          className={`flex items-center gap-2 p-2 mb-3 rounded-lg text-sm ${
            status.type === 'success'
              ? 'bg-green-900/30 text-green-400 border border-green-800'
              : status.type === 'error'
                ? 'bg-red-900/30 text-red-400 border border-red-800'
                : 'bg-blue-900/30 text-blue-400 border border-blue-800'
          }`}
        >
          {status.type === 'success' ? (
            <CheckCircle className="w-4 h-4" />
          ) : status.type === 'error' ? (
            <XCircle className="w-4 h-4" />
          ) : (
            <Search className="w-4 h-4" />
          )}
          {status.message}
        </div>
      )}

      {/* Search folder input */}
      {showSearchInput && (
        <div className="flex gap-2 mb-4 p-3 bg-zinc-900/50 rounded-lg border border-zinc-700">
          <input
            type="text"
            value={searchPath}
            onChange={(e) => setSearchPath(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleBatchRelocate()}
            placeholder="/path/to/search"
            className="flex-1 px-3 py-2 bg-zinc-800 border border-zinc-600 rounded-lg text-base font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            onClick={handleBatchRelocate}
            disabled={relocating || !searchPath.trim()}
            className="flex items-center gap-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg text-sm transition-colors"
          >
            {relocating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            Search
          </button>
        </div>
      )}

      {/* Select all */}
      <div className="flex items-center gap-2 mb-3 pb-2 border-b border-zinc-700">
        <input
          type="checkbox"
          checked={selectedTracks.size === tracks.length}
          onChange={toggleSelectAll}
          className="w-4 h-4 rounded bg-zinc-700 border-zinc-600"
        />
        <span className="text-sm text-zinc-400">Select all ({tracks.length})</span>
      </div>

      {/* Track list grouped by album */}
      <div className="space-y-4 max-h-96 overflow-y-auto">
        {Object.entries(tracksByAlbum).map(([album, albumTracks]) => (
          <div key={album} className="space-y-1">
            <h5 className="text-xs font-medium text-zinc-500 uppercase tracking-wide">{album}</h5>
            {albumTracks.map((track) => (
              <div
                key={track.id}
                className={`flex items-center gap-2 p-2 rounded-lg transition-colors ${
                  track.status === 'pending_deletion'
                    ? 'bg-red-900/20 border border-red-800/50'
                    : 'bg-zinc-900/50 border border-zinc-700/50'
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedTracks.has(track.id)}
                  onChange={() => toggleTrackSelection(track.id)}
                  className="w-4 h-4 rounded bg-zinc-700 border-zinc-600"
                />

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-white truncate">
                      {track.title || track.file_path.split('/').pop()}
                    </span>
                    {track.status === 'pending_deletion' && (
                      <span className="text-xs px-1.5 py-0.5 bg-red-600 rounded">Pending Deletion</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-zinc-500">
                    <span>{track.artist || 'Unknown Artist'}</span>
                    <span className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {track.days_missing} days missing
                      {track.status === 'missing' && (
                        <span className="text-zinc-600">({30 - track.days_missing} until pending deletion)</span>
                      )}
                    </span>
                  </div>
                  <p className="text-xs text-zinc-600 font-mono truncate">{track.file_path}</p>
                </div>

                {/* Locate input for this track */}
                {locatingTrackId === track.id ? (
                  <div className="flex items-center gap-1">
                    <input
                      type="text"
                      value={newPath}
                      onChange={(e) => setNewPath(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleLocateTrack(track.id)}
                      placeholder="/new/path/to/file"
                      className="w-48 px-2 py-1 bg-zinc-800 border border-zinc-600 rounded text-base font-mono focus:outline-none focus:ring-1 focus:ring-blue-500"
                      autoFocus
                    />
                    <button
                      onClick={() => handleLocateTrack(track.id)}
                      className="p-1 text-green-400 hover:text-green-300"
                      title="Confirm"
                    >
                      <CheckCircle className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => {
                        setLocatingTrackId(null);
                        setNewPath('');
                      }}
                      className="p-1 text-zinc-400 hover:text-zinc-300"
                      title="Cancel"
                    >
                      <XCircle className="w-4 h-4" />
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setLocatingTrackId(track.id)}
                      className="p-1 text-zinc-400 hover:text-blue-400 transition-colors"
                      title="Locate file"
                    >
                      <MapPin className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDeleteTrack(track.id)}
                      disabled={deletingIds.has(track.id)}
                      className="p-1 text-zinc-400 hover:text-red-400 transition-colors disabled:opacity-50"
                      title="Delete"
                    >
                      {deletingIds.has(track.id) ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Trash2 className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      <p className="text-xs text-zinc-500 mt-3">
        Missing tracks are kept for 30 days before being marked for deletion. Use "Search Folder" to find files that
        have moved, or "Locate" to specify a new path for individual tracks.
      </p>
    </div>
  );
}
