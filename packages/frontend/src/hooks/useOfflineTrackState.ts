import { useState, useEffect } from 'react';
import * as offlineService from '../services/offlineService';

/**
 * Manages offline track ID hydration and refresh on download completion.
 * Replaces ~25 lines of duplicated state + effects in detail pages.
 */
export function useOfflineTrackState(opts?: { downloadJobStatus?: string }) {
  const [offlineTrackIds, setOfflineTrackIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    offlineService.getOfflineTrackIds().then(ids => setOfflineTrackIds(new Set(ids)));
  }, []);

  useEffect(() => {
    if (opts?.downloadJobStatus === 'completed' || opts?.downloadJobStatus === 'failed') {
      offlineService.getOfflineTrackIds().then(ids => setOfflineTrackIds(new Set(ids)));
    }
  }, [opts?.downloadJobStatus]);

  return { offlineTrackIds };
}
