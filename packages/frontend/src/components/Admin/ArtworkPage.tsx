/**
 * Cover art, and the albums that never got any.
 *
 * **A placeholder is not artwork, and this page exists to say so out loud.** When Last.fm and
 * MusicBrainz both come back empty, Familiar draws a cover itself. That is a good fallback — a grid
 * of blank squares is worse — but it is indistinguishable from real art everywhere else in the app,
 * which is how 661 albums came to be permanently stuck on one: both queue routes reported"artwork
 * exists" for a file Familiar had drawn, so the fetcher's own retry allowance was unreachable.
 *
 * The fix is in the server. This page is the bulk lever, because fixing the routes only makes
 * browsing self-healing — reaching every placeholder that way means scrolling past every album.
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Image, RefreshCw, Loader2 } from 'lucide-react';

import { libraryApi } from '../../api/library';
import { queryKeys } from '../../api/queryKeys';
import { offlineAwareRetry } from '../../api/queryDefaults';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { AdminPage, AdminSection } from './AdminPage';

export function ArtworkPage() {
  const { isOffline } = useOfflineStatus();
  const queryClient = useQueryClient();
  const [result, setResult] = useState<{ queued: number; skipped_recent: number } | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.library.artworkCoverage(),
    queryFn: () => libraryApi.getArtworkCoverage(),
    retry: offlineAwareRetry(isOffline),
  });

  const refetch = useMutation({
    mutationFn: () => libraryApi.refetchGeneratedArtwork(),
    onSuccess: (r) => {
      setResult(r);
      // The queue drains in the background, so the numbers above are stale the moment this
      // returns — but not yet changed. Invalidating asks once; it does not poll, because a
      // progress bar over a queue this page cannot see would be an invention.
      queryClient.invalidateQueries({ queryKey: queryKeys.library.artworkCoverage() });
    },
  });

  // Stated rather than served by the endpoint, because `generated` is deliberately a *subset* of
  // `with_artwork` — an album with a placeholder does have a file. Folding them together is what
  // would let "91% covered" describe a library where a quarter of the covers are drawn.
  const real = data ? data.with_artwork - data.generated : 0;

  return (
    <AdminPage title="Cover art" subtitle="What has real artwork, what has a placeholder, and what has none">
      <AdminSection title="Coverage">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Figure label="Real art" value={real} loading={isLoading} tone="text-emerald-400" />
          <Figure label="Placeholder" value={data?.generated} loading={isLoading} tone="text-amber-400" />
          <Figure label="No art at all" value={data?.without_artwork} loading={isLoading} tone="text-zinc-400" />
        </div>
        {data && data.total_albums > 0 && (
          <p className="text-sm text-zinc-400">
            {Math.round((real / data.total_albums) * 100)}% of {data.total_albums.toLocaleString()}{' '}
            albums have artwork fetched from Last.fm or MusicBrainz. The rest show a cover Familiar
            drew, or nothing.
          </p>
        )}
      </AdminSection>

      <AdminSection title="Re-fetch">
        <div className="bg-zinc-800/50 rounded-lg p-4 space-y-3">
          <p className="text-sm text-zinc-400">
            Asks Last.fm and MusicBrainz again for every album currently showing a placeholder. Art
            gets added to those services over time, and correcting an album's tags changes what
            Familiar asks for — so an album that had nothing last year may have a cover now.
          </p>
          <button
            onClick={() => refetch.mutate()}
            disabled={refetch.isPending || !data?.generated}
            className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white text-sm font-medium flex items-center gap-2"
          >
            {refetch.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
            {refetch.isPending ? 'Queueing…' : 'Re-fetch placeholder covers'}
          </button>

          <p className="text-xs text-zinc-500">
            Albums with real art are never touched. A placeholder is only retried once every 30
            days, so pressing this again tomorrow will queue nothing — that limit protects Last.fm
            and MusicBrainz from being asked daily about albums that genuinely have no cover.
          </p>

          {refetch.isError && (
            <p className="text-sm text-red-400">
              Could not queue:{' '}
              {refetch.error instanceof Error ? refetch.error.message : 'unknown error'}
            </p>
          )}

          {result && !refetch.isPending && (
            <p className="text-sm text-zinc-300">
              Queued {result.queued.toLocaleString()} album
              {result.queued === 1 ? '' : 's'}
              {result.skipped_recent > 0 &&
                `, and left ${result.skipped_recent.toLocaleString()} that were tried recently`}
              . They are fetched in the background — check back rather than waiting here.
              {result.queued === 0 && result.skipped_recent === 0 && (
                <> Nothing was queued, which means no album is currently on a placeholder.</>
              )}
            </p>
          )}
        </div>
      </AdminSection>
    </AdminPage>
  );
}

function Figure({
  label,
  value,
  loading,
  tone,
}: {
  label: string;
  value: number | undefined;
  loading: boolean;
  tone: string;
}) {
  return (
    <div className="bg-zinc-800/50 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-1">
        <Image className={`w-5 h-5 ${tone}`} />
        <span className="text-sm text-zinc-400">{label}</span>
      </div>
      <div className="text-2xl font-semibold tabular-nums text-white">
        {loading || value === undefined ? '—' : value.toLocaleString()}
      </div>
    </div>
  );
}
