/**
 * Hook for managing offline album download state.
 * Uses the global download store for background downloads.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  removeOfflineTrack,
  getOfflineTrackIds,
} from '../services/offlineService';
import { useDownloadStore, getAlbumJobId } from '../stores/downloadStore';

interface AlbumTrack {
  id: string;
}

interface UseOfflineAlbumOptions {
  artist: string;
  album: string;
}

interface UseOfflineAlbumResult {
  /** Number of tracks already downloaded */
  offlineCount: number;
  /** Total number of tracks in the album */
  totalCount: number;
  /** Whether all tracks are downloaded */
  isFullyOffline: boolean;
  /** Whether some but not all tracks are downloaded */
  isPartiallyOffline: boolean;
  /** Whether a download is in progress */
  isDownloading: boolean;
  /** Current track being downloaded (1-indexed) */
  currentTrack: number;
  /** Progress of current track download (0-100) */
  currentTrackProgress: number;
  /** Overall album download progress (0-100) */
  overallProgress: number;
  /** Any error that occurred */
  error: string | null;
  /** Download all tracks that aren't already offline */
  download: () => Promise<void>;
  /** Remove all offline tracks for this album */
  remove: () => Promise<void>;
}

/**
 * Hook to manage offline status for an entire album.
 * Uses global download store for background downloads.
 */
export function useOfflineAlbum(
  tracks: AlbumTrack[],
  options?: UseOfflineAlbumOptions
): UseOfflineAlbumResult {
  const [offlineIds, setOfflineIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const trackIds = useMemo(() => tracks.map((t) => t.id), [tracks]);

  // Get download job from global store
  const { jobs, startDownload } = useDownloadStore();
  const jobId = options ? getAlbumJobId(options.artist, options.album) : null;
  const downloadJob = jobId ? jobs.get(jobId) : undefined;

  // Derive download state from job
  const isDownloading =
    downloadJob?.status === 'downloading' || downloadJob?.status === 'queued';
  const currentTrack = downloadJob
    ? downloadJob.completedIds.length + (downloadJob.currentProgress > 0 ? 1 : 0)
    : 0;
  const currentTrackProgress = downloadJob?.currentProgress ?? 0;
  const overallProgress =
    downloadJob && downloadJob.trackIds.length > 0
      ? Math.round(
          (downloadJob.completedIds.length / downloadJob.trackIds.length) * 100
        )
      : 0;

  // Check initial offline status for all tracks
  useEffect(() => {
    let mounted = true;

    async function checkOfflineStatus() {
      const allOfflineIds = await getOfflineTrackIds();
      const offlineSet = new Set(allOfflineIds);

      if (mounted) {
        // Only keep IDs that are in this album
        const albumOfflineIds = new Set(
          trackIds.filter((id) => offlineSet.has(id))
        );
        setOfflineIds(albumOfflineIds);
      }
    }

    checkOfflineStatus();

    return () => {
      mounted = false;
    };
  }, [trackIds]);

  // Update offline IDs when download completes
  useEffect(() => {
    if (downloadJob?.status === 'completed' || downloadJob?.status === 'failed') {
      getOfflineTrackIds().then((ids) => {
        const offlineSet = new Set(ids);
        const albumOfflineIds = new Set(
          trackIds.filter((id) => offlineSet.has(id))
        );
        setOfflineIds(albumOfflineIds);
      });

      if (downloadJob.error) {
        setError(downloadJob.error);
      }
    }
  }, [downloadJob?.status, downloadJob?.error, trackIds]);

  const offlineCount = offlineIds.size;
  const totalCount = tracks.length;
  const isFullyOffline = totalCount > 0 && offlineCount === totalCount;
  const isPartiallyOffline = offlineCount > 0 && offlineCount < totalCount;

  const download = useCallback(async () => {
    if (isDownloading || isFullyOffline || tracks.length === 0 || !jobId || !options) return;

    setError(null);

    // Only download tracks that aren't already offline
    const tracksToDownload = trackIds.filter((id) => !offlineIds.has(id));

    if (tracksToDownload.length === 0) {
      return;
    }

    // Start download via global store
    startDownload(
      jobId,
      'album',
      `${options.artist} - ${options.album}`,
      tracksToDownload
    );
  }, [isDownloading, isFullyOffline, tracks.length, trackIds, offlineIds, jobId, options, startDownload]);

  const remove = useCallback(async () => {
    if (offlineCount === 0) return;

    try {
      // Remove all tracks that are offline for this album
      const tracksToRemove = trackIds.filter((id) => offlineIds.has(id));

      for (const trackId of tracksToRemove) {
        await removeOfflineTrack(trackId);
      }

      setOfflineIds(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Remove failed');
    }
  }, [trackIds, offlineIds, offlineCount]);

  return {
    offlineCount,
    totalCount,
    isFullyOffline,
    isPartiallyOffline,
    isDownloading,
    currentTrack,
    currentTrackProgress,
    overallProgress,
    error,
    download,
    remove,
  };
}
