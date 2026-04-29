/**
 * Mix Tapes list view — every mixtape the current profile has rendered.
 *
 * Each entry shows the cover thumbnail (loaded straight from the bundle's
 * embedded MP3 cover via the cover_path on the server), name, source
 * playlist, status, and Download / Delete actions.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { CassetteTape, Download, Loader2, Trash2 } from 'lucide-react';
import { mixtapesApi, type MixTape } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { showError, showSuccess } from '../../stores/toastStore';

function StatusBadge({ status }: { status: MixTape['status'] }) {
  const styles: Record<MixTape['status'], string> = {
    pending: 'bg-zinc-700 text-zinc-300',
    rendering: 'bg-blue-700/50 text-blue-200',
    ready: 'bg-green-700/50 text-green-200',
    failed: 'bg-red-700/50 text-red-200',
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${styles[status]}`}>
      {status}
    </span>
  );
}

function formatBytes(n: number | null): string {
  if (!n) return '—';
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds: number | null): string {
  if (!seconds) return '—';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function MixTapesList() {
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.mixtapes.all,
    queryFn: () => mixtapesApi.list(),
    // Re-fetch a touch more often so an in-flight render flips to ready
    // without the user manually refreshing.
    refetchInterval: (query) => {
      const items = query.state.data as MixTape[] | undefined;
      if (!items) return false;
      const hasInflight = items.some(
        (m) => m.status === 'pending' || m.status === 'rendering'
      );
      return hasInflight ? 3000 : false;
    },
  });

  const handleDownload = async (mt: MixTape) => {
    try {
      await mixtapesApi.download(mt.id, mt.name);
    } catch {
      showError('Failed to download mix tape');
    }
  };

  const handleDelete = async (mt: MixTape) => {
    if (!window.confirm(`Delete "${mt.name}"?`)) return;
    try {
      await mixtapesApi.delete(mt.id);
      queryClient.invalidateQueries({ queryKey: queryKeys.mixtapes.all });
      showSuccess('Mix tape deleted');
    } catch {
      showError('Failed to delete mix tape');
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-8 text-zinc-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        Loading mix tapes…
      </div>
    );
  }

  if (error) {
    return <div className="p-8 text-red-400">Failed to load mix tapes.</div>;
  }

  const items = data ?? [];

  if (items.length === 0) {
    return (
      <div className="p-8 text-center text-zinc-400">
        <CassetteTape className="w-10 h-10 mx-auto mb-3 text-zinc-600" />
        <p className="font-medium text-white mb-1">No mix tapes yet</p>
        <p className="text-sm">
          Open a playlist or smart playlist and click "Export Mix Tape" to make one.
        </p>
      </div>
    );
  }

  return (
    <div className="p-4 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold text-white mb-4 flex items-center gap-2">
        <CassetteTape className="w-6 h-6 text-orange-400" />
        Mix Tapes
      </h1>
      <ul className="space-y-2">
        {items.map((mt) => (
          <li
            key={mt.id}
            className="bg-zinc-800 border border-zinc-700 rounded-lg p-3 flex items-center gap-3"
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-white font-medium truncate">{mt.name}</span>
                {mt.byline && (
                  <span className="text-xs text-zinc-400 truncate">· by {mt.byline}</span>
                )}
                <StatusBadge status={mt.status} />
              </div>
              <div className="text-xs text-zinc-400 flex items-center gap-3 flex-wrap">
                <span>{new Date(mt.created_at).toLocaleString()}</span>
                <span>{formatDuration(mt.duration_seconds)}</span>
                <span>{formatBytes(mt.file_size_bytes)}</span>
                <span>{mt.track_ids.length} tracks</span>
                {mt.crossfade_seconds && <span>{mt.crossfade_seconds}s crossfade</span>}
              </div>
              {mt.status === 'failed' && mt.error_message && (
                <p className="text-xs text-red-400 mt-1">{mt.error_message}</p>
              )}
            </div>
            <div className="flex items-center gap-2">
              {mt.status === 'ready' && (
                <button
                  onClick={() => handleDownload(mt)}
                  className="flex items-center gap-1 px-3 py-1.5 text-sm bg-orange-600 hover:bg-orange-500 text-white rounded transition-colors"
                  title="Download bundle"
                >
                  <Download className="w-4 h-4" />
                  Download
                </button>
              )}
              {(mt.status === 'pending' || mt.status === 'rendering') && (
                <Loader2 className="w-5 h-5 text-blue-400 animate-spin" />
              )}
              {mt.status !== 'pending' && mt.status !== 'rendering' && (
                <button
                  onClick={() => handleDelete(mt)}
                  className="p-1.5 text-zinc-400 hover:text-red-400 rounded transition-colors"
                  title="Delete mix tape"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
