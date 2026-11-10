/**
 * Analysis → Status (ADR-0126 point 5): the pipeline, whole.
 *
 * The four phases by state, the worker, the tracks that failed, and whether analysis is running.
 * Every count is the server's one status model (ADR-0172): `library/stats` and this page used to
 * disagree on the same library, and now read the same query.
 *
 * Re-analysis happens during a library sync (VERSIONING.md), so the action lives on Library →
 * Sync and this page links to it rather than growing a second trigger.
 */
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { libraryApi, systemApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { SectionPage } from '../AdminPage';
import { FailureGroups } from './FailureGroups';

const PHASE_LABELS: Record<string, string> = {
  features: 'Features',
  embeddings: 'Embeddings',
  melodic: 'Melodic',
  mood_tags: 'Mood tags',
};

/** What each reason code means to someone who can act on it (ADR-0172 point 2). */
const REASON_LABELS: Record<string, string> = {
  undecodable: 'the file could not be decoded',
  file_missing: 'the file is missing',
  worker_crashed: 'the worker crashed',
  timeout: 'timed out',
  error: 'an error',
};

function Count({ value, tone }: { value: number; tone: string }) {
  return <td className={`py-2 text-right ${value > 0 ? tone : 'text-zinc-500'}`}>{value.toLocaleString()}</td>;
}

export function StatusSection() {
  const workers = useQuery({ queryKey: queryKeys.workerStatus.all, queryFn: systemApi.workers, refetchInterval: 15_000 });
  const sync = useQuery({ queryKey: queryKeys.syncStatus.all, queryFn: libraryApi.getSyncStatus, refetchInterval: 5_000 });

  const failed = useQuery({
    queryKey: queryKeys.analysisFailures.all,
    queryFn: () => systemApi.analysisFailures(50),
    refetchInterval: 60_000,
  });

  const queues = workers.data?.phase_queues ?? [];
  const progress = workers.data?.analysis_progress;
  const worker = workers.data?.workers?.[0];
  const stalls = queues.reduce((n, q) => n + (q.stall_recoveries ?? 0), 0);
  const syncRunning = sync.data?.status === 'running';

  return (
    <SectionPage title="Status" subtitle="What has been analysed, what is waiting, and what is running">
      <section className="bg-zinc-800/50 rounded-lg p-4 space-y-3" aria-label="Pipeline">
        <div className="flex items-baseline justify-between gap-3">
          <h4 className="font-medium text-white">Pipeline</h4>
          {progress && (
            <span className="text-sm text-zinc-400 tabular-nums">
              {progress.analyzed.toLocaleString()} of {progress.total.toLocaleString()} · {progress.percent}%
            </span>
          )}
        </div>

        {workers.isError && <p className="text-sm text-danger">Could not read the worker status.</p>}

        {queues.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wider text-zinc-500">
                <th className="text-left font-medium py-1">Phase</th>
                <th className="text-right font-medium py-1">Done</th>
                <th className="text-right font-medium py-1" title="May be worked on now">Queued</th>
                <th className="text-right font-medium py-1" title="Failed; tried again after a day">Retrying</th>
                <th className="text-right font-medium py-1" title="Failed; not tried again until the file changes">Failed</th>
                <th className="text-right font-medium py-1 hidden sm:table-cell" title="An earlier phase has not finished">Waiting</th>
              </tr>
            </thead>
            <tbody>
              {queues.map((q) => (
                <tr key={q.phase} className="border-t border-zinc-800 tabular-nums">
                  <td className="py-2 text-white">{PHASE_LABELS[q.phase] ?? q.phase}</td>
                  <td className="py-2 text-right text-zinc-300">
                    {q.completed.toLocaleString()} <span className="text-zinc-500">· {q.percent}%</span>
                  </td>
                  <Count value={q.queued ?? 0} tone="text-warning" />
                  <Count value={q.retrying ?? 0} tone="text-warning" />
                  <Count value={q.failed ?? 0} tone="text-danger" />
                  <td className="py-2 text-right text-zinc-500 hidden sm:table-cell">
                    {(q.waiting ?? 0).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <p className="text-xs text-zinc-500">
          {stalls > 0 ? `${stalls} stall recover${stalls === 1 ? 'y' : 'ies'} · ` : ''}
          re-analysis runs during a library sync
        </p>
      </section>

      <section className="bg-zinc-800/50 rounded-lg p-4 space-y-2" aria-label="Running now">
        <h4 className="font-medium text-white">Running now</h4>
        <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-zinc-400">Worker</dt>
          <dd className="text-zinc-300">
            {worker ? `${worker.name} · ${worker.status} · ${worker.active_tasks?.length ?? 0} active` : '—'}
          </dd>
          <dt className="text-zinc-400">Sync</dt>
          <dd className="text-zinc-300">{sync.data?.message ?? '—'}</dd>
        </dl>
        {!syncRunning && (
          <Link to="/library" className="inline-block text-sm text-blue-400 hover:text-blue-300">
            Start a sync → Library / Sync
          </Link>
        )}
      </section>

      {(failed.data?.total ?? 0) > 0 && (
        <section className="bg-zinc-800/50 rounded-lg p-4 space-y-2" aria-label="Failed tracks">
          <div className="flex items-baseline justify-between gap-3">
            <h4 className="font-medium text-white">Failed tracks</h4>
            <span className="text-sm text-zinc-400 tabular-nums">{failed.data!.total.toLocaleString()}</span>
          </div>
          <ul className="space-y-1 text-sm">
            {failed.data!.failures.map((f) => (
              <li key={`${f.track_id}-${f.phase}`} className="text-zinc-300 break-words">
                {f.artist ?? 'Unknown artist'} — {f.title ?? 'Untitled'}{' '}
                <span className="text-zinc-500">
                  · {PHASE_LABELS[f.phase] ?? f.phase} · {REASON_LABELS[f.reason] ?? f.reason}
                  {f.final ? '' : ` · retrying (attempt ${f.attempts})`}
                </span>
              </li>
            ))}
          </ul>
          {failed.data!.total > failed.data!.failures.length && (
            <p className="text-xs text-zinc-500">
              Showing the {failed.data!.failures.length} most recent.
            </p>
          )}
        </section>
      )}

      <FailureGroups groups={workers.data?.failure_groups ?? []} />
    </SectionPage>
  );
}
