/**
 * The Overview's rules (ADR-0126 point 3), against the shapes the NAS returned on 2026-09-17
 * while the record was being written, and a synthetic failing server.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import { attentionAnswer, attentionItems, healthAnswer, runningAnswer, STALLED_AFTER_MS } from '../attention';

const NOW = Date.parse('2026-09-17T20:30:00Z');
const DAY = 86_400_000;

const idleNas = {
  health: {
    status: 'healthy' as const,
    version: 'v0.2.0-alpha4',
    deployment_mode: 'docker' as const,
    warnings: [],
    services: [
      { name: 'library', status: 'healthy', message: '1/1 paths accessible' },
      { name: 'database', status: 'healthy', message: 'PostgreSQL connected' },
      { name: 'redis', status: 'healthy', message: 'Redis connected' },
      { name: 'background_processing', status: 'healthy', message: 'Idle' },
      { name: 'analysis', status: 'healthy', message: '52 tracks pending' },
    ],
  },
  workers: {
    workers: [{ name: 'in-process', status: 'online', active_tasks: [], processed_total: 0, concurrency: 1 }],
    queues: [{ name: 'analysis', pending: 0 }],
    analysis_progress: { total: 26887, analyzed: 26835, pending: 52, percent: 99.8 },
    recent_failures: [],
    phase_queues: [
      { phase: 'features', pending: 52, completed: 26835, total: 26887, percent: 99.8 },
      { phase: 'embeddings', pending: 97, completed: 26790, total: 26887, percent: 99.6 },
      { phase: 'melodic', pending: 52, completed: 26835, total: 26887, percent: 99.8 },
      { phase: 'mood_tags', pending: 56, completed: 26831, total: 26887, percent: 99.8 },
    ],
  },
  sync: { status: 'completed' as const, message: 'Complete: 0 new, 0 updated, 26790 analyzed', progress: null },
  jobs: { jobs: [], active_count: 0 },
  backup: {
    enabled: false, bucket: 'familiar-backup', region: 'us-east-1', schedule: 'weekly', is_running: false,
    last_backup: { timestamp: new Date(NOW - 11 * DAY).toISOString(), status: 'success' }, progress: null,
  },
  discovery: {
    status: 'working',
    sources: [
      { source: 'acoustid', state: 'working', last_success_at: null, last_failure_at: null, last_failure_kind: 'timeout', last_failure_detail: null, consecutive_failures: 0, items_contributed: 21563, backoff_until: null },
      { source: 'bandcamp', state: 'not_instrumented', last_success_at: null, last_failure_at: null, last_failure_kind: null, last_failure_detail: null, consecutive_failures: 0, items_contributed: 0, backoff_until: null },
      { source: 'musicbrainz', state: 'working', last_success_at: null, last_failure_at: null, last_failure_kind: 'rate_limited', last_failure_detail: null, consecutive_failures: 0, items_contributed: 203, backoff_until: null },
    ],
  },
  artwork: { total_albums: 3957, with_artwork: 3593, generated: 596, without_artwork: 364 },
  now: NOW,
};

describe('the idle NAS', () => {
  it('is healthy, nothing running, with the backlog and the artwork gap pending, and the switched-off backup a warning', () => {
    expect(healthAnswer(idleNas.health)).toMatchObject({ tone: 'ok', head: 'Healthy', sub: '5 of 5 services · v0.2.0-alpha4' });
    expect(runningAnswer(idleNas.sync, idleNas.jobs, NOW)).toMatchObject({ tone: 'idle', head: 'Nothing running' });

    const items = attentionItems(idleNas);
    expect(items.map((i) => [i.tone, i.title])).toEqual([
      ['warn', 'Backups are off'],
      ['info', 'Analysis backlog'],
      ['info', '364 albums without artwork'],
    ]);
    expect(attentionAnswer(items).tone).toBe('warn');
  });

  it('reads the backlog from the phase queues, not from library/stats, and names each phase', () => {
    const backlog = attentionItems(idleNas).find((i) => i.title === 'Analysis backlog')!;
    expect(backlog.detail).toBe('52 features · 97 embeddings · 52 melodic · 56 mood tags — runs during the next library sync');
    expect(backlog.to).toBe('/analysis');
  });

  it('a working provider that once failed is not attention; off and unmonitored are not attention', () => {
    expect(attentionItems(idleNas).filter((i) => i.to === '/server/providers')).toEqual([]);
  });
});

describe('backups that quietly stopped (2026-10-02)', () => {
  const run = (offsetDays: number, status = 'success', error?: string) => ({
    timestamp: new Date(NOW - offsetDays * DAY).toISOString(), status, ...(error ? { error } : {}),
  });

  it('switched off is a warning, naming the last success', () => {
    // Backups stopped on 2026-09-06 and this was an `info` line among pending work for four weeks.
    const items = attentionItems({ ...idleNas, backup: { ...idleNas.backup, enabled: false, last_backup: run(27), last_success: run(27) } });
    expect(items.find((i) => i.title === 'Backups are off')).toMatchObject({ tone: 'warn', detail: expect.stringContaining('27 days ago') });
  });

  it('still says so once history has expired', () => {
    // History expires 30 days after its last write, and every rule went quiet with it.
    const items = attentionItems({ ...idleNas, backup: { ...idleNas.backup, enabled: false, last_backup: null, last_success: run(40) } });
    expect(items.find((i) => i.title === 'Backups are off')?.detail).toContain('40 days ago');
  });

  it('a monthly schedule can be overdue too', () => {
    const items = attentionItems({ ...idleNas, backup: { ...idleNas.backup, enabled: true, schedule: 'monthly', last_backup: run(50), last_success: run(50) } });
    expect(items.find((i) => i.title.startsWith('Last backup was'))).toMatchObject({ tone: 'warn', title: 'Last backup was 50 days ago' });
  });

  it('a failure shows its error, and the age is measured from the last success', () => {
    const items = attentionItems({ ...idleNas, backup: { ...idleNas.backup, enabled: true, schedule: 'weekly', last_backup: run(1, 'error', 'AccessDenied: RestoreObject'), last_success: run(20) } });
    expect(items.find((i) => i.title === 'The last backup failed')?.detail).toBe('AccessDenied: RestoreObject');
    expect(items.find((i) => i.title.startsWith('Last backup was'))?.title).toBe('Last backup was 20 days ago');
  });

  it('on, configured, and never succeeded is a warning', () => {
    const items = attentionItems({ ...idleNas, backup: { ...idleNas.backup, enabled: true, last_backup: null, last_success: null } });
    expect(items.find((i) => i.title === 'No successful backup recorded')?.tone).toBe('warn');
  });

  it('a server with no S3 configured is not nagged', () => {
    const items = attentionItems({ ...idleNas, backup: { ...idleNas.backup, configured: false, bucket: null, enabled: false } });
    expect(items.filter((i) => i.to === '/server/backup')).toEqual([]);
  });
});

describe('a failing server', () => {
  const failing = {
    ...idleNas,
    health: {
      ...idleNas.health,
      status: 'degraded' as const,
      services: [
        { name: 'library', status: 'unhealthy', message: '0/1 paths accessible' },
        { name: 'database', status: 'healthy', message: 'PostgreSQL connected' },
        { name: 'redis', status: 'unhealthy', message: 'connection refused' },
        { name: 'background_processing', status: 'degraded', message: 'sync running' },
        { name: 'analysis', status: 'healthy', message: 'paused' },
      ],
    },
    sync: {
      status: 'running' as const,
      message: 'Scanning',
      progress: { phase: 'discovering', phase_message: 'Discovering files', last_heartbeat: new Date(NOW - STALLED_AFTER_MS - 60_000).toISOString() },
    },
    backup: { ...idleNas.backup, enabled: true, last_backup: { timestamp: new Date(NOW - DAY).toISOString(), status: 'failed' } },
    discovery: {
      status: 'failing',
      sources: [
        { ...idleNas.discovery.sources[2], state: 'backing_off', consecutive_failures: 7, backoff_until: new Date(NOW + 3_600_000).toISOString() },
        { source: 'listenbrainz', state: 'failing', last_success_at: null, last_failure_at: null, last_failure_kind: 'timeout', last_failure_detail: null, consecutive_failures: 19, items_contributed: 0, backoff_until: null },
      ],
    },
  };

  it('leads with exceptions, in severity order, each pointing at the screen that owns it', () => {
    const items = attentionItems(failing as never);
    expect(items.slice(0, 6).map((i) => [i.tone, i.title, i.to])).toEqual([
      ['bad', 'The library path is unhealthy', '/server'],
      ['bad', 'Redis is unhealthy', '/server'],
      ['warn', 'Background processing is degraded', '/server'],
      ['warn', 'Library sync may be stalled', '/library'],
      ['bad', 'The last backup failed', '/server/backup'],
      ['warn', 'MusicBrainz is backing off', '/server/providers'],
    ]);
    expect(items.find((i) => i.title === 'ListenBrainz is failing')?.tone).toBe('bad');
    expect(attentionAnswer(items).tone).toBe('bad');
  });

  it('a running sync with a stale heartbeat reads as stalled', () => {
    const r = runningAnswer(failing.sync as never, failing.jobs, NOW);
    expect(r).toMatchObject({ tone: 'warn', head: 'Library sync stalled', stalled: true });
    expect(r.sub).toMatch(/last heartbeat 11 min ago/);
  });

  it('a stale but enabled backup is a warning with the schedule named', () => {
    const items = attentionItems({ ...idleNas, backup: { ...idleNas.backup, enabled: true } });
    expect(items[0]).toMatchObject({ tone: 'warn', title: 'Last backup was 11 days ago', to: '/server/backup' });
    expect(items[0].detail).toMatch(/weekly/);
  });
});

describe('every attention item links to a mounted route (ADR-0126 point 3)', () => {
  it('each `to` has a path= in App.tsx', () => {
    const appSource = readFileSync(resolve(process.cwd(), 'src/app/App.tsx'), 'utf-8');
    const mounted = new Set(Array.from(appSource.matchAll(/path="(\/[^"*]*)"/g), (m) => m[1]));
    const everything = attentionItems({
      ...idleNas,
      health: { ...idleNas.health, services: [{ name: 'redis', status: 'unhealthy', message: '' }] },
      backup: { ...idleNas.backup, last_backup: { timestamp: 'x', status: 'failed' } },
      discovery: { status: 'failing', sources: [{ source: 'lastfm', state: 'failing', last_success_at: null, last_failure_at: null, last_failure_kind: null, last_failure_detail: null, consecutive_failures: 1, items_contributed: 0, backoff_until: null }] },
      workers: { ...idleNas.workers, recent_failures: [{ task: 't', error: 'e' }] },
    } as never);
    expect(everything.length).toBeGreaterThan(4);
    for (const item of everything) {
      expect(mounted.has(item.to), `${item.title} → ${item.to} is not mounted`).toBe(true);
    }
  });
});

describe('loading is not failure', () => {
  it('says checking while the first request is in flight, and unknown only when it failed', () => {
    expect(healthAnswer(undefined, 'loading')).toMatchObject({ tone: 'idle', head: 'Checking…' });
    expect(healthAnswer(undefined, 'error')).toMatchObject({ tone: 'bad', head: 'Health unknown' });
    expect(runningAnswer(undefined, undefined, NOW, true).head).toBe('Checking…');
    expect(attentionAnswer([], true).head).toBe('Checking…');
    expect(attentionAnswer([], false).head).toBe('Nothing needs attention');
  });
});

describe('an open server (ADR-0141 point 3)', () => {
  const header = 'X-Familiar-Token';

  it('says a server with no token is open to anyone who can reach it', () => {
    const items = attentionItems({ token: { configured: false, open_by_choice: false, header } });
    const item = items.find((i) => i.title.includes('open to anyone'));
    expect(item?.to).toBe('/server/access');
  });

  it('stays quiet when the server is open by choice, as the demo is', () => {
    const items = attentionItems({ token: { configured: false, open_by_choice: true, header } });
    expect(items.some((i) => i.title.includes('open to anyone'))).toBe(false);
  });

  it('stays quiet once a token exists', () => {
    const items = attentionItems({ token: { configured: true, token: 't', open_by_choice: false, header } });
    expect(items.some((i) => i.title.includes('open to anyone'))).toBe(false);
  });
});

describe('the library watch (ADR-0142 point 6)', () => {
  it('says when new music waits for the next sync, and why', () => {
    const items = attentionItems({ watch: { watching: false, reason: 'OSError: inotify watch limit reached', roots: [], pending: 0 } });
    const item = items.find((i) => i.title.includes('next sync'));
    expect(item?.detail).toContain('watch limit');
    expect(item?.tone).toBe('info');
  });

  it('stays quiet while watching', () => {
    const items = attentionItems({ watch: { watching: true, roots: ['/music'], pending: 0 } });
    expect(items.some((i) => i.title.includes('next sync'))).toBe(false);
  });
});
