/**
 * StatusMenu — single consolidated status affordance for the content toolbar.
 *
 * Replaces the former row of five separate indicators (health, downloads,
 * background jobs, mix-tape renders, proposed changes). Always mounted so it can
 * host the polling/subscriptions; renders nothing when there is nothing to show.
 * When one or more categories are active it shows ONE button (colored by the
 * worst active severity, with a total count badge) that opens a single popover
 * containing a section per active category.
 */
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Activity, AlertCircle, AlertTriangle, Check, ChevronDown, Download, FileEdit,
  Image, ListMusic, Loader2, Music, CassetteTape, CloudUpload, Smartphone, X,
} from 'lucide-react';
import { useHealthStore } from '../stores/healthStore';
import { useBackgroundJobsStore } from '../stores/backgroundJobsStore';
import { useDownloadStore, type DownloadJob, restoreDownloadQueue } from '../stores/downloadStore';
import { useMixtapesList, PHASE_LABELS } from '../hooks/useMixtapes';
import { proposedChangesApi } from '../api';
import type { BackgroundJob, MixTape } from '../api';
import { queryKeys } from '../api/queryKeys';
import { useAppNavigation } from '../hooks/useAppNavigation';
import { isIOS } from '../utils/platform';
import { createLogger } from '../utils/logger';

const log = createLogger('StatusMenu');

// ---- Background jobs presentation --------------------------------------------

const jobIcons: Record<BackgroundJob['type'], typeof Music> = {
  library_sync: Music,
  artwork_fetch: Image,
  s3_backup: CloudUpload,
  spotify_matching: ListMusic,
};

const jobNames: Record<BackgroundJob['type'], string> = {
  library_sync: 'Library Sync',
  artwork_fetch: 'Artwork',
  s3_backup: 'S3 Backup',
  spotify_matching: 'Spotify Matching',
};

const jobPhaseLabels: Record<string, string> = {
  starting: 'Starting...',
  discovering: 'Discovering files',
  reading: 'Reading metadata',
  features: 'Extracting features',
  embeddings: 'Generating embeddings',
  melodic: 'Melodic analysis',
  backfill: 'Backfill analysis',
  complete: 'Complete',
};

function JobProgressBar({ job }: { job: BackgroundJob }) {
  const Icon = jobIcons[job.type];
  const progress = job.progress;
  const percent = progress && progress.total > 0
    ? Math.round((progress.current / progress.total) * 100)
    : null;
  const queueMatch = job.message?.match(/\((\d+) queued\)/);
  const queuedCount = queueMatch ? parseInt(queueMatch[1], 10) : null;

  return (
    <div className="p-3 bg-zinc-700/50 rounded-lg">
      <div className="flex items-center gap-2 mb-1">
        <Icon className="w-4 h-4 text-blue-400" />
        <span className="text-sm font-medium text-white">{jobNames[job.type]}</span>
        <span className="text-xs text-zinc-400 ml-auto">
          {progress && progress.total > 0 && `${progress.current}/${progress.total}`}
          {queuedCount !== null && queuedCount > 0 && ` (${queuedCount} queued)`}
        </span>
      </div>
      {job.type === 'library_sync' && job.phase && jobPhaseLabels[job.phase] && (
        <p className="text-xs text-zinc-400 mb-1">{jobPhaseLabels[job.phase]}</p>
      )}
      {job.current_item && (
        <p className="text-xs text-zinc-400 mb-2 truncate">{job.current_item}</p>
      )}
      <div className="h-1.5 bg-zinc-600 rounded-full overflow-hidden">
        {progress && progress.total > 0 ? (
          <div className="h-full bg-blue-500 transition-all duration-300" style={{ width: `${percent}%` }} />
        ) : (
          <div className="h-full bg-blue-500 w-full animate-pulse" />
        )}
      </div>
    </div>
  );
}

// ---- Download presentation ---------------------------------------------------

