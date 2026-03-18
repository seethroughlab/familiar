import {
  CloudDownload,
  Loader2,
  RefreshCw,
  AlertTriangle,
  Clock,
  CheckCircle,
} from 'lucide-react';
import type { S3ManifestSummary, S3RestoreState } from '../../../api';
import { formatRelativeTime, formatBytes } from './utils';

export function RestoreSection({
  onLoadManifest,
  isLoadingManifest,
  manifest,
  restoreState,
  isInitiatingRestore,
  onInitiateRestore,
  onCheckStatus,
  onDownloadRestore,
  showRestoreConfirm,
  setShowRestoreConfirm,
}: {
  onLoadManifest: () => void;
  isLoadingManifest: boolean;
  manifest: S3ManifestSummary | null;
  restoreState: S3RestoreState | null;
  isInitiatingRestore: boolean;
  onInitiateRestore: () => void;
  onCheckStatus: () => void;
  onDownloadRestore: () => void;
  showRestoreConfirm: boolean;
  setShowRestoreConfirm: (v: boolean) => void;
}) {
  return (
    <div className="py-3 border-t border-zinc-700 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-zinc-300">
          <CloudDownload className="w-4 h-4" />
          Restore from Backup
        </div>
        <button
          onClick={onLoadManifest}
          disabled={isLoadingManifest}
          className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-sky-400 hover:text-sky-300 hover:bg-sky-400/10 rounded transition-colors disabled:opacity-50"
        >
          {isLoadingManifest ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <RefreshCw className="w-3.5 h-3.5" />
          )}
          Check Backup Contents
        </button>
      </div>
      <p className="text-xs text-zinc-500">
        Fetches the backup index from S3 to show what's available to restore.
      </p>

      {manifest && (
        <div className="bg-zinc-900/50 rounded-lg p-3 space-y-2">
          <div className="text-xs text-zinc-400">
            Last backup: {manifest.last_backup_at ? formatRelativeTime(manifest.last_backup_at) : 'never'}
          </div>
          <div className="text-sm text-zinc-300">
            {manifest.file_count.toLocaleString()} files, {formatBytes(manifest.total_size_bytes)}
          </div>
          {Object.entries(manifest.by_category).length > 0 && (
            <div className="flex flex-wrap gap-3 text-xs text-zinc-400">
              {Object.entries(manifest.by_category).map(([cat, info]) => (
                <span key={cat}>
                  {cat}: {info.count} ({formatBytes(info.size_bytes)})
                </span>
              ))}
            </div>
          )}

          {/* Restore state */}
          {(!restoreState || restoreState.status === 'none') && (
            <div className="pt-2 space-y-2">
              <div className="flex items-center gap-2 text-xs text-amber-400">
                <AlertTriangle className="w-3.5 h-3.5" />
                Glacier retrieval takes 12-48 hours (Bulk tier)
              </div>
              <button
                onClick={onInitiateRestore}
                disabled={isInitiatingRestore}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 hover:bg-amber-500 disabled:bg-zinc-700 text-white text-sm rounded transition-colors"
              >
                {isInitiatingRestore ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <CloudDownload className="w-3.5 h-3.5" />
                )}
                Start Restore
              </button>
            </div>
          )}

          {restoreState?.status === 'retrieving' && (
            <div className="pt-2 space-y-2">
              <div className="flex items-center gap-2 text-sm text-amber-400">
                <Clock className="w-4 h-4" />
                Glacier retrieval in progress...
              </div>
              <div className="text-xs text-zinc-400">
                Files available: {restoreState.files_available || 0} / {restoreState.total_files || 0}
                {restoreState.initiated_at && (
                  <> (started {formatRelativeTime(restoreState.initiated_at)})</>
                )}
              </div>
              <button
                onClick={onCheckStatus}
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-sky-400 hover:text-sky-300 hover:bg-sky-400/10 rounded transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Check Status
              </button>
            </div>
          )}

          {restoreState?.status === 'available' && (
            <div className="pt-2 space-y-2">
              <div className="flex items-center gap-2 text-sm text-green-400">
                <CheckCircle className="w-4 h-4" />
                Files are ready for download
              </div>

              {!showRestoreConfirm ? (
                <button
                  onClick={() => setShowRestoreConfirm(true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 hover:bg-green-500 text-white text-sm rounded transition-colors"
                >
                  <CloudDownload className="w-3.5 h-3.5" />
                  Download & Restore
                </button>
              ) : (
                <div className="bg-red-900/20 border border-red-800 rounded-lg p-3 space-y-2">
                  <div className="flex items-center gap-2 text-sm text-red-400">
                    <AlertTriangle className="w-4 h-4" />
                    This will replace your current database
                  </div>
                  <p className="text-xs text-zinc-400">
                    A local safety backup will be created first. Existing files that match the backup will be skipped.
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={onDownloadRestore}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600 hover:bg-red-500 text-white text-sm rounded transition-colors"
                    >
                      Confirm Restore
                    </button>
                    <button
                      onClick={() => setShowRestoreConfirm(false)}
                      className="px-3 py-1.5 text-zinc-400 hover:text-zinc-300 text-sm rounded transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {restoreState?.status === 'complete' && (
            <div className="pt-2 flex items-center gap-2 text-sm text-green-400">
              <CheckCircle className="w-4 h-4" />
              Restore complete
            </div>
          )}
        </div>
      )}
    </div>
  );
}
