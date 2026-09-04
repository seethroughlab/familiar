/**
 * S3 backup configuration, on the Server destination.
 *
 * The backend has run a full-installation backup on an APScheduler cron for
 * months — pg_dump and settings to S3 Standard, audio and artwork
 * content-addressed into Glacier Deep Archive. **Nothing could turn it on.**
 * `s3_backup_enabled` and `s3_backup_schedule` were typed in `api/settings.ts`
 * and rendered by no component, and neither is in `config.py`, so the only way
 * in was hand-editing `data/settings.json`. The scheduler's first line is
 * `if not settings.s3_backup_enabled: return`, so the whole feature sat inert
 * and silent.
 *
 * Credentials are not editable here on purpose: bucket, region, prefix and keys
 * come from the environment and `/settings` returns them read-only, so this
 * panel never handles a secret. What it owns is the operational half — whether
 * backups run, how often, and whether the bucket actually works.
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  CloudUpload,
  Loader2,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Play,
  Square,
} from 'lucide-react';

import { appSettingsApi, s3BackupApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';

const SCHEDULES = [
  { value: 'daily', label: 'Daily', hint: '03:30' },
  { value: 'weekly', label: 'Weekly', hint: 'Sundays, 03:30' },
  { value: 'monthly', label: 'Monthly', hint: '1st, 03:30' },
];

function formatBytes(n: number): string {
  if (!n) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), units.length - 1);
  return `${(n / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function BackupSettings() {
  const queryClient = useQueryClient();
  const [validation, setValidation] = useState<string | null>(null);

  const { data: settings, isLoading } = useQuery({
    queryKey: queryKeys.appSettings.all,
    queryFn: appSettingsApi.get,
  });

  const { data: status } = useQuery({
    queryKey: queryKeys.s3Backup.status,
    queryFn: s3BackupApi.getStatus,
    // Only poll while a backup is actually moving.
    refetchInterval: (q) => (q.state.data?.is_running ? 3000 : false),
  });

  const { data: estimate } = useQuery({
    queryKey: queryKeys.s3Backup.estimate,
    queryFn: s3BackupApi.getEstimate,
    enabled: Boolean(settings?.s3_backup_configured),
    staleTime: 5 * 60 * 1000,
  });

  const update = useMutation({
    mutationFn: appSettingsApi.update,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.appSettings.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.s3Backup.all });
    },
  });

  const validate = useMutation({
    mutationFn: () =>
      s3BackupApi.validate({
        bucket: settings?.s3_backup_bucket ?? '',
        region: settings?.s3_backup_region,
        prefix: settings?.s3_backup_prefix,
      }),
    onSuccess: (r) =>
      setValidation(r.valid ? 'Bucket reachable, permissions look right.' : (r.error ?? 'Failed')),
    onError: (e: Error) => setValidation(e.message),
  });

  const runNow = useMutation({
    mutationFn: s3BackupApi.run,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.s3Backup.all }),
  });

  const cancel = useMutation({
    mutationFn: s3BackupApi.cancel,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.s3Backup.all }),
  });

  if (isLoading) {
    return (
      <div className="p-4">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }

  const configured = settings?.s3_backup_configured;
  const enabled = settings?.s3_backup_enabled ?? false;

  return (
    <div className="bg-zinc-800 rounded-lg p-4">
      <div className="flex items-center gap-3 mb-3">
        <CloudUpload className="w-6 h-6 text-info" />
        <h3 className="font-medium">S3 Backup</h3>
      </div>

      {!configured ? (
        <div className="flex items-start gap-2 p-3 bg-warning-surface/20 border border-warning-muted rounded-lg">
          <AlertTriangle className="w-4 h-4 text-warning mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm text-warning">S3 credentials not configured</p>
            <p className="text-xs text-zinc-500 mt-1">
              Set <code>S3_BACKUP_BUCKET</code>, <code>S3_BACKUP_ACCESS_KEY_ID</code> and{' '}
              <code>S3_BACKUP_SECRET_ACCESS_KEY</code> in <code>docker/.env</code>. Credentials are
              read from the environment and never stored or edited here.
            </p>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm">Scheduled backups</p>
              <p className="text-xs text-zinc-500">
                {settings?.s3_backup_bucket} · {settings?.s3_backup_region}
                {settings?.s3_backup_prefix ? ` · ${settings.s3_backup_prefix}` : ''}
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={enabled}
              aria-label="Scheduled backups"
              disabled={update.isPending}
              onClick={() => update.mutate({ s3_backup_enabled: !enabled })}
              className={`relative w-11 h-6 rounded-full transition-colors ${
                enabled ? 'bg-success' : 'bg-zinc-600'
              }`}
            >
              <span
                className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-transform ${
                  enabled ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          {enabled && (
            <div>
              <label htmlFor="s3-schedule" className="text-xs text-zinc-500 block mb-1">
                Frequency
              </label>
              <select
                id="s3-schedule"
                value={settings?.s3_backup_schedule ?? 'weekly'}
                disabled={update.isPending}
                onChange={(e) => update.mutate({ s3_backup_schedule: e.target.value })}
                className="bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-sm"
              >
                {SCHEDULES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label} ({s.hint})
                  </option>
                ))}
              </select>
            </div>
          )}

          {estimate && (
            <div className="text-xs text-zinc-400 border-t border-zinc-700 pt-3">
              <span className="text-zinc-300">{estimate.storage_gb.toFixed(1)} GB</span> stored ·{' '}
              <span className="text-zinc-300">${estimate.monthly_cost.toFixed(2)}/month</span> ·
              restore would cost about{' '}
              <span className="text-zinc-300">${estimate.estimated_restore_cost.toFixed(2)}</span>
            </div>
          )}

          {status?.last_backup && !status.is_running && (
            <p className="text-xs text-zinc-500">
              Last backup {String(status.last_backup.completed_at ?? 'unknown')}
            </p>
          )}

          {status?.is_running && status.progress && (
            <div className="text-xs text-zinc-400">
              <p>
                {status.progress.phase} — {status.progress.files_uploaded} uploaded,{' '}
                {status.progress.files_skipped} unchanged,{' '}
                {formatBytes(status.progress.bytes_uploaded)}
              </p>
            </div>
          )}

          <div className="flex items-center gap-2">
            {status?.is_running ? (
              <button
                type="button"
                onClick={() => cancel.mutate()}
                disabled={cancel.isPending}
                className="flex items-center gap-1 px-3 py-1.5 text-sm bg-zinc-700 hover:bg-zinc-600 rounded"
              >
                <Square className="w-3 h-3" /> Cancel
              </button>
            ) : (
              <button
                type="button"
                onClick={() => runNow.mutate()}
                disabled={runNow.isPending}
                className="flex items-center gap-1 px-3 py-1.5 text-sm bg-zinc-700 hover:bg-zinc-600 rounded"
              >
                <Play className="w-3 h-3" /> Back up now
              </button>
            )}
            <button
              type="button"
              onClick={() => validate.mutate()}
              disabled={validate.isPending}
              className="px-3 py-1.5 text-sm bg-zinc-700 hover:bg-zinc-600 rounded"
            >
              {validate.isPending ? 'Checking…' : 'Test bucket'}
            </button>
          </div>

          {validation && (
            <div className="flex items-start gap-2 text-xs">
              {validation.startsWith('Bucket reachable') ? (
                <CheckCircle className="w-4 h-4 text-success flex-shrink-0" />
              ) : (
                <XCircle className="w-4 h-4 text-danger flex-shrink-0" />
              )}
              <span className="text-zinc-400">{validation}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