function DownloadRow({ job }: { job: DownloadJob }) {
  const { cancelDownload } = useDownloadStore();
  const completedCount = job.completedIds.length;
  const totalCount = job.trackIds.length;
  const progressPercent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

  return (
    <div className="flex items-center gap-3 p-2 bg-zinc-800 rounded-lg">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          {job.status === 'downloading' && <Loader2 className="w-4 h-4 animate-spin text-blue-400 flex-shrink-0" />}
          {job.status === 'queued' && <Download className="w-4 h-4 text-zinc-400 flex-shrink-0" />}
          {job.status === 'completed' && <Check className="w-4 h-4 text-green-400 flex-shrink-0" />}
          {job.status === 'failed' && <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />}
          {job.status === 'cancelled' && <X className="w-4 h-4 text-zinc-500 flex-shrink-0" />}
          <span className="text-sm font-medium truncate">{job.name}</span>
        </div>
        {(job.status === 'downloading' || job.status === 'queued') && (
          <div className="mt-1">
            <div className="h-1 bg-zinc-700 rounded-full overflow-hidden">
              <div className="h-full bg-blue-500 transition-all duration-300" style={{ width: `${progressPercent}%` }} />
            </div>
            <div className="text-xs text-zinc-500 mt-0.5">
              {completedCount}/{totalCount} tracks
              {/* A throttled download is deliberately slow, not stuck. Saying so keeps
                  it from reading as a hang while music is playing. */}
              {job.throttled && job.status === 'downloading' && (
                <span className="text-amber-400/80"> · slowed while playing</span>
              )}
            </div>
          </div>
        )}
        {job.status === 'completed' && (
          <div className="text-xs text-green-400 mt-0.5">Downloaded {totalCount} tracks</div>
        )}
        {job.status === 'failed' && job.error && (
          <div className="text-xs text-red-400 mt-0.5">{job.error}</div>
        )}
      </div>
      {(job.status === 'downloading' || job.status === 'queued') && (
        <button
          onClick={() => cancelDownload(job.id)}
          className="p-1.5 hover:bg-zinc-700 rounded transition-colors"
          title="Cancel download"
        >
          <X className="w-4 h-4 text-zinc-400" />
        </button>
      )}
    </div>
  );
}

// ---- Mix-tape render presentation --------------------------------------------

function mixtapeInFlight(mt: MixTape): boolean {
  return mt.status === 'pending' || mt.status === 'rendering';
}

function MixTapeRow({ mt }: { mt: MixTape }) {
  const phase = mt.progress?.phase ?? mt.status;
  const phaseLabel = PHASE_LABELS[phase] ?? phase;
  const percent = typeof mt.progress?.progress === 'number' ? mt.progress.progress : null;

  return (
    <div className="p-3 bg-zinc-700/50 rounded-lg">
      <div className="flex items-center gap-2 mb-1">
        <CassetteTape className="w-4 h-4 text-orange-400" />
        <span className="text-sm font-medium text-white truncate">{mt.name}</span>
        {percent !== null && <span className="text-xs text-zinc-400 ml-auto">{percent}%</span>}
      </div>
      <p className="text-xs text-zinc-400 mb-2">{phaseLabel}</p>
      <div className="h-1.5 bg-zinc-600 rounded-full overflow-hidden">
        {percent !== null ? (
          <div className="h-full bg-orange-500 transition-all duration-300" style={{ width: `${percent}%` }} />
        ) : (
          <div className="h-full bg-orange-500 w-full animate-pulse" />
        )}
      </div>
    </div>
  );
}

// ---- Popover section wrapper -------------------------------------------------

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs font-medium text-zinc-400 uppercase tracking-wider px-1">
        {icon}
        {title}
      </div>
      {children}
    </div>
  );
}

// ---- Main component ----------------------------------------------------------

