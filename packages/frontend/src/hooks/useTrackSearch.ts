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
 *
 * Pass `externalSearch` to use an externally-managed search value (e.g. URL params)
 * instead of internal state.
 */
export function useTrackSearch<T extends Searchable>(
  tracks: T[],
  offlineTrackIds?: Set<string>,
  externalSearch?: string,
) {
  const [internalSearch, setInternalSearch] = useState('');
  const searchFilter = externalSearch ?? internalSearch;
  const setSearchFilter = setInternalSearch;
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
