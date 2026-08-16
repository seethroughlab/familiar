import { useQuery } from '@tanstack/react-query';
import { Disc3, Users, Music, Activity, Clock, AlertTriangle } from 'lucide-react';

import { libraryApi } from '../../api/library';
import { playTrackingApi, type PlayStatsResponse } from '../../api/profiles';
import { queryKeys } from '../../api/queryKeys';
import { offlineAwareRetry } from '../../api/queryDefaults';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';

/**
 * What the administrator is administering (ADR-0058 point 1).
 *
 * The app used to open on Settings — a form, with playback controls above library health, which
 * told the operator its own subject was secondary. This opens on the state of the library instead.
 *
 * **Every number here comes from a real query** (point 6). Both endpoints already existed and both
 * already had a client wrapper that nothing called: `libraryApi.getStats` over `/library/stats` and
 * `playTrackingApi.getStats` over `/tracks/stats/plays`. Nothing on this screen is derived from a
 * sample or rounded into a nicer shape, and a count that does not exist does not get a tile —
 * artwork coverage is absent for exactly that reason and needs an endpoint first.
 */
export function Dashboard() {
  const { isOffline } = useOfflineStatus();

  const { data: library, isLoading: libraryLoading } = useQuery({
    queryKey: queryKeys.library.stats(),
    queryFn: () => libraryApi.getStats(),
    retry: offlineAwareRetry(isOffline),
  });

  const { data: plays } = useQuery({
    queryKey: queryKeys.library.playStats(5),
    queryFn: () => playTrackingApi.getStats(5),
    retry: offlineAwareRetry(isOffline),
  });

  const analysed = library ? library.analyzed_tracks : 0;
  const total = library ? library.total_tracks : 0;
  const coverage = total > 0 ? Math.round((analysed / total) * 100) : 0;

  /**
   * The four backlogs, named separately (point 7).
   *
   * `analysis`, `backfill`, `melodic` and `mood_tags` have their own version constants and their
   * own reasons to stall — a single "pending" number hides which one is stuck, which is most of the
   * reason to have this screen rather than a progress bar.
   */
  const queues = library
    ? [
        { label: 'Analysis', value: library.pending_analysis },
        { label: 'Backfill', value: library.pending_backfill },
        { label: 'Melodic', value: library.pending_melodic },
        { label: 'Mood tags', value: library.pending_mood_tags },
      ].filter((q) => q.value > 0)
    : [];

  return (
    // Page chrome (title, padding, width) belongs to `LibraryPage`; this is content only, so the
    // same tiles can sit under a heading it does not own.
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Stat icon={<Music className="w-5 h-5 text-cyan-400" />} label="Tracks"
              value={library?.total_tracks} loading={libraryLoading} />
        {/*
          * No albums/compilations/soundtracks breakdown, though `/library/stats` returns one.
          * Nothing writes `Track.album_type`, so every row keeps the column default: the
          * breakdown reads "26,488 albums · 0 compilations" on a library ADR-0052 found 297
          * compilations in. Point 6 forbids exactly this — a figure that looks like data.
          */}
        <Stat icon={<Disc3 className="w-5 h-5 text-cyan-400" />} label="Albums"
              value={library?.total_albums} loading={libraryLoading} />
        <Stat icon={<Users className="w-5 h-5 text-cyan-400" />} label="Artists"
              value={library?.total_artists} loading={libraryLoading} />
      </div>

      <section className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4 space-y-3">
        <div className="flex items-center gap-3">
          <Activity className="w-5 h-5 text-cyan-400" />
          <h3 className="font-medium text-white dark:text-white light:text-zinc-900">Analysis</h3>
          <span className="ml-auto text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600 tabular-nums">
            {libraryLoading ? '—' : `${analysed.toLocaleString()} of ${total.toLocaleString()}`}
          </span>
        </div>

        <div className="h-2 rounded bg-zinc-700/50 overflow-hidden">
          <div className="h-full bg-cyan-500 transition-[width] duration-500"
               style={{ width: `${coverage}%` }} />
        </div>
        <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
          {libraryLoading ? 'Loading…' : `${coverage}% analysed`}
        </p>

        {queues.length > 0 && (
          <div className="pt-1 space-y-1">
            <div className="flex items-center gap-2 text-sm text-zinc-300 dark:text-zinc-300 light:text-zinc-700">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              <span>Waiting</span>
            </div>
            {queues.map((q) => (
              <div key={q.label} className="flex items-center justify-between bg-zinc-900/50 rounded p-2">
                <span className="text-sm text-zinc-300 dark:text-zinc-300 light:text-zinc-700">{q.label}</span>
                <span className="text-sm tabular-nums text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
                  {q.value.toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {plays && plays.total_plays > 0 && (
        <section className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4 space-y-3">
          <div className="flex items-center gap-3">
            <Clock className="w-5 h-5 text-cyan-400" />
            <h3 className="font-medium text-white dark:text-white light:text-zinc-900">Listening</h3>
          </div>
          <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
            {plays.total_plays.toLocaleString()} plays across{' '}
            {plays.unique_tracks.toLocaleString()} tracks · {formatHours(plays.total_play_seconds)}
          </p>
          {plays.top_tracks.length > 0 && (
            <ol className="space-y-1">
              {plays.top_tracks.map((t: PlayStatsResponse['top_tracks'][number]) => (
                <li key={t.id} className="flex items-center justify-between bg-zinc-900/50 rounded p-2">
                  <span className="text-sm truncate text-zinc-300 dark:text-zinc-300 light:text-zinc-700">
                    {t.title ?? 'Untitled'}
                    {t.artist ? <span className="text-zinc-500"> — {t.artist}</span> : null}
                  </span>
                  <span className="text-sm tabular-nums text-zinc-400 dark:text-zinc-400 light:text-zinc-600 pl-3">
                    {t.play_count}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </section>
      )}
    </div>
  );
}

function Stat({ icon, label, value, detail, loading }: {
  icon: React.ReactNode;
  label: string;
  value: number | undefined;
  detail?: string;
  loading: boolean;
}) {
  return (
    <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-1">
        {icon}
        <span className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">{label}</span>
      </div>
      <div className="text-2xl font-semibold tabular-nums text-white dark:text-white light:text-zinc-900">
        {loading || value === undefined ? '—' : value.toLocaleString()}
      </div>
      {detail && (
        <p className="text-xs text-zinc-500 mt-1">{detail}</p>
      )}
    </div>
  );
}

/** Seconds are what the endpoint returns; hours are what a person reads. */
function formatHours(seconds: number): string {
  const hours = seconds / 3600;
  if (hours < 1) return `${Math.round(seconds / 60)} minutes`;
  if (hours < 100) return `${hours.toFixed(1)} hours`;
  return `${Math.round(hours).toLocaleString()} hours`;
}
