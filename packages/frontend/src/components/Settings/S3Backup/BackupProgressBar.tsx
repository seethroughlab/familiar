import type { S3BackupProgress } from '../../../api';
import { formatBytes } from './utils';

export function BackupProgressBar({ progress }: { progress: S3BackupProgress }) {
  const pct = progress.files_total > 0
    ? Math.round((progress.files_uploaded / progress.files_total) * 100)
    : 0;

  const phaseLabels: Record<string, string> = {
    starting: 'Starting...',
    database: 'Backing up database...',
    settings: 'Backing up settings...',
    audio: 'Uploading audio files...',
    artwork: 'Uploading artwork...',
    videos: 'Uploading videos...',
    profiles: 'Uploading profiles...',
    manifest: 'Writing manifest...',
  };

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs text-zinc-400">
        <span>{phaseLabels[progress.phase] || progress.phase}</span>
        <span>
          {progress.files_uploaded}/{progress.files_total} files
          {' '}({formatBytes(progress.bytes_uploaded)})
        </span>
      </div>
      <div className="w-full bg-zinc-700 rounded-full h-1.5">
        <div
          className="bg-sky-500 h-1.5 rounded-full transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      {progress.current_file && (
        <div className="text-xs text-zinc-500 truncate">
          {progress.current_file}
        </div>
      )}
    </div>
  );
}
