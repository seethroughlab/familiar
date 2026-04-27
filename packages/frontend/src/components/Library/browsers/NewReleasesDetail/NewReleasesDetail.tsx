/**
 * NewReleasesDetail — full grid of new releases at /library/discover/new-releases.
 *
 * Mirrors the original (shelved) NewReleasesDetail.tsx but uses the shared
 * ExternalAlbumCard and the post-Pass-1 backend API. Features:
 *   - Infinite scroll (50/page)
 *   - Search filter (client-side)
 *   - Toggle: include dismissed / include owned
 *   - "Run check now" button + 2s progress polling while running
 *   - Optimistic dismiss
 */
import { useState, useMemo, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import {
  ArrowLeft,
  Disc3,
  Eye,
  EyeOff,
  Loader2,
  RefreshCw,
  Search,
  X,
} from 'lucide-react';
import {
  newReleasesApi,
  externalAlbumsApi,
  type NewReleasesListResponse,
  type ExternalAlbum,
} from '../../../../api/discovery';
import { queryKeys } from '../../../../api/queryKeys';
import { showError, showSuccess } from '../../../../stores/toastStore';
import { ExternalAlbumCard } from '../../../Discovery/ExternalAlbumCard';

const PAGE_SIZE = 50;

function formatContextLabel(releaseDate: string | null): string {
  if (!releaseDate) return 'NEW RELEASE';
  try {
    const d = new Date(releaseDate);
    if (Number.isNaN(d.valueOf())) return 'NEW RELEASE';
    const month = d.toLocaleString('default', { month: 'short', timeZone: 'UTC' });
    return `NEW RELEASE · ${month} ${d.getUTCFullYear()}`;
  } catch {
    return 'NEW RELEASE';
  }
}

export default function NewReleasesDetail() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [search, setSearch] = useState('');
  const [includeDismissed, setIncludeDismissed] = useState(false);
  const [includeOwned, setIncludeOwned] = useState(false);
  const [isCheckTriggered, setIsCheckTriggered] = useState(false);

  const baseParams = useMemo(
    () => ({
      include_dismissed: includeDismissed,
      include_owned: includeOwned,
    }),
    [includeDismissed, includeOwned],
  );

  // Status — polls while running
  const statusQuery = useQuery({
    queryKey: queryKeys.newReleases.status,
    queryFn: () => newReleasesApi.getStatus(),
    refetchInterval: (query) => {
      const data = query.state.data;
      const running = data?.progress?.status === 'running';
      return running || isCheckTriggered ? 2000 : false;
    },
    staleTime: 30_000,
  });

  // Reset check-triggered flag and refresh list when check completes
  const progressStatus = statusQuery.data?.progress?.status;
  useEffect(() => {
    if (
      isCheckTriggered &&
      (progressStatus === 'completed' || progressStatus === 'error')
    ) {
      setIsCheckTriggered(false);
      queryClient.invalidateQueries({ queryKey: queryKeys.newReleases.all });
      if (progressStatus === 'completed') {
        showSuccess('New releases check complete');
      }
    }
  }, [isCheckTriggered, progressStatus, queryClient]);

  // Infinite-scroll list
  const listQuery = useInfiniteQuery({
    queryKey: ['new-releases', 'detail', baseParams] as const,
    queryFn: ({ pageParam = 0 }) =>
      newReleasesApi.list({
        ...baseParams,
        limit: PAGE_SIZE,
        offset: pageParam,
      }),
    getNextPageParam: (lastPage: NewReleasesListResponse) => {
      const fetchedSoFar = lastPage.offset + lastPage.releases.length;
      return fetchedSoFar < lastPage.total ? fetchedSoFar : undefined;
    },
    initialPageParam: 0,
    staleTime: 60_000,
  });

  // Sentinel for infinite scroll
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const node = sentinelRef.current;
    if (!node) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting) && listQuery.hasNextPage && !listQuery.isFetchingNextPage) {
        listQuery.fetchNextPage();
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [listQuery]);

  const allReleases: ExternalAlbum[] = useMemo(
    () => (listQuery.data?.pages ?? []).flatMap((p) => p.releases),
    [listQuery.data],
  );
  const filteredReleases = useMemo(() => {
    if (!search.trim()) return allReleases;
    const q = search.trim().toLowerCase();
    return allReleases.filter(
      (r) =>
        r.artist_name.toLowerCase().includes(q) ||
        r.release_name.toLowerCase().includes(q),
    );
  }, [allReleases, search]);

  const checkMutation = useMutation({
    mutationFn: () => newReleasesApi.checkBatch({ batch_size: 75 }),
    onSuccess: () => {
      setIsCheckTriggered(true);
      showSuccess('Checking for new releases...');
      queryClient.invalidateQueries({ queryKey: queryKeys.newReleases.status });
    },
    onError: () => showError('Failed to start check. Try again later.'),
  });

  const dismissMutation = useMutation({
    mutationFn: (id: string) => externalAlbumsApi.dismiss(id),
    onMutate: async (id) => {
      const queryKey = ['new-releases', 'detail', baseParams] as const;
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData(queryKey);
      queryClient.setQueryData(queryKey, (old: typeof listQuery.data) => {
        if (!old) return old;
        return {
          ...old,
          pages: old.pages.map((p) => ({
            ...p,
            releases: p.releases.filter((r) => r.id !== id),
          })),
        };
      });
      return { previous };
    },
    onError: (_err, _id, ctx) => {
      const queryKey = ['new-releases', 'detail', baseParams] as const;
      if (ctx?.previous) queryClient.setQueryData(queryKey, ctx.previous);
      showError('Failed to dismiss. Try again.');
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.newReleases.all });
    },
  });

  const isRunning = progressStatus === 'running' || isCheckTriggered;
  const progressMsg = statusQuery.data?.progress?.message;
  const lastCheckAt = statusQuery.data?.last_check_at
    ? new Date(statusQuery.data.last_check_at).toLocaleString()
    : null;

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-3 border-b border-zinc-800 bg-zinc-950/50 backdrop-blur-sm">
        <div className="flex items-center gap-3 mb-3">
          <button
            type="button"
            onClick={() => navigate('/library/discover')}
            className="p-1.5 rounded-md hover:bg-zinc-800 text-zinc-400 hover:text-zinc-100 transition-colors"
            aria-label="Back to Discover"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <Disc3 className="w-5 h-5 text-zinc-400" />
          <h1 className="text-lg font-semibold text-zinc-100">New Releases</h1>
          {statusQuery.data && (
            <span className="text-xs text-zinc-500 ml-auto">
              {lastCheckAt ? `Last checked: ${lastCheckAt}` : 'Never checked'}
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Search */}
          <div className="relative flex-1 min-w-[200px] max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter by artist or release..."
              className="w-full pl-9 pr-9 py-1.5 text-sm rounded-md bg-zinc-900 border border-zinc-800 text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-600"
            />
            {search && (
              <button
                type="button"
                onClick={() => setSearch('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded text-zinc-500 hover:text-zinc-200"
                aria-label="Clear search"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </div>

          {/* Toggles */}
          <button
            type="button"
            onClick={() => setIncludeDismissed((v) => !v)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md transition-colors ${
              includeDismissed
                ? 'bg-zinc-700 text-zinc-100'
                : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200 border border-zinc-800'
            }`}
          >
            {includeDismissed ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
            {includeDismissed ? 'Showing dismissed' : 'Show dismissed'}
          </button>
          <button
            type="button"
            onClick={() => setIncludeOwned((v) => !v)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md transition-colors ${
              includeOwned
                ? 'bg-zinc-700 text-zinc-100'
                : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200 border border-zinc-800'
            }`}
          >
            {includeOwned ? 'Showing owned' : 'Show owned'}
          </button>

          {/* Run check now */}
          <button
            type="button"
            disabled={isRunning || checkMutation.isPending}
            onClick={() => checkMutation.mutate()}
            className="ml-auto flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 disabled:cursor-not-allowed text-zinc-100 transition-colors"
          >
            {isRunning ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Checking...
              </>
            ) : (
              <>
                <RefreshCw className="w-4 h-4" />
                Run check now
              </>
            )}
          </button>
        </div>

        {/* Progress line */}
        {isRunning && (
          <div className="mt-2 text-xs text-zinc-500 flex items-center gap-2">
            <Loader2 className="w-3 h-3 animate-spin" />
            {progressMsg || 'Checking artists for new releases...'}
          </div>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {listQuery.isLoading ? (
          <div className="flex items-center justify-center h-32 text-zinc-500">
            <Loader2 className="w-6 h-6 animate-spin" />
          </div>
        ) : filteredReleases.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-zinc-500 gap-2">
            {search ? (
              <p className="text-sm">No releases match "{search}".</p>
            ) : (
              <>
                <p className="text-sm text-zinc-300">No new releases cached yet.</p>
                <p className="text-xs">Run a check to discover releases from your artists.</p>
              </>
            )}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
              {filteredReleases.map((album) => (
                <ExternalAlbumCard
                  key={album.id}
                  album={album}
                  contextLabel={formatContextLabel(album.release_date)}
                  onDismiss={(id) => dismissMutation.mutate(id)}
                  layout="grid"
                />
              ))}
            </div>
            {/* Sentinel for infinite scroll */}
            <div ref={sentinelRef} className="h-12 flex items-center justify-center">
              {listQuery.isFetchingNextPage && (
                <Loader2 className="w-5 h-5 animate-spin text-zinc-500" />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
