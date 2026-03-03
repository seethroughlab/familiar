/**
 * Hook for getting downloaded/offline tracks with metadata.
 */
import { useState, useEffect, useCallback } from 'react';
import {
  getOfflineTracksWithInfo,
  getOfflineStorageUsage,
  formatBytes,
  type OfflineTrackInfo,
} from '../services/offlineService';
import { createLogger } from '../utils/logger';

const log = createLogger('DownloadedTracks');

interface UseDownloadedTracksResult {
  tracks: OfflineTrackInfo[];
  total: number;
  totalSize: number;
  totalSizeFormatted: string;
  isLoading: boolean;
  refresh: () => Promise<void>;
}

/**
 * Hook to get all downloaded tracks with their metadata.
 */
export function useDownloadedTracks(): UseDownloadedTracksResult {
  const [tracks, setTracks] = useState<OfflineTrackInfo[]>([]);
  const [totalSize, setTotalSize] = useState(0);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const [tracksInfo, storageInfo] = await Promise.all([
        getOfflineTracksWithInfo(),
        getOfflineStorageUsage(),
      ]);
      // Sort by cachedAt descending (most recent first)
      tracksInfo.sort((a, b) => b.cachedAt.getTime() - a.cachedAt.getTime());
      setTracks(tracksInfo);
      setTotalSize(storageInfo.sizeBytes);
    } catch (error) {
      log.error('Failed to load downloaded tracks:', error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return {
    tracks,
    total: tracks.length,
    totalSize,
    totalSizeFormatted: formatBytes(totalSize),
    isLoading,
    refresh,
  };
}
