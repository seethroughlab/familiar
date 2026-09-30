/**
 * The Overview's three answers, derived from the server's state (ADR-0126 point 3).
 *
 * Pure: takes what the queries returned, returns what the first viewport says. Kept out of the
 * component so the rules are unit-tested against recorded shapes rather than eyeballed.
 *
 * Rules, and the ADR points behind them:
 * - **Every item links to a mounted screen.** Nothing here points at pending review or a
 *   duplicates count (see `UNBUILT_DESTINATION_ITEMS`).
 * - **The analysis backlog is read from the worker phase queues**, never from `library/stats`:
 *   the two disagreed on the NAS (52 pending against 0) while the record was being written.
 * - Providers use the states `ProviderCards` renders; `not_instrumented` and `disabled` are not
 *   attention — "off" must not look like "broken".
 */

import type {
  BackgroundJobsResponse,
  DiscoveryHealth,
  PhaseQueue,
  SystemHealth,
  WorkerStatus,
} from '../../api/system';
import type { SyncStatus } from '../../api/library';
import type { BackupStatus } from '../../api/s3Backup';
import type { ArtworkCoverage } from '../../api/library';

export type Tone = 'ok' | 'warn' | 'bad' | 'idle' | 'info';

export interface AttentionItem {
  tone: 'bad' | 'warn' | 'info';
  title: string;
  detail: string;
  /** A route that is mounted. `OverviewPage.test.tsx` checks each against `App.tsx`. */
  to: string;
  /** What the link is labelled with. */
  where: string;
}

export interface OverviewInputs {
  health?: SystemHealth;
  workers?: WorkerStatus;
  sync?: SyncStatus;
  jobs?: BackgroundJobsResponse;
  backup?: BackupStatus;
  discovery?: DiscoveryHealth;
  artwork?: ArtworkCoverage;
  now?: number;
}

const DAY = 86_400_000;
/** A sync whose heartbeat is older than this while it says "running" is presumed stuck. */
export const STALLED_AFTER_MS = 10 * 60_000;

const PHASE_LABELS: Record<string, string> = {
  features: 'features',
  embeddings: 'embeddings',
  melodic: 'melodic',
  mood_tags: 'mood tags',
};

const PROVIDER_LABELS: Record<string, string> = {
  musicbrainz: 'MusicBrainz',
  listenbrainz: 'ListenBrainz',
  lastfm: 'Last.fm',
  acoustid: 'AcoustID',
  bandcamp: 'Bandcamp',
  soulseek: 'Soulseek',
  community_cache_claims: 'Community cache',
  discovery_batch: 'Nightly discovery',
};

function ageMs(iso: string | null | undefined, now: number): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? null : now - t;
}

export function days(ms: number): number {
  return Math.round(ms / DAY);
}

// ── is the system healthy? ───────────────────────────────────────────────────────────────────

export function healthAnswer(
  health?: SystemHealth,
  state: 'loading' | 'error' | 'ready' = health ? 'ready' : 'error',
): { tone: Tone; head: string; sub: string } {
  // Loading and failed are different answers: "unknown" while the first request is in flight
  // would tell an operator the server is unreachable for the half-second it takes to answer.
  if (state === 'loading') return { tone: 'idle', head: 'Checking…', sub: 'Loading…' };
  if (!health) return { tone: 'bad', head: 'Health unknown', sub: 'Could not read the server' };
  const services = health.services ?? [];
  const unhealthy = services.filter((s) => s.status !== 'healthy');
  const version = health.version ? ` · ${health.version}` : '';
  if (unhealthy.length === 0) {
    return { tone: 'ok', head: 'Healthy', sub: `${services.length} of ${services.length} services${version}` };
  }
  const tone: Tone = health.status === 'unhealthy' ? 'bad' : 'warn';
  return {
    tone,
    head: health.status === 'unhealthy' ? 'Unhealthy' : 'Degraded',
    sub: `${services.length - unhealthy.length} of ${services.length} services${version}`,
  };
}

// ── is anything running? ─────────────────────────────────────────────────────────────────────

export function runningAnswer(
  sync?: SyncStatus,
  jobs?: BackgroundJobsResponse,
  now: number = Date.now(),
  loading = false,
): { tone: Tone; head: string; sub: string; stalled: boolean } {
  if (loading && !sync && !jobs) return { tone: 'idle', head: 'Checking…', sub: 'Loading…', stalled: false };
  const heartbeatAge = ageMs(sync?.progress?.last_heartbeat, now);
  const syncRunning = sync?.status === 'running' || sync?.status === 'already_running';
  const stalled = syncRunning && heartbeatAge !== null && heartbeatAge > STALLED_AFTER_MS;

  if (syncRunning) {
    const phase = sync?.progress?.phase_message || sync?.message || 'Library sync';
    return stalled
      ? { tone: 'warn', head: 'Library sync stalled', sub: `${phase} · last heartbeat ${Math.round(heartbeatAge! / 60_000)} min ago`, stalled }
      : { tone: 'ok', head: 'Library sync running', sub: phase, stalled };
  }

  const active = (jobs?.jobs ?? []).filter((j) => j.status === 'running');
  if (active.length > 0) {
    const names = active.map((j) => j.type.replace(/_/g, ' ')).join(', ');
    return { tone: 'ok', head: `${active.length} job${active.length === 1 ? '' : 's'} running`, sub: names, stalled: false };
  }

  const last = sync?.message ? `Last sync: ${sync.message}` : 'No sync recorded';
  return { tone: 'idle', head: 'Nothing running', sub: last, stalled: false };
}

