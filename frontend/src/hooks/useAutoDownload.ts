/**
 * Hook for auto-downloading new tracks in playlists/smart playlists.
 * Compares current track IDs against offline tracks and triggers download
 * for any missing tracks when auto-download is enabled.
 */
import { useEffect, useRef } from 'react';
import { useDownloadStore } from '../stores/downloadStore';
import { useOfflineStatus } from './useOfflineStatus';
import * as offlineService from '../services/offlineService';
import type { DownloadJob } from '../stores/downloadStore';

interface UseAutoDownloadOptions {
  enabled: boolean;
  jobId: string;
  jobType: DownloadJob['type'];
  jobName: string;
  trackIds: string[];
}

/**
 * Automatically downloads un-downloaded tracks when enabled.
 * Skips when offline. Uses downloadStore.startDownload which
 * already deduplicates jobs and filters already-downloaded tracks.
 */
export function useAutoDownload({
  enabled,
  jobId,
  jobType,
  jobName,
  trackIds,
}: UseAutoDownloadOptions) {
  const { isOffline } = useOfflineStatus();
  const startDownload = useDownloadStore((s) => s.startDownload);
  const prevTrackIdsRef = useRef<string[]>([]);

  useEffect(() => {
    if (!enabled || isOffline || trackIds.length === 0) return;

    // Skip if track IDs haven't changed
    const prevIds = prevTrackIdsRef.current;
    const idsChanged =
      prevIds.length !== trackIds.length ||
      trackIds.some((id, i) => id !== prevIds[i]);

    if (!idsChanged && prevIds.length > 0) return;
    prevTrackIdsRef.current = trackIds;

    // Check which tracks are not yet offline and download them
    let cancelled = false;
    (async () => {
      const offlineIds = new Set(await offlineService.getOfflineTrackIds());
      const missing = trackIds.filter((id) => !offlineIds.has(id));
      if (!cancelled && missing.length > 0) {
        startDownload(jobId, jobType, jobName, trackIds);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [enabled, isOffline, trackIds, jobId, jobType, jobName, startDownload]);
}
