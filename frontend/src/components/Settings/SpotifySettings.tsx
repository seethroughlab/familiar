import { useState, useEffect, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { spotifyApi } from '../../api/client';
import type { SpotifyStatus } from '../../api/client';
import { Music2, RefreshCw, LogOut, ExternalLink, CheckCircle, XCircle, Loader2, AlertTriangle } from 'lucide-react';
import { MissingTracks } from '../Library/MissingTracks';

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
}

export function SpotifySettings() {
  const queryClient = useQueryClient();
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [favoriteMatched, setFavoriteMatched] = useState(true);

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
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-4">
            <div className={`p-3 rounded-lg ${status.connected ? 'bg-green-500/20' : 'bg-zinc-700'}`}>
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
                    disabled={syncMutation.isPending || isPolling}
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

        {/* Sync progress when running */}
        {isPolling && syncStatus?.progress && (
          <div className="mt-4 space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-zinc-400">
                {syncStatus.progress.phase === 'connecting' && 'Connecting to Spotify...'}
                {syncStatus.progress.phase === 'fetching' && 'Fetching tracks from Spotify...'}
                {syncStatus.progress.phase === 'matching' && 'Matching to local library...'}
                {syncStatus.progress.phase === 'complete' && 'Complete'}
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
    </div>
  );
}
