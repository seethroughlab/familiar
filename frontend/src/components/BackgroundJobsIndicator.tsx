import { useEffect, useState, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, X, Music, Radio, Disc, Image } from 'lucide-react';
import { useBackgroundJobsStore } from '../stores/backgroundJobsStore';
import type { BackgroundJob } from '../api/client';

// Icons for each job type
const jobIcons: Record<BackgroundJob['type'], typeof Music> = {
  library_sync: Music,
  spotify_sync: Radio,
  new_releases: Disc,
  artwork_fetch: Image,
};

// Friendly names for job types
const jobNames: Record<BackgroundJob['type'], string> = {
  library_sync: 'Library Sync',
  spotify_sync: 'Spotify Sync',
  new_releases: 'New Releases',
  artwork_fetch: 'Artwork',
};

const phaseLabels: Record<string, string> = {
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

  // Extract queue count from message for artwork jobs (format: "Fetching artwork (X queued)")
  const queueMatch = job.message?.match(/\((\d+) queued\)/);
  const queuedCount = queueMatch ? parseInt(queueMatch[1], 10) : null;

  return (
    <div className="p-3 bg-zinc-700/50 rounded-lg">
      <div className="flex items-center gap-2 mb-1">
        <Icon className="w-4 h-4 text-blue-400" />
        <span className="text-sm font-medium text-white">
          {jobNames[job.type]}
        </span>
        <span className="text-xs text-zinc-400 ml-auto">
          {progress && progress.total > 0 && `${progress.current}/${progress.total}`}
          {queuedCount !== null && queuedCount > 0 && ` (${queuedCount} queued)`}
        </span>
      </div>

      {job.type === 'library_sync' && job.phase && phaseLabels[job.phase] && (
        <p className="text-xs text-zinc-400 mb-1">
          {phaseLabels[job.phase]}
        </p>
      )}

      {job.current_item && (
        <p className="text-xs text-zinc-400 mb-2 truncate">
          {job.current_item}
        </p>
      )}

      {progress && progress.total > 0 && (
        <div className="h-1.5 bg-zinc-600 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 transition-all duration-300"
            style={{ width: `${percent}%` }}
          />
        </div>
      )}

      {!progress && (
        <div className="h-1.5 bg-zinc-600 rounded-full overflow-hidden">
          <div className="h-full bg-blue-500 w-full animate-pulse" />
        </div>
      )}
    </div>
  );
}

export function BackgroundJobsIndicator() {
  const { jobs, activeCount, startPolling, stopPolling } = useBackgroundJobsStore();
  const [showPopover, setShowPopover] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Start polling on mount
  useEffect(() => {
    startPolling();
    return () => stopPolling();
  }, [startPolling, stopPolling]);

  // Close popover when clicking outside
  useEffect(() => {
    if (!showPopover) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (
        buttonRef.current?.contains(e.target as Node) ||
        popoverRef.current?.contains(e.target as Node)
      ) {
        return;
      }
      setShowPopover(false);
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showPopover]);

  // Compute popover position from button rect
  const [menuPosition, setMenuPosition] = useState<{ top: number; right: number } | null>(null);
  useEffect(() => {
    if (!showPopover || !buttonRef.current) {
      setMenuPosition(null);
      return;
    }
    const rect = buttonRef.current.getBoundingClientRect();
    setMenuPosition({
      top: rect.bottom + 8,
      right: window.innerWidth - rect.right,
    });
  }, [showPopover]);

  // Don't render if no active jobs
  if (activeCount === 0) {
    return null;
  }

  const popover = showPopover && menuPosition && createPortal(
    <div
      ref={popoverRef}
      style={{ top: menuPosition.top, right: menuPosition.right }}
      className="fixed w-80 bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl z-[60]"
    >
      <div className="p-3 border-b border-zinc-700 flex items-center justify-between">
        <h3 className="font-medium text-white flex items-center gap-2">
          <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
          Background Jobs
        </h3>
        <button
          onClick={() => setShowPopover(false)}
          className="p-1 hover:bg-zinc-700 rounded transition-colors"
        >
          <X className="w-4 h-4 text-zinc-400" />
        </button>
      </div>

      <div className="p-3 space-y-2 max-h-64 overflow-y-auto">
        {jobs.map((job) => (
          <JobProgressBar key={job.type} job={job} />
        ))}
      </div>
    </div>,
    document.body
  );

  return (
    <>
      <div className="relative">
        <button
          ref={buttonRef}
          onClick={() => setShowPopover(!showPopover)}
          className="p-2 rounded-lg transition-colors text-blue-400 hover:text-blue-300 hover:bg-blue-900/30"
          title={`${activeCount} background job${activeCount !== 1 ? 's' : ''} running`}
        >
          <Loader2 className="w-5 h-5 animate-spin" />
          {activeCount > 1 && (
            <span className="absolute -top-1 -right-1 w-4 h-4 bg-blue-500 text-white text-xs rounded-full flex items-center justify-center">
              {activeCount}
            </span>
          )}
        </button>
      </div>
      {popover}
    </>
  );
}
