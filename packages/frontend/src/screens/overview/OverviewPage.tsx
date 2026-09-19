/**
 * Overview — the landing page (ADR-0126 point 3).
 *
 * Three questions in the first viewport: is the system healthy, is anything running, and what
 * needs attention. Collection totals and listening come after, because an operator arriving with
 * a problem should not scroll past three numbers to find it (point 9). Every attention item links
 * to a screen that is mounted; the rules are in `attention.ts`, tested on their own.
 *
 * This is a summary (Consequences). Redis being down is reported here and *handled* under
 * Server → Health; the same panel is never rendered in two destinations (point 2).
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Activity, AlertTriangle, CheckCircle2, ChevronRight, RefreshCw } from 'lucide-react';
import { useState } from 'react';

import { libraryApi, s3BackupApi, systemApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { showError } from '../../stores/toastStore';
import { Dashboard } from '../Dashboard';
import { attentionAnswer, attentionItems, healthAnswer, runningAnswer, type Tone } from './attention';

const TONE_TEXT: Record<Tone, string> = {
  ok: 'text-success',
  warn: 'text-warning',
  bad: 'text-danger',
  info: 'text-blue-400',
  idle: 'text-zinc-400',
};
const TONE_DOT: Record<Tone, string> = {
  ok: 'bg-success',
  warn: 'bg-warning',
  bad: 'bg-danger',
  info: 'bg-blue-400',
  idle: 'bg-zinc-500',
};

function Tile({
  tone,
  icon: Icon,
  head,
  sub,
  children,
}: {
  tone: Tone;
  icon: typeof Activity;
  head: string;
  sub: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="bg-zinc-800/50 rounded-lg p-4 flex flex-col gap-2 min-w-0">
      <div className={`flex items-center gap-2 ${TONE_TEXT[tone]}`}>
        <Icon className="w-5 h-5 shrink-0" />
        <span className="text-base font-semibold text-white">{head}</span>
      </div>
      <p className="text-sm text-zinc-400">{sub}</p>
      {children}
    </div>
  );
}

function SyncNowButton() {
  const queryClient = useQueryClient();
  const [starting, setStarting] = useState(false);
  const start = async () => {
    setStarting(true);
    try {
      await libraryApi.sync();
      await queryClient.invalidateQueries({ queryKey: queryKeys.syncStatus.all });
      await queryClient.invalidateQueries({ queryKey: queryKeys.backgroundJobs.all });
    } catch {
      showError('Failed to start library sync');
    } finally {
      setStarting(false);
    }
  };
  return (
    <button
      type="button"
      onClick={start}
      disabled={starting}
      className="self-start mt-1 inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-60"
    >
      <RefreshCw className={`w-4 h-4 ${starting ? 'animate-spin' : ''}`} />
      Sync library
    </button>
  );
}

export function OverviewPage() {
  const health = useQuery({ queryKey: queryKeys.systemHealth.all, queryFn: systemApi.health, refetchInterval: 30_000 });
  const workers = useQuery({ queryKey: queryKeys.workerStatus.all, queryFn: systemApi.workers, refetchInterval: 30_000 });
  const sync = useQuery({ queryKey: queryKeys.syncStatus.all, queryFn: libraryApi.getSyncStatus, refetchInterval: 5_000 });
  const jobs = useQuery({ queryKey: queryKeys.backgroundJobs.all, queryFn: systemApi.jobs, refetchInterval: 5_000 });
  const backup = useQuery({ queryKey: queryKeys.backupStatus.all, queryFn: s3BackupApi.getStatus, staleTime: 60_000 });
  const discovery = useQuery({ queryKey: queryKeys.discoverySources.all, queryFn: systemApi.discoverySources, refetchInterval: 30_000 });
  const artwork = useQuery({ queryKey: queryKeys.library.artworkCoverage(), queryFn: () => libraryApi.getArtworkCoverage(), staleTime: 5 * 60_000 });

  const h = healthAnswer(health.data, health.isPending ? 'loading' : health.data ? 'ready' : 'error');
  const r = runningAnswer(sync.data, jobs.data, Date.now(), sync.isPending || jobs.isPending);
  const items = attentionItems({
    health: health.data,
    workers: workers.data,
    sync: sync.data,
    jobs: jobs.data,
    backup: backup.data,
    discovery: discovery.data,
    artwork: artwork.data,
  });
  const stillLoading = [health, workers, sync, jobs, backup, discovery, artwork].some((q) => q.isPending);
  const a = attentionAnswer(items, stillLoading);
  const running = r.tone === 'ok' || r.tone === 'warn';

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto space-y-5">
      <div>
        <h2 className="text-xl font-bold text-white">Overview</h2>
        <p className="text-sm text-zinc-400 mt-1">Is it healthy, is anything running, what needs attention</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Tile tone={h.tone} icon={h.tone === 'ok' ? CheckCircle2 : h.tone === 'idle' ? Activity : AlertTriangle} head={h.head} sub={h.sub} />
        <Tile tone={r.tone} icon={Activity} head={r.head} sub={r.sub}>
          {!running && <SyncNowButton />}
        </Tile>
        <Tile tone={a.tone} icon={a.tone === 'ok' ? CheckCircle2 : a.tone === 'idle' ? Activity : AlertTriangle} head={a.head} sub={a.sub} />
      </div>

      {items.length > 0 && (
        <section aria-label="Needs attention" className="bg-zinc-800/50 rounded-lg overflow-hidden">
          <h3 className="px-4 py-3 text-sm font-medium text-zinc-400 uppercase tracking-wider">Needs attention</h3>
          <ul>
            {items.map((item) => (
              <li key={`${item.to}:${item.title}`} className="border-t border-zinc-800">
                <Link
                  to={item.to}
                  className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-800/60 transition-colors"
                >
                  <span aria-hidden="true" className={`w-2.5 h-2.5 rounded-full shrink-0 ${TONE_DOT[item.tone]}`} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm text-white">{item.title}</span>
                    {item.detail && <span className="block text-xs text-zinc-400">{item.detail}</span>}
                  </span>
                  <span className="hidden sm:inline text-xs text-blue-400 whitespace-nowrap">{item.where}</span>
                  <ChevronRight className="w-4 h-4 text-zinc-500 shrink-0" />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Secondary: what there is, once you know whether anything is wrong (point 3). */}
      <Dashboard />
    </div>
  );
}
