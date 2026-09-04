/**
 * Restore from S3, on the Server destination.
 *
 * Five restore endpoints existed with **no caller anywhere in either client**,
 * so the one operation a backup exists for had never been executed by anything.
 * This is the surface that makes it reachable without hand-written curl.
 *
 * Restore is three phases because Deep Archive cannot be read directly: ask
 * Glacier to thaw (Bulk tier, 12-48 hours), check whether the thaw finished,
 * then download and apply. The wait is a property of the storage class, not of
 * this UI, so the phases are shown rather than hidden behind one button that
 * appears to hang for two days.
 *
 * The download phase overwrites the live database via `psql`. It takes a local
 * pg_dump first and aborts if that fails, so there is a way back — but it is
 * still the most destructive thing this application can do, hence typing the
 * bucket name. That is a guard against a mis-click, not against an attacker:
 * Familiar runs on a private network and authentication is the network's job.
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { RotateCcw, Loader2, AlertTriangle, Clock, Download } from 'lucide-react';

import { appSettingsApi, s3BackupApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';

export function BackupRestore() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState('');
  const [message, setMessage] = useState<string | null>(null);

  const { data: settings } = useQuery({
    queryKey: queryKeys.appSettings.all,
    queryFn: appSettingsApi.get,
  });

  const { data: manifest } = useQuery({
    queryKey: [...queryKeys.s3Backup.all, 'manifest'],
    queryFn: s3BackupApi.getManifest,
    enabled: open && Boolean(settings?.s3_backup_configured),
  });

  const { data: progress } = useQuery({
    queryKey: queryKeys.s3Backup.restore,
    queryFn: s3BackupApi.getRestoreProgress,
    enabled: open,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 3000 : false),
  });

  const thaw = useMutation({
    mutationFn: () => s3BackupApi.initiateRestore(),
    onSuccess: (r) =>
      setMessage(
        r.error
          ? r.error
          : `Thaw requested for ${r.files_requested ?? 0} files. Glacier Bulk retrieval takes 12-48 hours.`
      ),
  });

  const check = useMutation({
    mutationFn: s3BackupApi.checkRestore,
    onSuccess: (r) => setMessage(JSON.stringify(r)),
  });

  const download = useMutation({
    mutationFn: s3BackupApi.downloadAndRestore,
    onSuccess: (r) => {
      setMessage(r.error ?? r.message ?? r.status);
      setTyped('');
      queryClient.invalidateQueries({ queryKey: queryKeys.s3Backup.all });
    },
  });

  if (!settings?.s3_backup_configured) return null;

  const bucket = settings.s3_backup_bucket ?? '';
  const armed = typed === bucket && bucket.length > 0;

  return (
    <div className="bg-zinc-800 rounded-lg p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <RotateCcw className="w-6 h-6 text-warning" />
          <h3 className="font-medium">Restore from backup</h3>
        </div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="text-sm text-zinc-400 hover:text-zinc-200"
        >
          {open ? 'Hide' : 'Show'}
        </button>
      </div>

      {open && (
        <div className="mt-4 space-y-4">
          {manifest && (
            <p className="text-xs text-zinc-500">
              Backup contains {manifest.file_count.toLocaleString()} files, last written{' '}
              {manifest.last_backup_at ?? 'never'}.
            </p>
          )}

          <div className="flex items-start gap-2 p-3 bg-warning-surface/20 border border-warning-muted rounded-lg">
            <AlertTriangle className="w-4 h-4 text-warning mt-0.5 flex-shrink-0" />
            <div className="text-xs text-zinc-400">
              <p className="text-warning text-sm">This replaces your library database.</p>
              <p className="mt-1">
                A pg_dump of the current database is written to{' '}
                <code>data/restore-safety/</code> first, and the restore aborts if that fails.
                Audio files are only overwritten where the local copy does not match the backup.
              </p>
            </div>
          </div>

          <ol className="space-y-3 text-sm">
            <li className="flex items-start gap-3">
              <Clock className="w-4 h-4 mt-0.5 text-zinc-500 flex-shrink-0" />
              <div className="flex-1">
                <p>1. Ask Glacier to thaw the archive</p>
                <button
                  type="button"
                  onClick={() => thaw.mutate()}
                  disabled={thaw.isPending}
                  className="mt-1 px-3 py-1 text-xs bg-zinc-700 hover:bg-zinc-600 rounded"
                >
                  {thaw.isPending ? 'Requesting…' : 'Request thaw'}
                </button>
              </div>
            </li>
            <li className="flex items-start gap-3">
              <Loader2 className="w-4 h-4 mt-0.5 text-zinc-500 flex-shrink-0" />
              <div className="flex-1">
                <p>2. Check whether the thaw has finished</p>
                <button
                  type="button"
                  onClick={() => check.mutate()}
                  disabled={check.isPending}
                  className="mt-1 px-3 py-1 text-xs bg-zinc-700 hover:bg-zinc-600 rounded"
                >
                  {check.isPending ? 'Checking…' : 'Check availability'}
                </button>
              </div>
            </li>
            <li className="flex items-start gap-3">
              <Download className="w-4 h-4 mt-0.5 text-danger flex-shrink-0" />
              <div className="flex-1">
                <p>3. Download and apply</p>
                <label htmlFor="s3-confirm" className="text-xs text-zinc-500 block mt-1">
                  Type the bucket name <code>{bucket}</code> to enable
                </label>
                <input
                  id="s3-confirm"
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  placeholder={bucket}
                  className="mt-1 bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-sm w-64"
                />
                <button
                  type="button"
                  onClick={() => download.mutate()}
                  disabled={!armed || download.isPending}
                  className="mt-2 block px-3 py-1 text-xs rounded bg-danger disabled:bg-zinc-700 disabled:text-zinc-500"
                >
                  {download.isPending ? 'Restoring…' : 'Restore now'}
                </button>
              </div>
            </li>
          </ol>

          {progress && progress.status === 'running' && (
            <p className="text-xs text-zinc-400">
              {progress.phase === 'safety_dump'
                ? 'Taking a safety dump of the current database…'
                : `${progress.phase} — ${progress.files_uploaded} files`}
            </p>
          )}

          {message && <p className="text-xs text-zinc-400 break-all">{message}</p>}
        </div>
      )}
    </div>
  );
}
