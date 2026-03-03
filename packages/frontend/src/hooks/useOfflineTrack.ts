/**
 * Hook for managing offline track download state.
 */
import { useState, useEffect, useCallback } from 'react';
import {
  isTrackOffline,
  downloadTrackForOffline,
  removeOfflineTrack,
} from '../services/offlineService';

interface UseOfflineTrackResult {
  isOffline: boolean;
  isDownloading: boolean;
  downloadProgress: number;
  error: string | null;
  download: () => Promise<void>;
  remove: () => Promise<void>;
}

/**
 * Hook to manage offline status for a single track.
 */
export function useOfflineTrack(trackId: string): UseOfflineTrackResult {
  const [isOffline, setIsOffline] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // Check initial offline status
  useEffect(() => {
    let mounted = true;

    isTrackOffline(trackId).then((offline) => {
      if (mounted) setIsOffline(offline);
    });

    return () => {
      mounted = false;
    };
  }, [trackId]);

  const download = useCallback(async () => {
    if (isOffline || isDownloading) return;

    setIsDownloading(true);
    setDownloadProgress(0);
    setError(null);

    try {
      await downloadTrackForOffline(trackId, (progress) => {
        setDownloadProgress(progress.percentage);
      });
      setIsOffline(true);
      setDownloadProgress(100);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed');
    } finally {
      setIsDownloading(false);
    }
  }, [trackId, isOffline, isDownloading]);

  const remove = useCallback(async () => {
    if (!isOffline) return;

    try {
      await removeOfflineTrack(trackId);
      setIsOffline(false);
      setDownloadProgress(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Remove failed');
    }
  }, [trackId, isOffline]);

  return {
    isOffline,
    isDownloading,
    downloadProgress,
    error,
    download,
    remove,
  };
}

/**
 * Hook to get offline status for multiple tracks at once.
 */
export function useOfflineTrackIds(): {
  offlineIds: Set<string>;
  refresh: () => Promise<void>;
} {
  const [offlineIds, setOfflineIds] = useState<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    const { getOfflineTrackIds } = await import('../services/offlineService');
    const ids = await getOfflineTrackIds();
    setOfflineIds(new Set(ids));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { offlineIds, refresh };
}