// ── what needs attention? ────────────────────────────────────────────────────────────────────

function backlog(queues: PhaseQueue[] | undefined): PhaseQueue[] {
  return (queues ?? []).filter((q) => q.pending > 0);
}

export function attentionItems(inputs: OverviewInputs): AttentionItem[] {
  const now = inputs.now ?? Date.now();
  const items: AttentionItem[] = [];

  // Exceptions first: things that are wrong, then things that are waiting.
  for (const service of inputs.health?.services ?? []) {
    if (service.status === 'healthy') continue;
    items.push({
      tone: service.status === 'unhealthy' ? 'bad' : 'warn',
      title: `${serviceLabel(service.name)} is ${service.status}`,
      detail: service.message ?? '',
      to: '/server',
      where: 'Server › Health',
    });
  }

  const running = runningAnswer(inputs.sync, inputs.jobs, now);
  if (running.stalled) {
    items.push({ tone: 'warn', title: 'Library sync may be stalled', detail: running.sub, to: '/library', where: 'Library › Sync' });
  }

  const b = inputs.backup;
  const last = b?.last_backup as { timestamp?: string; status?: string } | null | undefined;
  if (last?.status && last.status !== 'success') {
    items.push({ tone: 'bad', title: 'The last backup failed', detail: `S3 backup ended with status "${last.status}"`, to: '/server/backup', where: 'Server › Backup' });
  } else if (b) {
    const age = ageMs(last?.timestamp, now);
    const period = b.schedule === 'daily' ? DAY : b.schedule === 'weekly' ? 7 * DAY : null;
    if (b.enabled && period && age !== null && age > period * 1.5) {
      items.push({ tone: 'warn', title: `Last backup was ${days(age)} days ago`, detail: `The schedule is ${b.schedule}; a backup is overdue`, to: '/server/backup', where: 'Server › Backup' });
    } else if (!b.enabled && age !== null) {
      items.push({ tone: 'info', title: 'Backups are off', detail: `Last backup ${days(age)} days ago; S3 is configured but the schedule is disabled`, to: '/server/backup', where: 'Server › Backup' });
    }
  }

  for (const source of inputs.discovery?.sources ?? []) {
    const label = PROVIDER_LABELS[source.source] ?? source.source;
    if (source.state === 'failing' || source.state === 'never_succeeded') {
      items.push({
        tone: 'bad',
        title: `${label} is ${source.state === 'failing' ? 'failing' : 'not working'}`,
        detail: source.last_failure_kind ? `Last failure: ${source.last_failure_kind.replace(/_/g, ' ')}` : 'Has never found anything',
        to: '/server/providers',
        where: 'Server › Providers',
      });
    } else if (source.state === 'backing_off' || source.state === 'degraded') {
      items.push({
        tone: 'warn',
        title: `${label} is ${source.state === 'backing_off' ? 'backing off' : 'degraded'}`,
        detail: source.last_failure_kind ? `Last failure: ${source.last_failure_kind.replace(/_/g, ' ')}` : '',
        to: '/server/providers',
        where: 'Server › Providers',
      });
    }
  }

  const failures = inputs.workers?.recent_failures?.length ?? 0;
  if (failures > 0) {
    items.push({ tone: 'warn', title: `${failures} recent analysis failure${failures === 1 ? '' : 's'}`, detail: 'Tracks whose analysis raised; see the pipeline status', to: '/analysis', where: 'Analysis' });
  }

  const pending = backlog(inputs.workers?.phase_queues);
  if (pending.length > 0) {
    const detail = pending.map((q) => `${q.pending.toLocaleString()} ${PHASE_LABELS[q.phase] ?? q.phase}`).join(' · ');
    items.push({ tone: 'info', title: 'Analysis backlog', detail: `${detail} — runs during the next library sync`, to: '/analysis', where: 'Analysis' });
  }

  const missing = inputs.artwork?.without_artwork ?? 0;
  if (missing > 0) {
    const generated = inputs.artwork?.generated ?? 0;
    items.push({
      tone: 'info',
      title: `${missing.toLocaleString()} album${missing === 1 ? '' : 's'} without artwork`,
      detail: generated > 0 ? `${generated.toLocaleString()} more are using generated art` : '',
      to: '/library/artwork',
      where: 'Library › Artwork',
    });
  }

  return items;
}

function serviceLabel(name: string): string {
  const labels: Record<string, string> = {
    library: 'The library path',
    database: 'PostgreSQL',
    redis: 'Redis',
    background_processing: 'Background processing',
    analysis: 'Analysis',
  };
  return labels[name] ?? name;
}

export function attentionAnswer(
  items: AttentionItem[],
  loading = false,
): { tone: Tone; head: string; sub: string } {
  if (loading && items.length === 0) return { tone: 'idle', head: 'Checking…', sub: 'Loading…' };
  if (items.length === 0) return { tone: 'ok', head: 'Nothing needs attention', sub: 'No exceptions, no pending work' };
  const exceptions = items.filter((i) => i.tone !== 'info').length;
  const pending = items.length - exceptions;
  const tone: Tone = items.some((i) => i.tone === 'bad') ? 'bad' : exceptions > 0 ? 'warn' : 'info';
  const parts = [
    exceptions > 0 ? `${exceptions} exception${exceptions === 1 ? '' : 's'}` : null,
    pending > 0 ? `${pending} pending` : null,
  ].filter(Boolean);
  return { tone, head: `${items.length} need${items.length === 1 ? 's' : ''} attention`, sub: parts.join(' · ') };
}