export function StatusMenu() {
  const { navigateToLibrary } = useAppNavigation();

  // Health
  const { status: healthStatus, warnings, startPolling: startHealth, stopPolling: stopHealth } = useHealthStore();
  // Background jobs
  const { jobs: bgJobs, activeCount: bgActiveCount, startPolling: startJobs, stopPolling: stopJobs } = useBackgroundJobsStore();
  // Downloads
  const { jobs: downloadJobsMap } = useDownloadStore();
  // Mix-tape renders
  const { data: mixtapes } = useMixtapesList();
  // Proposed changes
  const { data: proposedStats } = useQuery({
    queryKey: queryKeys.proposedChanges.stats,
    queryFn: () => proposedChangesApi.getStats(),
    refetchInterval: 30000,
  });

  const [open, setOpen] = useState(false);
  const [showIOSWarning, setShowIOSWarning] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [menuPosition, setMenuPosition] = useState<{ top: number; right: number } | null>(null);

  // Host the polling/subscriptions that the old indicators owned.
  useEffect(() => {
    startHealth();
    startJobs();
    restoreDownloadQueue().catch((error) => log.error('Failed to restore queue:', error));
    return () => {
      stopHealth();
      stopJobs();
    };
  }, [startHealth, stopHealth, startJobs, stopJobs]);

  useEffect(() => {
    setShowIOSWarning(isIOS());
  }, []);

  // Derive per-category active state.
  const healthActive = healthStatus !== 'healthy' && healthStatus !== 'loading';
  const healthError = healthStatus === 'unhealthy' || healthStatus === 'error';

  const downloadJobs = Array.from(downloadJobsMap.values());
  const downloadsDownloading = downloadJobs.some((j) => j.status === 'downloading' || j.status === 'queued');
  const downloadsActive = downloadJobs.length > 0;

  const inFlightMixtapes = (mixtapes ?? []).filter(mixtapeInFlight);
  const mixtapeActive = inFlightMixtapes.length > 0;

  const proposedCount = proposedStats?.pending ?? 0;
  const proposedActive = proposedCount > 0;

  const anyInProgress = bgActiveCount > 0 || downloadsDownloading || mixtapeActive;
  const anyActive = healthActive || downloadsActive || bgActiveCount > 0 || mixtapeActive || proposedActive;

  // Close popover automatically once nothing is active.
  useEffect(() => {
    if (!anyActive && open) setOpen(false);
  }, [anyActive, open]);

  // Close on click outside.
  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (buttonRef.current?.contains(e.target as Node) || popoverRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  // Position popover under the button.
  useEffect(() => {
    if (!open || !buttonRef.current) {
      setMenuPosition(null);
      return;
    }
    const rect = buttonRef.current.getBoundingClientRect();
    setMenuPosition({ top: rect.bottom + 8, right: window.innerWidth - rect.right });
  }, [open]);

  if (!anyActive) return null;

  // Worst-severity color + icon for the single button.
  const colorClasses = healthError
    ? 'text-red-400 hover:text-red-300 hover:bg-red-900/30'
    : healthActive || proposedActive
    ? 'text-amber-400 hover:text-amber-300 hover:bg-amber-900/30'
    : anyInProgress
    ? 'text-blue-400 hover:text-blue-300 hover:bg-blue-900/30'
    : 'text-green-400 hover:text-green-300 hover:bg-green-900/30';

  const ButtonIcon = anyInProgress
    ? Loader2
    : healthError
    ? AlertCircle
    : healthActive
    ? AlertTriangle
    : proposedActive
    ? FileEdit
    : downloadsActive
    ? Check
    : Activity;

  const totalCount =
    bgActiveCount + (downloadsDownloading ? 1 : 0) + inFlightMixtapes.length + proposedCount + warnings.length;

  const popover = open && menuPosition && createPortal(
    <div
      ref={popoverRef}
      style={{ top: menuPosition.top, right: menuPosition.right }}
      className="fixed w-80 max-h-[70vh] overflow-y-auto bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl z-[60] p-3 space-y-4"
    >
      <div className="flex items-center justify-between">
        <h3 className="font-medium text-white">Status</h3>
        <button onClick={() => setOpen(false)} className="p-1 hover:bg-zinc-700 rounded transition-colors">
          <X className="w-4 h-4 text-zinc-400" />
        </button>
      </div>

      {healthActive && (
        <Section
          icon={healthError ? <AlertCircle className="w-3.5 h-3.5 text-red-400" /> : <AlertTriangle className="w-3.5 h-3.5 text-yellow-400" />}
          title={healthError ? 'System Issues' : 'Warnings'}
        >
          {warnings.length > 0 ? (
            warnings.map((warning, i) => (
              <div key={i} className={`p-2 rounded text-sm ${healthError ? 'bg-red-900/30 text-red-200' : 'bg-yellow-900/30 text-yellow-200'}`}>
                {warning}
              </div>
            ))
          ) : (
            <p className="text-sm text-zinc-400">
              {healthError
                ? 'A required service is not responding. View System Status in Settings for details.'
                : 'System is operational but may need attention. View System Status in Settings for details.'}
            </p>
          )}
          <button
            onClick={() => { setOpen(false); window.dispatchEvent(new CustomEvent('navigate-to-settings')); }}
            className="text-sm text-blue-400 hover:text-blue-300"
          >
            View System Status
          </button>
        </Section>
      )}

      {downloadsActive && (
        <Section icon={<Download className="w-3.5 h-3.5 text-blue-400" />} title="Downloads">
          {showIOSWarning && downloadsDownloading && (
            <div className="flex items-start gap-2 p-2 bg-amber-500/10 border border-amber-500/30 rounded-lg">
              <Smartphone className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
              <div className="text-xs text-amber-200">
                <span className="font-medium">Keep Familiar open</span>
                <br />
                <span className="text-amber-300/80">iOS pauses downloads when you switch apps. Downloads will resume if interrupted.</span>
              </div>
            </div>
          )}
          {downloadJobs.map((job) => <DownloadRow key={job.id} job={job} />)}
        </Section>
      )}

      {bgActiveCount > 0 && (
        <Section icon={<Loader2 className="w-3.5 h-3.5 text-blue-400 animate-spin" />} title="Background Jobs">
          {bgJobs.map((job) => <JobProgressBar key={job.type} job={job} />)}
        </Section>
      )}

      {mixtapeActive && (
        <Section icon={<CassetteTape className="w-3.5 h-3.5 text-orange-400" />} title="Mix Tapes Rendering">
          {inFlightMixtapes.map((mt) => <MixTapeRow key={mt.id} mt={mt} />)}
        </Section>
      )}

      {proposedActive && (
        <Section icon={<FileEdit className="w-3.5 h-3.5 text-amber-400" />} title="Proposed Changes">
          <button
            onClick={() => { setOpen(false); navigateToLibrary({ browser: 'proposed-changes' }); }}
            className="w-full p-2 bg-amber-900/20 hover:bg-amber-900/30 rounded-lg text-sm text-amber-200 text-left transition-colors"
          >
            {proposedCount} change{proposedCount !== 1 ? 's' : ''} pending review — click to review
          </button>
        </Section>
      )}
    </div>,
    document.body,
  );

  return (
    <>
      <button
        ref={buttonRef}
        onClick={() => setOpen((v) => !v)}
        className={`relative p-2 rounded-lg transition-colors flex items-center gap-1 ${colorClasses}`}
        title="Status"
      >
        <ButtonIcon className={`w-5 h-5 ${anyInProgress ? 'animate-spin' : ''}`} />
        <ChevronDown className="w-3 h-3" />
        {totalCount > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[1rem] h-4 px-1 bg-current text-zinc-900 text-xs rounded-full flex items-center justify-center font-medium">
            {totalCount > 99 ? '99+' : totalCount}
          </span>
        )}
      </button>
      {popover}
    </>
  );
}
