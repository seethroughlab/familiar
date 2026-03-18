/**
 * S3 Glacier Deep Archive backup settings component.
 *
 * Covers all phases: credentials, cost estimate, manual/scheduled backup,
 * backup history, and restore (Glacier retrieval + download).
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Cloud,
  CloudUpload,
  Shield,
  ShieldCheck,
  ShieldX,
  Loader2,
  CheckCircle,
  XCircle,
  Square,
} from 'lucide-react';
import {
  appSettingsApi,
  s3BackupApi,
  type AppSettingsResponse,
  type S3ValidateResponse,
  type S3CostEstimate,
  type S3BackupStatus,
  type S3BackupProgress,
  type S3BackupHistoryEntry,
  type S3ManifestSummary,
  type S3RestoreState,
} from '../../../api';
import { showSuccess, showError, showWarning } from '../../../stores/toastStore';
import { createLogger } from '../../../utils/logger';
import { formatRelativeTime, formatBytes, formatDuration } from './utils';
import { CostEstimateCard } from './CostEstimateCard';
import { BackupProgressBar } from './BackupProgressBar';
import { BackupHistory } from './BackupHistory';
import { RestoreSection } from './RestoreSection';

const log = createLogger('S3BackupSettings');

function ValidationResult({ validation }: { validation: S3ValidateResponse }) {
  if (validation.valid) {
    return (
      <div className="flex items-center gap-1.5 text-green-400 text-sm">
        <ShieldCheck className="w-4 h-4" />
        All permissions verified
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {validation.error && (
        <div className="flex items-center gap-1.5 text-red-400 text-xs">
          <ShieldX className="w-3.5 h-3.5" />
          {validation.error}
        </div>
      )}
      <div className="flex gap-3 text-xs">
        {Object.entries(validation.permissions).map(([perm, ok]) => (
          <div key={perm} className={`flex items-center gap-1 ${ok ? 'text-green-400' : 'text-red-400'}`}>
            {ok ? <CheckCircle className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
            {perm}
          </div>
        ))}
      </div>
    </div>
  );
}

export function S3BackupSettings() {
  // Settings state
  const [settings, setSettings] = useState<AppSettingsResponse | null>(null);
  const [schedule, setSchedule] = useState('weekly');
  const [enabled, setEnabled] = useState(false);

  // Validation state
  const [validation, setValidation] = useState<S3ValidateResponse | null>(null);
  const [isValidating, setIsValidating] = useState(false);

  // Cost estimate
  const [costEstimate, setCostEstimate] = useState<S3CostEstimate | null>(null);
  const [isEstimating, setIsEstimating] = useState(false);

  // Backup state
  const [backupStatus, setBackupStatus] = useState<S3BackupStatus | null>(null);
  const [backupProgress, setBackupProgress] = useState<S3BackupProgress | null>(null);
  const [history, setHistory] = useState<S3BackupHistoryEntry[]>([]);
  const progressPollRef = useRef<NodeJS.Timeout | null>(null);

  // Restore state
  const [manifest, setManifest] = useState<S3ManifestSummary | null>(null);
  const [restoreState, setRestoreState] = useState<S3RestoreState | null>(null);
  const [isLoadingManifest, setIsLoadingManifest] = useState(false);
  const [isInitiatingRestore, setIsInitiatingRestore] = useState(false);
  const [showRestoreConfirm, setShowRestoreConfirm] = useState(false);

  // Loading
  const [isSaving, setIsSaving] = useState(false);

  // Load initial settings
  useEffect(() => {
    loadSettings();
    loadCostEstimate();
  }, []);

  const loadSettings = async () => {
    try {
      const data = await appSettingsApi.get();
      setSettings(data);
      setSchedule(data.s3_backup_schedule || 'weekly');
      setEnabled(data.s3_backup_enabled);
    } catch (error) {
      log.error('Failed to load settings:', error);
    }
  };

  const loadCostEstimate = async () => {
    setIsEstimating(true);
    try {
      const data = await s3BackupApi.getEstimate();
      setCostEstimate(data);
    } catch (error) {
      log.error('Failed to load cost estimate:', error);
    } finally {
      setIsEstimating(false);
    }
  };

  const loadBackupStatus = useCallback(async () => {
    try {
      const [status, hist] = await Promise.all([
        s3BackupApi.getStatus(),
        s3BackupApi.getHistory(),
      ]);
      setBackupStatus(status);
      setHistory(hist);

      if (status.is_running && status.progress) {
        setBackupProgress(status.progress);
        startProgressPolling();
      }
    } catch (error) {
      log.error('Failed to load backup status:', error);
    }
  }, []);

  useEffect(() => {
    if (enabled && settings?.s3_backup_bucket) {
      loadBackupStatus();
    }
  }, [enabled, settings?.s3_backup_bucket, loadBackupStatus]);

  // Progress polling
  const startProgressPolling = useCallback(() => {
    if (progressPollRef.current) return;
    progressPollRef.current = setInterval(async () => {
      try {
        const progress = await s3BackupApi.getProgress();
        setBackupProgress(progress);
        if (progress.status !== 'running') {
          stopProgressPolling();
          loadBackupStatus();
          if (progress.status === 'complete') {
            showSuccess('Backup completed successfully');
          } else if (progress.status === 'error') {
            showError(`Backup failed: ${progress.error || 'Unknown error'}`);
          }
        }
      } catch (error) {
        log.error('Failed to poll progress:', error);
      }
    }, 2000);
  }, []);

  const stopProgressPolling = useCallback(() => {
    if (progressPollRef.current) {
      clearInterval(progressPollRef.current);
      progressPollRef.current = null;
    }
  }, []);

  useEffect(() => () => stopProgressPolling(), [stopProgressPolling]);

  // Handlers
  const handleValidate = async () => {
    if (!settings?.s3_backup_bucket) {
      showWarning('No bucket configured in environment');
      return;
    }
    setIsValidating(true);
    setValidation(null);
    try {
      const result = await s3BackupApi.validate({
        bucket: settings.s3_backup_bucket,
        region: settings.s3_backup_region || 'us-east-1',
        prefix: settings.s3_backup_prefix || '',
      });
      setValidation(result);
      if (result.valid) {
        showSuccess('AWS credentials validated successfully');
      } else {
        showError(result.error || 'Credential validation failed');
      }
    } catch {
      showError('Failed to validate credentials');
    } finally {
      setIsValidating(false);
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await appSettingsApi.update({
        s3_backup_schedule: schedule,
        s3_backup_enabled: enabled,
      });
      showSuccess('S3 backup settings saved');
      loadSettings();
    } catch {
      showError('Failed to save settings');
    } finally {
      setIsSaving(false);
    }
  };

  const handleBackupNow = async () => {
    try {
      const result = await s3BackupApi.runBackup();
      if (result.status === 'started') {
        showSuccess('Backup started');
        setBackupProgress({
          status: 'running', phase: 'starting', files_total: 0,
          files_uploaded: 0, files_skipped: 0, bytes_uploaded: 0,
          current_file: null, started_at: new Date().toISOString(), error: null,
        });
        startProgressPolling();
      } else if (result.status === 'already_running') {
        showWarning('A backup is already in progress');
      }
    } catch {
      showError('Failed to start backup');
    }
  };

  const handleCancelBackup = async () => {
    try {
      await s3BackupApi.cancelBackup();
      showSuccess('Backup cancellation requested');
    } catch {
      showError('Failed to cancel backup');
    }
  };

  const handleLoadManifest = async () => {
    setIsLoadingManifest(true);
    try {
      const [m, rs] = await Promise.all([
        s3BackupApi.getManifest(),
        s3BackupApi.getRestoreStatus(),
      ]);
      setManifest(m);
      setRestoreState(rs);
    } catch {
      showError('Failed to load backup manifest');
    } finally {
      setIsLoadingManifest(false);
    }
  };

  const handleInitiateRestore = async () => {
    setIsInitiatingRestore(true);
    try {
      const result = await s3BackupApi.initiateRestore();
      setRestoreState(result);
      showSuccess('Glacier retrieval initiated. This typically takes 12-48 hours.');
    } catch {
      showError('Failed to initiate restore');
    } finally {
      setIsInitiatingRestore(false);
    }
  };

  const handleCheckRestoreStatus = async () => {
    try {
      const result = await s3BackupApi.checkRestoreAvailability();
      setRestoreState(result);
      if (result.status === 'available') {
        showSuccess('Files are available for download!');
      }
    } catch {
      showError('Failed to check restore status');
    }
  };

  const handleDownloadRestore = async () => {
    try {
      const result = await s3BackupApi.downloadAndRestore(true);
      if (result.status === 'started') {
        showSuccess('Restore download started');
        setShowRestoreConfirm(false);
        startProgressPolling();
      }
    } catch {
      showError('Failed to start restore');
    }
  };

  const isRunning = backupProgress?.status === 'running';

  return (
    <div className="bg-zinc-800/50 rounded-lg p-4">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <Cloud className="w-5 h-5 text-sky-400" />
        <div>
          <h4 className="font-medium text-white">Cloud Backup</h4>
          <p className="text-xs text-zinc-400">
            S3 Glacier Deep Archive — ~$1/TB/month
          </p>
        </div>
      </div>

      <div className="space-y-4">
        {/* Cost Estimate (always visible) */}
        <CostEstimateCard estimate={costEstimate} isLoading={isEstimating} />

        {/* Configuration Status (read-only from env) */}
        <div className="space-y-3 py-3 border-t border-zinc-700">
          <div className="bg-zinc-900/50 rounded-lg p-3 space-y-2">
            <div className="grid grid-cols-3 gap-3 text-xs">
              <div>
                <span className="text-zinc-500">Bucket</span>
                <p className="text-zinc-300 font-mono mt-0.5">
                  {settings?.s3_backup_bucket || <span className="text-zinc-600 italic">not set</span>}
                </p>
              </div>
              <div>
                <span className="text-zinc-500">Region</span>
                <p className="text-zinc-300 font-mono mt-0.5">
                  {settings?.s3_backup_region || <span className="text-zinc-600 italic">not set</span>}
                </p>
              </div>
              <div>
                <span className="text-zinc-500">Prefix</span>
                <p className="text-zinc-300 font-mono mt-0.5">
                  {settings?.s3_backup_prefix || <span className="text-zinc-600 italic">none</span>}
                </p>
              </div>
            </div>
            <p className="text-xs text-zinc-600">
              Configure via <code className="bg-zinc-800 px-1 rounded">S3_BACKUP_BUCKET</code>, <code className="bg-zinc-800 px-1 rounded">S3_BACKUP_REGION</code>, <code className="bg-zinc-800 px-1 rounded">S3_BACKUP_PREFIX</code> in docker/.env
            </p>
          </div>

          {/* AWS Credentials Status */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {settings?.s3_backup_configured ? (
                <ShieldCheck className="w-4 h-4 text-green-400" />
              ) : (
                <ShieldX className="w-4 h-4 text-zinc-500" />
              )}
              <div>
                <p className="text-sm text-white">AWS Credentials</p>
                <p className="text-xs text-zinc-500">
                  {settings?.s3_backup_configured
                    ? 'Configured via environment'
                    : <>Set <code className="bg-zinc-900 px-1 rounded">S3_BACKUP_ACCESS_KEY_ID</code> and <code className="bg-zinc-900 px-1 rounded">S3_BACKUP_SECRET_ACCESS_KEY</code> in docker/.env</>}
                </p>
              </div>
            </div>
          </div>

          {/* Validate Button */}
          <div className="flex items-center gap-3">
            <button
              onClick={handleValidate}
              disabled={isValidating || !settings?.s3_backup_bucket || !settings?.s3_backup_configured}
              className="flex items-center gap-2 px-3 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm rounded transition-colors"
            >
              {isValidating ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Shield className="w-4 h-4" />
              )}
              Validate
            </button>

            {validation && (
              <ValidationResult validation={validation} />
            )}
          </div>
        </div>

        {/* Schedule & Enable */}
        <div className="flex items-center justify-between py-3 border-t border-zinc-700">
          <div className="flex items-center gap-3">
            <div>
              <label className="block text-xs text-zinc-400 mb-1">Schedule</label>
              <select
                value={schedule}
                onChange={(e) => setSchedule(e.target.value)}
                className="bg-zinc-900 border border-zinc-700 rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-sky-500"
              >
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </select>
            </div>

            <label className="relative inline-flex items-center gap-2 cursor-pointer mt-4">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                disabled={!settings?.s3_backup_configured && !settings?.s3_backup_enabled}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-sky-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-sky-500 peer-disabled:opacity-50" />
              <span className="text-sm text-zinc-300">Enable</span>
            </label>
          </div>

          <button
            onClick={handleSave}
            disabled={isSaving}
            className="flex items-center gap-2 px-4 py-1.5 bg-green-600 hover:bg-green-500 disabled:bg-zinc-700 text-white text-sm rounded transition-colors"
          >
            {isSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            Save
          </button>
        </div>

        {/* Backup Controls (only when configured) */}
        {enabled && settings?.s3_backup_bucket && (
          <>
            <div className="py-3 border-t border-zinc-700 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-zinc-300">Manual Backup</span>
                <div className="flex items-center gap-2">
                  {isRunning ? (
                    <button
                      onClick={handleCancelBackup}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600/20 hover:bg-red-600/30 text-red-400 text-sm rounded transition-colors"
                    >
                      <Square className="w-3.5 h-3.5" />
                      Cancel
                    </button>
                  ) : (
                    <button
                      onClick={handleBackupNow}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-sky-600 hover:bg-sky-500 text-white text-sm rounded transition-colors"
                    >
                      <CloudUpload className="w-3.5 h-3.5" />
                      Back Up Now
                    </button>
                  )}
                </div>
              </div>

              {/* Progress */}
              {backupProgress && backupProgress.status === 'running' && (
                <BackupProgressBar progress={backupProgress} />
              )}

              {/* Last backup */}
              {backupStatus?.last_backup && (
                <div className="text-xs text-zinc-400">
                  Last backup: {formatRelativeTime(backupStatus.last_backup.timestamp)}
                  {' — '}
                  {backupStatus.last_backup.files_uploaded} files uploaded,{' '}
                  {formatBytes(backupStatus.last_backup.bytes_uploaded)},
                  took {formatDuration(backupStatus.last_backup.duration_seconds)}
                </div>
              )}
            </div>

            {/* History */}
            {history.length > 0 && (
              <BackupHistory entries={history} />
            )}

            {/* Restore Section */}
            <RestoreSection
              onLoadManifest={handleLoadManifest}
              isLoadingManifest={isLoadingManifest}
              manifest={manifest}
              restoreState={restoreState}
              isInitiatingRestore={isInitiatingRestore}
              onInitiateRestore={handleInitiateRestore}
              onCheckStatus={handleCheckRestoreStatus}
              onDownloadRestore={handleDownloadRestore}
              showRestoreConfirm={showRestoreConfirm}
              setShowRestoreConfirm={setShowRestoreConfirm}
            />
          </>
        )}
      </div>
    </div>
  );
}
