/**
 * NewReleasesSection — "New releases from your artists" on the Discover page.
 *
 * Reads from /api/v1/new-releases. Empty state offers a "Run check now" CTA
 * (calls /new-releases/check/batch) since the daily APScheduler job runs at
 * 03:00 and new users would otherwise wait a day.
 *
 * Polls /new-releases/status every 2s while a check is running.
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Disc3, Loader2, RefreshCw, ChevronRight } from 'lucide-react';
import { newReleasesApi, externalAlbumsApi } from '../../../../api/discovery';
import { queryKeys } from '../../../../api/queryKeys';
import { STALE_TIME } from '../../../../api/queryDefaults';
import { showError, showSuccess } from '../../../../stores/toastStore';
import { ExternalAlbumCard } from '../../../Discovery/ExternalAlbumCard';

const SECTION_LIMIT = 12;

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

export function NewReleasesSection() {
  const queryClient = useQueryClient();
  const [isCheckTriggered, setIsCheckTriggered] = useState(false);

  const listParams = {
    limit: SECTION_LIMIT,
    offset: 0,
    include_dismissed: false,
    include_owned: false,
  };

  const listQuery = useQuery({
    queryKey: queryKeys.newReleases.list(listParams),
    queryFn: () => newReleasesApi.list(listParams),
    staleTime: STALE_TIME.LONG,
  });

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

  // When a check completes, reset the flag and refresh the list
  const progressStatus = statusQuery.data?.progress?.status;
  if (
    isCheckTriggered &&
    (progressStatus === 'completed' || progressStatus === 'error')
  ) {
    setIsCheckTriggered(false);
    queryClient.invalidateQueries({ queryKey: queryKeys.newReleases.all });
  }

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
      await queryClient.cancelQueries({ queryKey: queryKeys.newReleases.list(listParams) });
      const previous = queryClient.getQueryData(queryKeys.newReleases.list(listParams));
      queryClient.setQueryData(
        queryKeys.newReleases.list(listParams),
        (old: typeof listQuery.data) =>
          old
            ? { ...old, releases: old.releases.filter((r) => r.id !== id) }
            : old,
      );
      return { previous };
    },
    onError: (_err, _id, ctx) => {
      if (ctx?.previous) {
        queryClient.setQueryData(queryKeys.newReleases.list(listParams), ctx.previous);
      }
      showError('Failed to dismiss. Try again.');
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.newReleases.all });
    },
  });

  const releases = listQuery.data?.releases ?? [];
  const isRunning = progressStatus === 'running' || isCheckTriggered;

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Disc3 className="w-5 h-5 text-zinc-400" />
          <h2 className="text-lg font-semibold text-zinc-100">
            New releases from your artists
          </h2>
          {releases.length > 0 && (
            <span className="px-2 py-0.5 text-xs rounded-full bg-zinc-800 text-zinc-400">
              {listQuery.data?.total ?? releases.length}
            </span>
          )}
        </div>
        {releases.length > 0 && (
          <Link
            to="/library/discover/new-releases"
            className="flex items-center gap-1 text-sm text-zinc-400 hover:text-zinc-200 transition-colors"
          >
            See all
            <ChevronRight className="w-4 h-4" />
          </Link>
        )}
      </div>

      {listQuery.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-zinc-500 py-6">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading new releases...
        </div>
      ) : releases.length === 0 ? (
        <div className="rounded-lg border border-dashed border-zinc-800 bg-zinc-900/40 p-6 text-center">
          <p className="text-sm text-zinc-300 mb-1">
            No new releases cached yet.
          </p>
          <p className="text-xs text-zinc-500 mb-4">
            We check daily for new music from your artists. You can also run a check now.
          </p>
          <button
            type="button"
            disabled={isRunning || checkMutation.isPending}
            onClick={() => checkMutation.mutate()}
            className="inline-flex items-center gap-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2 text-sm text-zinc-100 transition-colors"
          >
            {isRunning ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Checking...
              </>
            ) : (
              <>
                <RefreshCw className="w-4 h-4" />
                Run a check now
              </>
            )}
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
          {releases.map((album) => (
            <ExternalAlbumCard
              key={album.id}
              album={album}
              contextLabel={formatContextLabel(album.release_date)}
              onDismiss={(id) => dismissMutation.mutate(id)}
              layout="grid"
            />
          ))}
        </div>
      )}

      {/* Inline progress pill while a check is running and we have stale data shown */}
      {isRunning && releases.length > 0 && (
        <div className="mt-3 flex items-center gap-2 text-xs text-zinc-500">
          <Loader2 className="w-3 h-3 animate-spin" />
          Checking artists for new releases...
          {statusQuery.data?.progress?.message && (
            <span>· {statusQuery.data.progress.message}</span>
          )}
        </div>
      )}
    </section>
  );
}
