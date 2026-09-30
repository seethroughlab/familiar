/**
 * Analysis → Status (ADR-0126 point 5): the pipeline, whole.
 *
 * The four phases and their backlog, the worker, the failures, and whether analysis is running —
 * from the worker phase queues, the source that distinguishes phases. `library/stats` also
 * reports a pending count and disagreed with the queues on the same library while ADR-0126 was
 * being written; it is not read here.
 *
 * Re-analysis happens during a library sync (VERSIONING.md), so the action lives on Library →
 * Sync and this page links to it rather than growing a second trigger.
 */
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { libraryApi, systemApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { SectionPage } from '../AdminPage';

const PHASE_LABELS: Record<string, string> = {
  features: 'Features',
  embeddings: 'Embeddings',
  melodic: 'Melodic',
  mood_tags: 'Mood tags',
};

export function StatusSection() {
  const workers = useQuery({ queryKey: queryKeys.workerStatus.all, queryFn: systemApi.workers, refetchInterval: 15_000 });
  const sync = useQuery({ queryKey: queryKeys.syncStatus.all, queryFn: libraryApi.getSyncStatus, refetchInterval: 5_000 });

  const queues = workers.data?.phase_queues ?? [];
  // The schema types `analysis_progress` as a free-form object — the Pydantic model never declared
  // its fields. Narrowed here; typing it on the server is the fix (ADR-0126 Implementation).
  const progress = workers.data?.analysis_progress as
    | { total: number; analyzed: number; pending: number; percent: number }
    | undefined;
  const worker = workers.data?.workers?.[0];
  const failures = workers.data?.recent_failures ?? [];
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
                <th className="text-right font-medium py-1">Pending</th>
                <th className="text-right font-medium py-1 hidden sm:table-cell">Complete</th>
              </tr>
            </thead>
            <tbody>
              {queues.map((q) => (
                <tr key={q.phase} className="border-t border-zinc-800 tabular-nums">
                  <td className="py-2 text-white">{PHASE_LABELS[q.phase] ?? q.phase}</td>
                  <td className="py-2 text-right text-zinc-300">{q.completed.toLocaleString()}</td>
                  <td className={`py-2 text-right ${q.pending > 0 ? 'text-warning' : 'text-zinc-500'}`}>
                    {q.pending.toLocaleString()}
                  </td>
                  <td className="py-2 text-right text-zinc-400 hidden sm:table-cell">{q.percent}%</td>
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

      {failures.length > 0 && (
        <section className="bg-zinc-800/50 rounded-lg p-4 space-y-2" aria-label="Recent failures">
          <h4 className="font-medium text-white">Recent failures</h4>
          <ul className="space-y-1 text-sm">
            {failures.slice(0, 10).map((f, i) => (
              <li key={i} className="text-zinc-300 break-words">
                {f.task} — <span className="text-zinc-500">{f.error}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </SectionPage>
  );
}
