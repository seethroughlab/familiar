/**
 * Offline storage settings component.
 */
import { useState, useEffect } from 'react';
import {
  HardDrive,
  Trash2,
  RefreshCw,
  Loader2,
  WifiOff,
  Cloud,
  CheckCircle,
  ListMusic,
  Zap,
  Heart,
} from 'lucide-react';
import * as libraryCache from '../../services/libraryCache';
import * as playlistCache from '../../services/playlistCache';
import * as syncService from '../../services/syncService';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { OfflineTracksPanel } from './OfflineTracksPanel';
import { StorageQuotaDisplay } from './StorageQuotaDisplay';
import { showWarning, showSuccess, showError } from '../../stores/toastStore';

import { createLogger } from '../../utils/logger';

const log = createLogger('OfflineSettings');

export function OfflineSettings() {
  const { isOnline, isOffline } = useOfflineStatus();

  const [cacheInfo, setCacheInfo] = useState<{
    count: number;
    lastCached: Date | null;
  } | null>(null);

  const [playlistCacheInfo, setPlaylistCacheInfo] = useState<{
    playlists: { count: number; lastCached: Date | null };
    smartPlaylists: { count: number; lastCached: Date | null };
    favorites: { count: number; lastCached: Date | null };
  } | null>(null);

  const [pendingCount, setPendingCount] = useState<number>(0);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [isLoading, setIsLoading] = useState<{
    cacheLibrary?: boolean;
    clearCache?: boolean;
    syncPending?: boolean;
    clearPlaylistCache?: boolean;
  }>({});

  const loadStats = async () => {
    try {
      const [cache, playlistStats, pending] = await Promise.all([
        libraryCache.getCacheInfo(),
        playlistCache.getAllCacheStats(),
        syncService.getPendingCount(),
      ]);
      setCacheInfo(cache);
      setPlaylistCacheInfo(playlistStats);
      setPendingCount(pending);
    } catch (error) {
      log.error('Failed to load offline stats:', error);
      showError('Failed to load offline storage info');
    }
  };

  useEffect(() => {
    loadStats();
  }, []);

  const handleCacheLibrary = async () => {
    setIsLoading((prev) => ({ ...prev, cacheLibrary: true }));
    try {
      await libraryCache.cacheLibrary();
      await loadStats();
    } catch (error) {
      log.error('Failed to cache library:', error);
      showError('Failed to cache library for offline use');
    } finally {
      setIsLoading((prev) => ({ ...prev, cacheLibrary: false }));
    }
  };

  const handleClearCache = async () => {
    if (!confirm('Clear the library cache? You can re-cache anytime.')) {
      return;
    }
    setIsLoading((prev) => ({ ...prev, clearCache: true }));
    try {
      await libraryCache.clearLibraryCache();
      await loadStats();
    } catch (error) {
      log.error('Failed to clear cache:', error);
      showError('Failed to clear library cache');
    } finally {
      setIsLoading((prev) => ({ ...prev, clearCache: false }));
    }
  };

  const handleClearPlaylistCaches = async () => {
    if (!confirm('Clear all cached playlists and favorites? You can re-cache by viewing them.')) {
      return;
    }
    setIsLoading((prev) => ({ ...prev, clearPlaylistCache: true }));
    try {
      await playlistCache.clearAllPlaylistCaches();
      await loadStats();
    } catch (error) {
      log.error('Failed to clear playlist caches:', error);
      showError('Failed to clear playlist caches');
    } finally {
      setIsLoading((prev) => ({ ...prev, clearPlaylistCache: false }));
    }
  };

  const handleSyncPending = async () => {
    if (!isOnline) {
      showWarning('Cannot sync while offline');
      return;
    }
    setIsLoading((prev) => ({ ...prev, syncPending: true }));
    try {
      const result = await syncService.processPendingActions();
      await loadStats();
      if (result.processed > 0 || result.failed > 0) {
        if (result.failed > 0) {
          showWarning(`Synced ${result.processed} actions, ${result.failed} failed`);
        } else if (result.processed > 0) {
          showSuccess(`Synced ${result.processed} actions`);
        }
      }
    } catch (error) {
      log.error('Failed to sync pending actions:', error);
      showError('Failed to sync pending actions');
    } finally {
      setIsLoading((prev) => ({ ...prev, syncPending: false }));
    }
  };

  return (
    <div className="bg-zinc-800/50 rounded-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <HardDrive className="w-5 h-5 text-purple-400" />
          <div>
            <h4 className="font-medium text-white">Offline Storage</h4>
            <p className="text-xs text-zinc-400">
              Download tracks for offline playback
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isOnline ? (
            <div className="flex items-center gap-1.5 text-green-400 text-xs">
              <Cloud className="w-4 h-4" />
              <span>Online</span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-amber-400 text-xs">
              <WifiOff className="w-4 h-4" />
              <span>Offline</span>
            </div>
          )}
        </div>
      </div>

      <div className="space-y-4">
        {/* Storage quota */}
        <div className="py-2 border-t border-zinc-700">
          <StorageQuotaDisplay refreshTrigger={refreshTrigger} />
        </div>

        {/* Downloaded tracks panel */}
        <div className="py-2 border-t border-zinc-700">
          <OfflineTracksPanel
            onTracksChanged={() => {
              loadStats();
              setRefreshTrigger((t) => t + 1);
            }}
          />
        </div>

        {/* Library cache */}
        <div className="flex items-center justify-between py-2 border-t border-zinc-700">
          <div className="flex items-center gap-2">
            <HardDrive className="w-4 h-4 text-zinc-400" />
            <span className="text-sm text-zinc-300">Library cache</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-zinc-400">
              {cacheInfo ? (
                cacheInfo.count > 0 ? (
                  <>
                    {cacheInfo.count} tracks
                    {cacheInfo.lastCached && (
                      <span className="text-xs ml-1">
                        (cached {formatRelativeTime(cacheInfo.lastCached)})
                      </span>
                    )}
                  </>
                ) : (
                  'Not cached'
                )
              ) : (
                '...'
              )}
            </span>
            <button
              onClick={handleCacheLibrary}
              disabled={isLoading.cacheLibrary || isOffline}
              className="p-1.5 text-blue-400 hover:text-blue-300 hover:bg-blue-400/10 rounded transition-colors disabled:opacity-50"
              title="Refresh library cache"
            >
              {isLoading.cacheLibrary ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4" />
              )}
            </button>
            {cacheInfo && cacheInfo.count > 0 && (
              <button
                onClick={handleClearCache}
                disabled={isLoading.clearCache}
                className="p-1.5 text-red-400 hover:text-red-300 hover:bg-red-400/10 rounded transition-colors disabled:opacity-50"
                title="Clear library cache"
              >
                {isLoading.clearCache ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Trash2 className="w-4 h-4" />
                )}
              </button>
            )}
          </div>
        </div>

        {/* Playlist cache status */}
        {playlistCacheInfo && (playlistCacheInfo.playlists.count > 0 || playlistCacheInfo.smartPlaylists.count > 0 || playlistCacheInfo.favorites.count > 0) && (
          <div className="py-2 border-t border-zinc-700 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm text-zinc-300 font-medium">Cached Playlists</span>
              <button
                onClick={handleClearPlaylistCaches}
                disabled={isLoading.clearPlaylistCache}
                className="p-1.5 text-red-400 hover:text-red-300 hover:bg-red-400/10 rounded transition-colors disabled:opacity-50"
                title="Clear all playlist caches"
              >
                {isLoading.clearPlaylistCache ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Trash2 className="w-4 h-4" />
                )}
              </button>
            </div>

            {playlistCacheInfo.playlists.count > 0 && (
              <div className="flex items-center justify-between text-sm text-zinc-400 pl-2">
                <div className="flex items-center gap-2">
                  <ListMusic className="w-3.5 h-3.5" />
                  <span>AI Playlists</span>
                </div>
                <span>
                  {playlistCacheInfo.playlists.count} cached
                  {playlistCacheInfo.playlists.lastCached && (
                    <span className="text-xs ml-1">
                      ({formatRelativeTime(playlistCacheInfo.playlists.lastCached)})
                    </span>
                  )}
                </span>
              </div>
            )}

            {playlistCacheInfo.smartPlaylists.count > 0 && (
              <div className="flex items-center justify-between text-sm text-zinc-400 pl-2">
                <div className="flex items-center gap-2">
                  <Zap className="w-3.5 h-3.5" />
                  <span>Smart Playlists</span>
                </div>
                <span>
                  {playlistCacheInfo.smartPlaylists.count} cached
                  {playlistCacheInfo.smartPlaylists.lastCached && (
                    <span className="text-xs ml-1">
                      ({formatRelativeTime(playlistCacheInfo.smartPlaylists.lastCached)})
                    </span>
                  )}
                </span>
              </div>
            )}

            {playlistCacheInfo.favorites.count > 0 && (
              <div className="flex items-center justify-between text-sm text-zinc-400 pl-2">
                <div className="flex items-center gap-2">
                  <Heart className="w-3.5 h-3.5" />
                  <span>Favorites</span>
                </div>
                <span>
                  {playlistCacheInfo.favorites.count} profile{playlistCacheInfo.favorites.count !== 1 ? 's' : ''} cached
                </span>
              </div>
            )}
          </div>
        )}

        {/* Pending sync actions */}
        <div className="flex items-center justify-between py-2 border-t border-zinc-700">
          <div className="flex items-center gap-2">
            <Cloud className="w-4 h-4 text-zinc-400" />
            <span className="text-sm text-zinc-300">Pending sync</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-zinc-400">
              {pendingCount > 0 ? `${pendingCount} actions` : 'All synced'}
            </span>
            {pendingCount > 0 ? (
              <button
                onClick={handleSyncPending}
                disabled={isLoading.syncPending || isOffline}
                className="p-1.5 text-green-400 hover:text-green-300 hover:bg-green-400/10 rounded transition-colors disabled:opacity-50"
                title="Sync now"
              >
                {isLoading.syncPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <RefreshCw className="w-4 h-4" />
                )}
              </button>
            ) : (
              <CheckCircle className="w-4 h-4 text-green-500" />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function formatRelativeTime(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}
