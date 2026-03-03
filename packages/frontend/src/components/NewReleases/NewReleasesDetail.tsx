import { useState, useMemo, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Disc3,
  RefreshCw,
  Search,
  X,
  Eye,
  EyeOff,
  Loader2,
} from 'lucide-react';
import { newReleasesApi, playlistsApi, type NewRelease } from '../../api';
import { NewReleaseCard } from './NewReleaseCard';
import { showError, showSuccess } from '../../stores/toastStore';
import { useIntersectionObserver } from '../../hooks/useIntersectionObserver';

export function NewReleasesDetail() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [searchFilter, setSearchFilter] = useState('');
  const [showDismissed, setShowDismissed] = useState(false);
  const [showOwned, setShowOwned] = useState(false);

  // Status query — polls every 2s while a check is running
  const { data: status } = useQuery({
    queryKey: ['new-releases-status'],
    queryFn: () => newReleasesApi.getStatus(),
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.progress?.status === 'running' ? 2000 : false;
    },
    staleTime: 30_000,
  });

  const isCheckRunning = status?.progress?.status === 'running';
  const progressPercent = status?.progress
    ? Math.round(
        (status.progress.artists_checked / Math.max(status.progress.artists_total, 1)) * 100,
      )
    : 0;

  // Releases — infinite query, 50 per page
  const PAGE_SIZE = 50;
  const {
    data: releasesData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    refetch: refetchReleases,
  } = useInfiniteQuery({
    queryKey: ['new-releases', showDismissed, showOwned],
    queryFn: ({ pageParam = 0 }) =>
      newReleasesApi.list({
        limit: PAGE_SIZE,
        offset: pageParam,
        include_dismissed: showDismissed,
        include_owned: showOwned,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => {
      const nextOffset = lastPage.offset + lastPage.limit;
      return nextOffset < lastPage.total ? nextOffset : undefined;
    },
    staleTime: 60_000,
  });

  // Refetch releases when a check completes
  const [wasRunning, setWasRunning] = useState(false);
  useEffect(() => {
    if (isCheckRunning) {
      setWasRunning(true);
    } else if (wasRunning) {
      setWasRunning(false);
      refetchReleases();
      queryClient.invalidateQueries({ queryKey: ['new-releases-status'] });
    }
  }, [isCheckRunning, wasRunning, refetchReleases, queryClient]);

  // Flatten pages into a single list
  const allReleases = useMemo(
    () => releasesData?.pages.flatMap((p) => p.releases) ?? [],
    [releasesData],
  );
  const totalCount = releasesData?.pages[0]?.total ?? 0;

  // Client-side search filter
  const filteredReleases = useMemo(() => {
    if (!searchFilter) return allReleases;
    const q = searchFilter.toLowerCase();
    return allReleases.filter(
      (r) =>
        r.artist_name.toLowerCase().includes(q) ||
        r.release_name.toLowerCase().includes(q),
    );
  }, [allReleases, searchFilter]);

  // Infinite scroll trigger
  const loadMoreRef = useIntersectionObserver({
    onIntersect: () => fetchNextPage(),
    enabled: !!hasNextPage && !isFetchingNextPage,
  });

  const handleCheck = async () => {
    try {
      await newReleasesApi.check({ days_back: 90 });
      queryClient.invalidateQueries({ queryKey: ['new-releases-status'] });
    } catch {
      showError('Failed to start check');
    }
  };

  const handleDismiss = useCallback(
    async (releaseId: string) => {
      try {
        await newReleasesApi.dismiss(releaseId);
        // Optimistically remove from cache
        queryClient.setQueryData(
          ['new-releases', showDismissed, showOwned],
          (old: typeof releasesData) => {
            if (!old) return old;
            return {
              ...old,
              pages: old.pages.map((page) => ({
                ...page,
                releases: page.releases.filter((r: NewRelease) => r.id !== releaseId),
                total: page.total - 1,
              })),
            };
          },
        );
        // Update sidebar count
        queryClient.invalidateQueries({ queryKey: ['new-releases-status'] });
      } catch {
        showError('Failed to dismiss release');
      }
    },
    [queryClient, showDismissed, showOwned, releasesData],
  );

  const handleAddToWishlist = useCallback(async (release: NewRelease) => {
    try {
      if (release.source === 'spotify') {
        const result = await playlistsApi.addReleaseToWishlist(release.id);
        if (result.tracks_added > 0) {
          showSuccess(`Added ${result.tracks_added} track${result.tracks_added !== 1 ? 's' : ''} from "${release.release_name}" to Wishlist`);
        } else {
          showSuccess(`"${release.release_name}" already in Wishlist`);
        }
      } else {
        await playlistsApi.addToWishlist({
          title: release.release_name,
          artist: release.artist_name,
          album: release.release_name,
          external_data: {
            artwork_url: release.artwork_url,
            external_url: release.external_url,
            source: release.source,
            release_type: release.release_type,
          },
        });
        showSuccess(`Added "${release.release_name}" to Wishlist`);
      }
    } catch {
      showError('Failed to add to wishlist');
      throw new Error('Failed to add to wishlist');
    }
  }, []);

  const formatLastChecked = (dateStr: string | null) => {
    if (!dateStr) return 'Never checked';
    const date = new Date(dateStr);
    return `Last checked ${date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })}`;
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="space-y-4 p-4">
        {/* Header */}
        <div className="flex items-start gap-4">
          <button
            onClick={() => navigate(-1)}
            className="p-2 hover:bg-zinc-800 rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>

          <div className="flex-1">
            <div className="flex items-center gap-2">
              <Disc3 className="w-5 h-5 text-purple-500" />
              <h2 className="text-xl font-bold">New Releases</h2>
            </div>
            <p className="text-sm text-zinc-500 mt-1">
              {totalCount > 0
                ? `${totalCount} release${totalCount !== 1 ? 's' : ''} from your artists`
                : 'New music from artists in your library'}
            </p>
          </div>

          <button
            onClick={handleCheck}
            disabled={isCheckRunning}
            className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-500 disabled:bg-purple-600/50 rounded-full text-sm font-medium transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${isCheckRunning ? 'animate-spin' : ''}`} />
            {isCheckRunning ? 'Checking...' : 'Check Now'}
          </button>
        </div>

        {/* Last checked + progress */}
        <div className="text-sm text-zinc-500">
          {formatLastChecked(status?.last_check_at ?? null)}
        </div>

        {isCheckRunning && status?.progress && (
          <div>
            <div className="flex items-center justify-between text-xs text-zinc-500 mb-1">
              <span>{status.progress.message}</span>
              <span>{progressPercent}%</span>
            </div>
            <div className="h-1.5 bg-zinc-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-purple-500 transition-all duration-300"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
            {status.progress.current_artist && (
              <p className="text-xs text-zinc-500 mt-1 truncate">
                Checking: {status.progress.current_artist}
              </p>
            )}
          </div>
        )}

        {/* Search + show dismissed toggle */}
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
            <input
              type="text"
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              placeholder="Search releases..."
              className="w-full pl-9 pr-8 py-2 bg-zinc-800 rounded-lg text-sm placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-600"
            />
            {searchFilter && (
              <button
                onClick={() => setSearchFilter('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 text-zinc-500 hover:text-zinc-300"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>

          <button
            onClick={() => setShowOwned(!showOwned)}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
              showOwned
                ? 'bg-zinc-700 text-zinc-200'
                : 'bg-zinc-800 text-zinc-500 hover:text-zinc-300'
            }`}
            title={showOwned ? 'Hide owned releases' : 'Show releases already in library'}
          >
            {showOwned ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
            <span className="hidden sm:inline">In Library</span>
          </button>

          <button
            onClick={() => setShowDismissed(!showDismissed)}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
              showDismissed
                ? 'bg-zinc-700 text-zinc-200'
                : 'bg-zinc-800 text-zinc-500 hover:text-zinc-300'
            }`}
            title={showDismissed ? 'Hide dismissed' : 'Show dismissed'}
          >
            {showDismissed ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
            <span className="hidden sm:inline">Dismissed</span>
          </button>
        </div>

        {/* Loading state */}
        {isLoading && (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
          </div>
        )}

        {/* Empty state */}
        {!isLoading && allReleases.length === 0 && (
          <div className="text-center py-12">
            <Disc3 className="w-12 h-12 text-zinc-600 mx-auto mb-3" />
            {status && status.total_releases_found > 0 && !showOwned ? (
              <>
                <p className="text-zinc-400">
                  {status.total_releases_found} release{status.total_releases_found !== 1 ? 's' : ''} found, but all are already in your library
                </p>
                <p className="text-xs text-zinc-500 mt-1">
                  Toggle "In Library" to see them
                </p>
              </>
            ) : (
              <>
                <p className="text-zinc-400">No new releases found</p>
                <p className="text-xs text-zinc-500 mt-1">
                  Click "Check Now" to search for new music from artists in your library
                </p>
              </>
            )}
          </div>
        )}

        {/* No search results */}
        {!isLoading && allReleases.length > 0 && filteredReleases.length === 0 && searchFilter && (
          <div className="text-center py-8 text-zinc-500">
            No releases matching "{searchFilter}"
          </div>
        )}

        {/* Releases grid */}
        {filteredReleases.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {filteredReleases.map((release) => (
              <NewReleaseCard
                key={release.id}
                release={release}
                onDismiss={handleDismiss}
                onAddToWishlist={handleAddToWishlist}
              />
            ))}
          </div>
        )}

        {/* Infinite scroll trigger */}
        {hasNextPage && (
          <div ref={loadMoreRef} className="flex items-center justify-center py-4">
            {isFetchingNextPage && (
              <Loader2 className="w-6 h-6 animate-spin text-zinc-500" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
