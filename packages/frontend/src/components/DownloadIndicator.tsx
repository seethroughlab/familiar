/**
 * Global download progress indicator.
 * Shows in the app header when downloads are in progress.
 * Includes iOS-specific warning about keeping the app open.
 */
import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Download, X, Check, AlertCircle, Loader2, ChevronDown, ChevronUp, Smartphone } from 'lucide-react';
import { useDownloadStore, type DownloadJob, restoreDownloadQueue } from '../stores/downloadStore';
import { isIOS } from '../utils/platform';

import { createLogger } from '../utils/logger';

const log = createLogger('DownloadIndicator');

function JobProgress({ job }: { job: DownloadJob }) {
  const { cancelDownload } = useDownloadStore();

  const completedCount = job.completedIds.length;
  const totalCount = job.trackIds.length;
  const progressPercent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

  return (
    <div className="flex items-center gap-3 p-2 bg-zinc-800 rounded-lg">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          {job.status === 'downloading' && (
            <Loader2 className="w-4 h-4 animate-spin text-blue-400 flex-shrink-0" />
          )}
          {job.status === 'queued' && (
            <Download className="w-4 h-4 text-zinc-400 flex-shrink-0" />
          )}
          {job.status === 'completed' && (
            <Check className="w-4 h-4 text-green-400 flex-shrink-0" />
          )}
          {job.status === 'failed' && (
            <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
          )}
          {job.status === 'cancelled' && (
            <X className="w-4 h-4 text-zinc-500 flex-shrink-0" />
          )}
          <span className="text-sm font-medium truncate">{job.name}</span>
        </div>
        {(job.status === 'downloading' || job.status === 'queued') && (
          <div className="mt-1">
            <div className="h-1 bg-zinc-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 transition-all duration-300"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
            <div className="text-xs text-zinc-500 mt-0.5">
              {completedCount}/{totalCount} tracks
            </div>
          </div>
        )}
        {job.status === 'completed' && (
          <div className="text-xs text-green-400 mt-0.5">
            Downloaded {totalCount} tracks
          </div>
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

export function DownloadIndicator() {
  const { jobs, getActiveJob } = useDownloadStore();
  const [expanded, setExpanded] = useState(false);
  const [showIOSWarning, setShowIOSWarning] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuPosition, setMenuPosition] = useState<{ top: number; right: number } | null>(null);

  // Restore download queue from IndexedDB on mount
  useEffect(() => {
    restoreDownloadQueue().catch((error) => {
      log.error('Failed to restore queue:', error);
    });
  }, []);

  // Check if we're on iOS and should show the warning
  useEffect(() => {
    setShowIOSWarning(isIOS());
  }, []);

  // Compute portal position from button rect
  useEffect(() => {
    if (!expanded || !buttonRef.current) {
      setMenuPosition(null);
      return;
    }
    const rect = buttonRef.current.getBoundingClientRect();
    setMenuPosition({
      top: rect.bottom + 8,
      right: window.innerWidth - rect.right,
    });
  }, [expanded]);

  // Close on click outside
  useEffect(() => {
    if (!expanded) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (
        buttonRef.current?.contains(e.target as Node) ||
        menuRef.current?.contains(e.target as Node)
      ) {
        return;
      }
      setExpanded(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [expanded]);

  // Get all active/queued/recent jobs
  const allJobs = Array.from(jobs.values());
  const activeJob = getActiveJob();
  const hasJobs = allJobs.length > 0;

  if (!hasJobs) {
    return null;
  }

  // Calculate overall progress
  const downloadingJobs = allJobs.filter(
    (j) => j.status === 'downloading' || j.status === 'queued'
  );
  const isDownloading = downloadingJobs.length > 0;

  const dropdown = expanded && menuPosition && createPortal(
    <div
      ref={menuRef}
      style={{ top: menuPosition.top, right: menuPosition.right }}
      className="fixed w-72 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl z-[60] p-2 space-y-2"
    >
      <div className="text-xs font-medium text-zinc-400 px-2 py-1">
        Downloads
      </div>
      {/* iOS warning banner */}
      {showIOSWarning && isDownloading && (
        <div className="flex items-start gap-2 p-2 bg-amber-500/10 border border-amber-500/30 rounded-lg">
          <Smartphone className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
          <div className="text-xs text-amber-200">
            <span className="font-medium">Keep Familiar open</span>
            <br />
            <span className="text-amber-300/80">
              iOS pauses downloads when you switch apps. Downloads will resume if interrupted.
            </span>
          </div>
        </div>
      )}
      {allJobs.map((job) => (
        <JobProgress key={job.id} job={job} />
      ))}
    </div>,
    document.body
  );

  return (
    <>
      <div className="relative">
        {/* Indicator button */}
        <button
          ref={buttonRef}
          onClick={() => setExpanded(!expanded)}
          className={`flex items-center gap-2 px-2 py-1.5 rounded-lg transition-colors ${
            isDownloading
              ? 'bg-blue-500/20 text-blue-400 hover:bg-blue-500/30'
              : 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
          }`}
          title={isDownloading ? 'Downloads in progress' : 'Downloads complete'}
        >
          {isDownloading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Check className="w-4 h-4" />
          )}
          <span className="text-xs font-medium hidden sm:inline">
            {isDownloading
              ? activeJob
                ? `${activeJob.completedIds.length}/${activeJob.trackIds.length}`
                : 'Downloading...'
              : 'Complete'}
          </span>
          {expanded ? (
            <ChevronUp className="w-3 h-3" />
          ) : (
            <ChevronDown className="w-3 h-3" />
          )}
        </button>
      </div>
      {dropdown}
    </>
  );
}
