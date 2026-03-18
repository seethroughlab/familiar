import { useState, useMemo } from 'react';

interface Searchable {
  id: string;
  title?: string | null;
  artist?: string | null;
  album?: string | null;
}

/**
 * Search filter + downloaded-only toggle for track lists.
 * Replaces ~15 lines of duplicated state + useMemo in 5 detail pages.
 */
export function useTrackSearch<T extends Searchable>(
  tracks: T[],
  offlineTrackIds?: Set<string>,
) {
  const [searchFilter, setSearchFilter] = useState('');
  const [showDownloadedOnly, setShowDownloadedOnly] = useState(false);

  const filteredTracks = useMemo(() => {
    let result = tracks;
    if (showDownloadedOnly && offlineTrackIds) {
      result = result.filter(t => offlineTrackIds.has(t.id));
    }
    if (searchFilter) {
      const q = searchFilter.toLowerCase();
      result = result.filter(t =>
        t.title?.toLowerCase().includes(q) ||
        t.artist?.toLowerCase().includes(q) ||
        t.album?.toLowerCase().includes(q),
      );
    }
    return result;
  }, [tracks, showDownloadedOnly, offlineTrackIds, searchFilter]);

  return { searchFilter, setSearchFilter, showDownloadedOnly, setShowDownloadedOnly, filteredTracks };
}
