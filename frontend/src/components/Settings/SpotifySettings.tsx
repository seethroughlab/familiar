import { useState, useEffect, useCallback, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { spotifyApi } from '../../api';
import type { SpotifyStatus, SpotifyExportPreview, SpotifyExportImportOptions } from '../../api';
import { Music2, RefreshCw, LogOut, ExternalLink, CheckCircle, XCircle, Loader2, AlertTriangle, Upload, FileArchive } from 'lucide-react';
import { MissingTracks } from '../Library/MissingTracks';
import { showSuccess, showError } from '../../stores/toastStore';

import { createLogger } from '../../utils/logger';

const log = createLogger('SpotifySettings');

interface SyncProgress {
  phase: string;
  tracks_fetched: number;
  tracks_processed: number;
  tracks_total: number;
  new_favorites: number;
  matched: number;
  unmatched: number;
  current_track: string | null;
  started_at: string | null;
  errors: string[];
}

interface SyncStatus {
  status: string;
  message: string;
  progress?: SyncProgress | null;
  rate_limited_until?: string | null;
}

export function SpotifySettings() {
  const queryClient = useQueryClient();
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [favoriteMatched, setFavoriteMatched] = useState(true);
  const [rateLimitCountdown, setRateLimitCountdown] = useState<number>(0);

  // Track rate limit countdown
  useEffect(() => {
    const until = syncStatus?.rate_limited_until;
    if (!until) {
      setRateLimitCountdown(0);
      return;
    }

    const calcRemaining = () => {
      const remaining = Math.max(0, Math.ceil((new Date(until).getTime() - Date.now()) / 1000));
      setRateLimitCountdown(remaining);
      return remaining;
    };

    if (calcRemaining() === 0) return;

    const interval = setInterval(() => {
      if (calcRemaining() === 0) {
        clearInterval(interval);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [syncStatus?.rate_limited_until]);

  // Check URL params for OAuth callback status
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const spotifyConnected = params.get('spotify_connected');
    const spotifyError = params.get('spotify_error');
    const spotifyUser = params.get('spotify_user');

    if (spotifyConnected === 'true') {
      setSyncMessage(`Connected as ${spotifyUser || 'user'}!`);
      queryClient.invalidateQueries({ queryKey: ['spotify-status'] });
      // Clean up URL
      window.history.replaceState({}, '', window.location.pathname);
    } else if (spotifyError) {
      setSyncMessage(`Error: ${spotifyError}`);
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, [queryClient]);

  // Fetch sync status
  const fetchSyncStatus = useCallback(async () => {
    try {
      const response = await spotifyApi.getSyncStatus();
      setSyncStatus(response);
      return response.status === 'running';
    } catch (error) {
      log.error('Failed to fetch sync status:', error);
    }
    return false;
  }, []);

  // Initial fetch - start polling if sync is already running
  useEffect(() => {
    const checkInitialStatus = async () => {
      const isRunning = await fetchSyncStatus();
      if (isRunning) {
        setIsPolling(true);
      }
    };
    checkInitialStatus();
  }, [fetchSyncStatus]);

  // Poll while sync is running
  useEffect(() => {
    if (!isPolling) return;

    const interval = setInterval(async () => {
      const stillRunning = await fetchSyncStatus();
      if (!stillRunning) {
        setIsPolling(false);
        // Sync completed - refresh stats
        queryClient.invalidateQueries({ queryKey: ['spotify-status'] });

        // Surface the result to the user
        if (syncStatus?.status === 'error') {
          showError(syncStatus.message || 'Spotify sync failed');
        } else if (syncStatus?.status === 'completed') {
          showSuccess(syncStatus.message || 'Spotify sync complete');
        }
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [isPolling, fetchSyncStatus, queryClient]);

  const { data: status, isLoading } = useQuery<SpotifyStatus>({
    queryKey: ['spotify-status'],
    queryFn: spotifyApi.getStatus,
    refetchInterval: 30000, // Refresh every 30 seconds
  });

  const connectMutation = useMutation({
    mutationFn: spotifyApi.getAuthUrl,
    onSuccess: (data) => {
      if (data.auth_url) {
        window.location.href = data.auth_url;
      } else {
        setSyncMessage('Error: No auth URL received');
      }
    },
    onError: (error: Error) => {
      setSyncMessage(`Failed to get auth URL: ${error.message}`);
    },
  });

  const syncMutation = useMutation({
    mutationFn: () => spotifyApi.sync(true, favoriteMatched),
    onSuccess: (data) => {
      if (data.status === 'started' || data.status === 'already_running') {
        setIsPolling(true);
        setSyncMessage(null);
      } else if (data.status === 'rate_limited') {
        setSyncStatus(data);
        setSyncMessage(null);
      } else {
        setSyncMessage(data.message);
        queryClient.invalidateQueries({ queryKey: ['spotify-status'] });
      }
    },
    onError: (error: Error) => {
      setSyncMessage(`Sync failed: ${error.message}`);
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: spotifyApi.disconnect,
    onSuccess: () => {
      setSyncMessage('Disconnected from Spotify');
      queryClient.invalidateQueries({ queryKey: ['spotify-status'] });
    },
    onError: (error: Error) => {
      setSyncMessage(`Failed to disconnect: ${error.message}`);
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }

  if (!status?.configured) {
    return (
      <div className="bg-zinc-800/50 rounded-lg p-6">
        <div className="flex items-start gap-4">
          <div className="p-3 bg-zinc-700 rounded-lg">
            <Music2 className="w-6 h-6 text-zinc-400" />
          </div>
          <div className="flex-1">
            <h3 className="font-medium text-white">Spotify</h3>
            <div className="mt-3 flex items-start gap-2 p-3 bg-amber-900/20 border border-amber-800 rounded-lg">
              <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-sm text-amber-400">Spotify API not configured</p>
                <p className="text-xs text-zinc-500 mt-1">
                  Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in docker/.env to enable Spotify integration.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Connection status card */}
      <div className="bg-zinc-800/50 rounded-lg p-6">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div className="flex items-start gap-4">
            <div className={`p-3 rounded-lg flex-shrink-0 ${status.connected ? 'bg-green-500/20' : 'bg-zinc-700'}`}>
              <Music2 className={`w-6 h-6 ${status.connected ? 'text-green-500' : 'text-zinc-400'}`} />
            </div>
            <div>
              <h3 className="font-medium text-white flex items-center gap-2">
                Spotify
                {status.connected ? (
                  <CheckCircle className="w-4 h-4 text-green-500" />
                ) : (
                  <XCircle className="w-4 h-4 text-zinc-500" />
                )}
              </h3>
              {status.connected ? (
                <p className="text-sm text-zinc-400 mt-1">
                  Connected as <span className="text-white">{status.spotify_user_id}</span>
                </p>
              ) : (
                <p className="text-sm text-zinc-400 mt-1">
                  Connect your Spotify account to sync your favorites
                </p>
              )}
            </div>
          </div>

          {/* Sync options and action buttons */}
          <div className="flex flex-col gap-3">
            {status.connected && (
              <label className="flex items-center gap-2 text-sm text-zinc-400 cursor-pointer">
                <input
                  type="checkbox"
                  checked={favoriteMatched}
                  onChange={(e) => setFavoriteMatched(e.target.checked)}
                  className="rounded border-zinc-600 bg-zinc-700 text-green-500 focus:ring-green-500 focus:ring-offset-zinc-800"
                />
                Favorite matched tracks in local library
              </label>
            )}
            <div className="flex gap-2 flex-wrap">
              {status.connected ? (
                <>
                  <button
                    onClick={() => syncMutation.mutate()}
                    disabled={syncMutation.isPending || isPolling || rateLimitCountdown > 0}
                    className="flex items-center gap-2 px-3 py-1.5 text-sm bg-green-600 hover:bg-green-500 text-white rounded-md disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {(syncMutation.isPending || isPolling) ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <RefreshCw className="w-4 h-4" />
                    )}
                    {isPolling ? 'Syncing...' : 'Sync'}
                  </button>
                <button
                  onClick={() => disconnectMutation.mutate()}
                  disabled={disconnectMutation.isPending}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm bg-zinc-700 hover:bg-zinc-600 text-white rounded-md disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <LogOut className="w-4 h-4" />
                  Disconnect
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  connectMutation.mutate();
                }}
                disabled={connectMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 text-sm bg-[#1DB954] hover:bg-[#1ed760] text-black font-medium rounded-full disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {connectMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <ExternalLink className="w-4 h-4" />
                )}
                Connect Spotify
              </button>
            )}
            </div>
          </div>
        </div>

        {/* Status message */}
        {syncMessage && (
          <div className="mt-4 p-3 bg-zinc-700/50 rounded-md text-sm text-zinc-300">
            {syncMessage}
          </div>
        )}

        {/* Rate limit warning */}
        {rateLimitCountdown > 0 && (
          <div className="mt-4 flex items-start gap-2 p-3 bg-amber-900/20 border border-amber-800 rounded-lg">
            <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-sm text-amber-400">Spotify rate limited</p>
              <p className="text-xs text-zinc-400 mt-0.5">
                Available again in {(() => { const h = Math.floor(rateLimitCountdown / 3600); const m = Math.floor((rateLimitCountdown % 3600) / 60); const s = rateLimitCountdown % 60; return `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`; })()}
              </p>
            </div>
          </div>
        )}

        {/* Sync progress when running */}
        {(isPolling || syncStatus?.status === 'error') && syncStatus?.progress && (
          <div className="mt-4 space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-zinc-400">
                {syncStatus.progress.phase === 'connecting' && 'Connecting to Spotify...'}
                {syncStatus.progress.phase === 'fetching' && 'Fetching tracks from Spotify...'}
                {syncStatus.progress.phase === 'matching' && 'Matching to local library...'}
                {syncStatus.progress.phase === 'complete' && 'Complete'}
                {syncStatus.progress.phase === 'error' && 'Sync failed'}
              </span>
              <span className="text-zinc-300">
                {syncStatus.progress.phase === 'fetching' ? (
                  `${syncStatus.progress.tracks_fetched} tracks fetched`
                ) : syncStatus.progress.tracks_total > 0 ? (
                  `${Math.round((syncStatus.progress.tracks_processed / syncStatus.progress.tracks_total) * 100)}%`
                ) : null}
              </span>
            </div>

            <div className="w-full bg-zinc-700 rounded-full h-2">
              {syncStatus.progress.phase === 'fetching' ? (
                <div className="bg-green-500 h-2 rounded-full w-1/3 animate-pulse" />
              ) : syncStatus.progress.tracks_total > 0 ? (
                <div
                  className="bg-green-500 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${(syncStatus.progress.tracks_processed / syncStatus.progress.tracks_total) * 100}%` }}
                />
              ) : (
                <div className="bg-green-500 h-2 rounded-full w-1/4 animate-pulse" />
              )}
            </div>

            {syncStatus.progress.current_track && (
              <p className="text-xs text-zinc-500 truncate">
                {syncStatus.progress.current_track}
              </p>
            )}

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-center text-xs">
              <div className="bg-zinc-700/50 rounded p-2">
                <div className="text-green-400 font-medium">{syncStatus.progress.new_favorites}</div>
                <div className="text-zinc-500">New</div>
              </div>
              <div className="bg-zinc-700/50 rounded p-2">
                <div className="text-blue-400 font-medium">{syncStatus.progress.matched}</div>
                <div className="text-zinc-500">Matched</div>
              </div>
              <div className="bg-zinc-700/50 rounded p-2">
                <div className="text-orange-400 font-medium">{syncStatus.progress.unmatched}</div>
                <div className="text-zinc-500">Unmatched</div>
              </div>
            </div>

            {Array.isArray(syncStatus.progress.errors) && syncStatus.progress.errors.length > 0 && (
              <div className="mt-2 p-2 bg-red-900/20 border border-red-800 rounded text-xs text-red-300">
                <p className="font-medium mb-1">Errors ({syncStatus.progress.errors.length}):</p>
                <ul className="list-disc list-inside">
                  {syncStatus.progress.errors.slice(0, 3).map((err, i) => (
                    <li key={i} className="truncate">{err}</li>
                  ))}
                  {syncStatus.progress.errors.length > 3 && (
                    <li>...and {syncStatus.progress.errors.length - 3} more</li>
                  )}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Stats card (when connected) */}
      {status.connected && status.stats && (
        <div className="bg-zinc-800/50 rounded-lg p-6">
          <h4 className="text-sm font-medium text-zinc-400 mb-4">Sync Statistics</h4>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="text-center">
              <div className="text-2xl font-bold text-white">{status.stats.total_favorites}</div>
              <div className="text-xs text-zinc-500 mt-1">Total Favorites</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-green-500">{status.stats.matched}</div>
              <div className="text-xs text-zinc-500 mt-1">Matched</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-orange-500">{status.stats.unmatched}</div>
              <div className="text-xs text-zinc-500 mt-1">Unmatched</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-white">{status.stats.match_rate}%</div>
              <div className="text-xs text-zinc-500 mt-1">Match Rate</div>
            </div>
          </div>
          {status.last_sync && (
            <div className="mt-4 text-xs text-zinc-500 text-center">
              Last synced: {new Date(status.last_sync).toLocaleString()}
            </div>
          )}
        </div>
      )}

      {/* Missing tracks with store search links */}
      {status.connected && status.stats && status.stats.unmatched > 0 && (
        <MissingTracks />
      )}

      {/* Spotify Data Export Import */}
      <SpotifyExportImport />
    </div>
  );
}


// ============================================================================
// Spotify Data Export Import Component
// ============================================================================

function SpotifyExportImport() {
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [preview, setPreview] = useState<SpotifyExportPreview | null>(null);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<{ favorites_imported: number; playlists_created: number; tracks_favorited: number; errors: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [options, setOptions] = useState<SpotifyExportImportOptions>({
    import_favorites: true,
    import_playlists: true,
    favorite_matched: false,
  });

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  }, []);

  const handleFile = useCallback(async (file: File) => {
    setError(null);
    setResult(null);
    setPreview(null);
    setUploading(true);

    try {
      const data = await spotifyApi.uploadExport(file);
      setPreview(data);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Upload failed';
      setError(message);
      log.error('Export upload failed:', err);
    } finally {
      setUploading(false);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files?.[0]) {
      handleFile(e.dataTransfer.files[0]);
    }
  }, [handleFile]);

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) {
      handleFile(e.target.files[0]);
    }
  }, [handleFile]);

  const handleExecute = useCallback(async () => {
    if (!preview?.session_id) return;
    setImporting(true);
    setError(null);

    try {
      const data = await spotifyApi.executeImport(preview.session_id, options);
      setResult(data);
      setPreview(null);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Import failed';
      setError(message);
      log.error('Import execution failed:', err);
    } finally {
      setImporting(false);
    }
  }, [preview, options]);

  const handleReset = useCallback(() => {
    setPreview(null);
    setResult(null);
    setError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, []);

  return (
    <div className="bg-zinc-800/50 rounded-lg p-6">
      <div className="flex items-center gap-3 mb-4">
        <Upload className="w-5 h-5 text-zinc-400" />
        <div>
          <h3 className="font-medium text-white">Import Spotify Data Export</h3>
          <p className="text-sm text-zinc-400">
            Import your saved tracks and playlists from a Spotify data export
          </p>
        </div>
      </div>

      <p className="text-xs text-zinc-500 mb-4">
        Request your data at{' '}
        <a
          href="https://www.spotify.com/account/privacy/"
          target="_blank"
          rel="noopener noreferrer"
          className="text-green-500 hover:text-green-400 underline"
        >
          spotify.com/account &rarr; Privacy &rarr; Download your data
        </a>
      </p>

      {/* Upload zone */}
      {!preview && !result && (
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors cursor-pointer ${
            dragActive
              ? 'border-green-500 bg-green-500/10'
              : 'border-zinc-600 hover:border-zinc-500'
          }`}
          onClick={() => fileInputRef.current?.click()}
        >
          {uploading ? (
            <div className="flex flex-col items-center gap-2">
              <Loader2 className="w-8 h-8 text-green-500 animate-spin" />
              <p className="text-sm text-zinc-400">Processing export file...</p>
            </div>
          ) : (
            <>
              <FileArchive className="w-8 h-8 text-zinc-500 mx-auto mb-2" />
              <p className="text-sm text-zinc-400 mb-1">
                Drop your Spotify export here, or click to browse
              </p>
              <p className="text-xs text-zinc-500">
                .zip or individual .json files (YourLibrary.json, Playlist*.json)
              </p>
            </>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept=".zip,.json"
            onChange={handleFileInput}
            className="hidden"
          />
        </div>
      )}

      {/* Error message */}
      {error && (
        <div className="mt-3 p-3 bg-red-900/20 border border-red-800 rounded-lg flex items-start gap-2">
          <XCircle className="w-4 h-4 text-red-400 mt-0.5 flex-shrink-0" />
          <p className="text-sm text-red-400">{error}</p>
        </div>
      )}

      {/* Preview */}
      {preview && !result && (
        <div className="mt-4 space-y-4">
          <div className="text-sm text-zinc-400">
            Found {preview.files_found.length} file(s): {preview.files_found.join(', ')}
          </div>

          {/* Stats grid */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {preview.library_tracks.total > 0 && (
              <div className="bg-zinc-900/50 rounded-lg p-3">
                <div className="text-lg font-bold text-white">{preview.library_tracks.total}</div>
                <div className="text-xs text-zinc-500">Saved Tracks</div>
                <div className="text-xs text-green-400 mt-1">
                  {preview.library_tracks.matched} matched ({preview.library_tracks.match_rate}%)
                </div>
              </div>
            )}

            {preview.playlists.total > 0 && (
              <div className="bg-zinc-900/50 rounded-lg p-3">
                <div className="text-lg font-bold text-white">{preview.playlists.total}</div>
                <div className="text-xs text-zinc-500">Playlists</div>
                {preview.playlists.details.length > 0 && (
                  <div className="text-xs text-zinc-400 mt-1">
                    {preview.playlists.details.reduce((a, p) => a + p.total_tracks, 0)} total tracks
                  </div>
                )}
              </div>
            )}

            {preview.streaming_history.total_tracks > 0 && (
              <div className="bg-zinc-900/50 rounded-lg p-3">
                <div className="text-lg font-bold text-white">{preview.streaming_history.total_streams.toLocaleString()}</div>
                <div className="text-xs text-zinc-500">Stream Events</div>
                <div className="text-xs text-zinc-400 mt-1">
                  {preview.streaming_history.total_tracks} unique tracks
                </div>
              </div>
            )}
          </div>

          {/* Playlist details */}
          {preview.playlists.details.length > 0 && (
            <div className="space-y-1">
              <h4 className="text-sm font-medium text-zinc-400">Playlists</h4>
              <div className="max-h-32 overflow-y-auto space-y-1">
                {preview.playlists.details.map((p, i) => (
                  <div key={i} className="flex items-center justify-between text-sm bg-zinc-900/30 rounded px-3 py-1.5">
                    <span className="truncate text-zinc-300">{p.name}</span>
                    <span className="text-xs text-zinc-500 flex-shrink-0 ml-2">
                      {p.matched}/{p.total_tracks} matched
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Import options */}
          <div className="space-y-2 border-t border-zinc-700 pt-3">
            <h4 className="text-sm font-medium text-zinc-400">Import Options</h4>
            {preview.library_tracks.total > 0 && (
              <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={options.import_favorites}
                  onChange={(e) => setOptions({ ...options, import_favorites: e.target.checked })}
                  className="rounded border-zinc-600 bg-zinc-700 text-green-500 focus:ring-green-500"
                />
                Import saved tracks as Spotify favorites
              </label>
            )}
            {preview.playlists.total > 0 && (
              <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={options.import_playlists}
                  onChange={(e) => setOptions({ ...options, import_playlists: e.target.checked })}
                  className="rounded border-zinc-600 bg-zinc-700 text-green-500 focus:ring-green-500"
                />
                Import playlists (matched tracks only)
              </label>
            )}
            <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
              <input
                type="checkbox"
                checked={options.favorite_matched}
                onChange={(e) => setOptions({ ...options, favorite_matched: e.target.checked })}
                className="rounded border-zinc-600 bg-zinc-700 text-green-500 focus:ring-green-500"
              />
              Favorite matched tracks in local library
            </label>
          </div>

          {/* Action buttons */}
          <div className="flex gap-2">
            <button
              onClick={handleExecute}
              disabled={importing}
              className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded-lg text-sm transition-colors disabled:opacity-50"
            >
              {importing ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <CheckCircle className="w-4 h-4" />
              )}
              {importing ? 'Importing...' : 'Import'}
            </button>
            <button
              onClick={handleReset}
              disabled={importing}
              className="px-4 py-2 bg-zinc-700 hover:bg-zinc-600 text-white rounded-lg text-sm transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="mt-4 space-y-3">
          <div className="flex items-center gap-2">
            <CheckCircle className="w-5 h-5 text-green-500" />
            <span className="font-medium text-white">Import Complete</span>
          </div>

          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="bg-zinc-900/50 rounded-lg p-3">
              <div className="text-lg font-bold text-green-400">{result.favorites_imported}</div>
              <div className="text-xs text-zinc-500">Favorites</div>
            </div>
            <div className="bg-zinc-900/50 rounded-lg p-3">
              <div className="text-lg font-bold text-blue-400">{result.playlists_created}</div>
              <div className="text-xs text-zinc-500">Playlists</div>
            </div>
            <div className="bg-zinc-900/50 rounded-lg p-3">
              <div className="text-lg font-bold text-amber-400">{result.tracks_favorited}</div>
              <div className="text-xs text-zinc-500">Favorited</div>
            </div>
          </div>

          {result.errors.length > 0 && (
            <div className="p-3 bg-red-900/20 border border-red-800 rounded-lg">
              <p className="text-sm text-red-400 font-medium mb-1">Errors:</p>
              {result.errors.map((err, i) => (
                <p key={i} className="text-xs text-red-300">{err}</p>
              ))}
            </div>
          )}

          <button
            onClick={handleReset}
            className="px-4 py-2 bg-zinc-700 hover:bg-zinc-600 text-white rounded-lg text-sm transition-colors"
          >
            Import Another
          </button>
        </div>
      )}
    </div>
  );
}
