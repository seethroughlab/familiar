import { useState } from 'react';
import { History, CheckCircle, XCircle } from 'lucide-react';
import type { S3BackupHistoryEntry } from '../../../api';
import { formatRelativeTime, formatBytes, formatDuration } from './utils';

export function BackupHistory({ entries }: { entries: S3BackupHistoryEntry[] }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? entries : entries.slice(0, 3);

  return (
    <div className="py-3 border-t border-zinc-700">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-sm text-zinc-300">
          <History className="w-4 h-4" />
          Backup History
        </div>
        {entries.length > 3 && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-sky-400 hover:text-sky-300"
          >
            {expanded ? 'Show less' : `Show all (${entries.length})`}
          </button>
        )}
      </div>
      <div className="space-y-1">
        {visible.map((entry, i) => (
          <div key={i} className="flex items-center justify-between text-xs text-zinc-400">
            <div className="flex items-center gap-2">
              {entry.status === 'success' ? (
                <CheckCircle className="w-3 h-3 text-green-400" />
              ) : (
                <XCircle className="w-3 h-3 text-red-400" />
              )}
              <span>{formatRelativeTime(entry.timestamp)}</span>
            </div>
            <span>
              {entry.files_uploaded} uploaded, {entry.files_skipped} skipped
              {' — '}{formatBytes(entry.bytes_uploaded)}
              {' — '}{formatDuration(entry.duration_seconds)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
