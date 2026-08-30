/**
 * Background jobs in flight, on the Server destination.
 *
 * This is what `StatusMenu` was carrying that nothing else did. Of its four sections, three had
 * somewhere else to be — health polls from `WorkerAlert` and reports through `SystemStatus`,
 * mix-tape renders are watched by `MixTapeProgressWatcher` and listed by `MixTapesList`, and the
 * proposed-changes button linked to `/library/proposed-changes`, which `App.tsx` does not mount
 * (ADR-0080 points 4 and 5). Background jobs did not: `library_sync` has its own progress on the
 * Library dashboard, but **`artwork_fetch` and `s3_backup` had no indicator anywhere else**, so
 * deleting the menu without this would have taken two long-running jobs' only progress with it.
 *
 * **Renders its own `AdminSection`**, heading included, so that when nothing is running the whole
 * section is absent rather than a "JOBS" heading over empty space. Returning `null` from inside a
 * section the page had already opened is what produced exactly that, which is the empty-section
 * defect `ServerPage`'s own comment says this destination does not ship.
 */
import { useEffect } from 'react';
import { Image, Music, CloudUpload } from 'lucide-react';

import { AdminSection } from '../../screens/AdminPage';
import { useBackgroundJobsStore } from '../../stores/backgroundJobsStore';
import type { BackgroundJob } from '../../api';

const jobIcons: Record<BackgroundJob['type'], typeof Music> = {
  library_sync: Music,
  artwork_fetch: Image,
  s3_backup: CloudUpload,
};

const jobNames: Record<BackgroundJob['type'], string> = {
  library_sync: 'Library Sync',
  artwork_fetch: 'Artwork',
  s3_backup: 'S3 Backup',
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
    <div className="p-3 bg-zinc-800/50 rounded-lg">
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
      <div className="h-1.5 bg-zinc-700 rounded-full overflow-hidden">
        {progress && progress.total > 0 ? (
          <div className="h-full bg-blue-500 transition-all duration-300" style={{ width: `${percent}%` }} />
        ) : (
          <div className="h-full bg-blue-500 w-full animate-pulse" />
        )}
      </div>
    </div>
  );
}

export function BackgroundJobs() {
  const { jobs, activeCount, startPolling, stopPolling } = useBackgroundJobsStore();

  // The polling `StatusMenu` used to host. It is the only caller, as it was there.
  useEffect(() => {
    startPolling();
    return () => stopPolling();
  }, [startPolling, stopPolling]);

  if (activeCount === 0) return null;

  return (
    <AdminSection title="Jobs">
      {jobs.map((job) => <JobProgressBar key={job.type} job={job} />)}
    </AdminSection>
  );
}
