/**
 * SpotifyImportModal - Shown when a Spotify data export ZIP is dropped.
 *
 * Flow: uploading -> polling -> done (summary + navigate to Spotify Library)
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Disc3, Loader2, X, CheckCircle, AlertTriangle } from 'lucide-react';
import { spotifyApi } from '../../api/spotify';
import type { SpotifyImportData } from '../../api/spotify';

interface SpotifyImportModalProps {
  file: File;
  onClose: () => void;
}

type ImportState =
  | { phase: 'uploading' }
  | { phase: 'polling'; taskId: string; message: string }
  | { phase: 'done'; data: SpotifyImportData }
  | { phase: 'error'; error: string };

export function SpotifyImportModal({ file, onClose }: SpotifyImportModalProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [state, setState] = useState<ImportState>({ phase: 'uploading' });
  const pollInterval = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollInterval.current) {
      clearInterval(pollInterval.current);
      pollInterval.current = null;
    }
  };

  const startPolling = (taskId: string) => {
    const poll = async () => {
      try {
        const status = await spotifyApi.pollStatus(taskId);
        if (status.status === 'completed') {
          stopPolling();
          queryClient.invalidateQueries({ queryKey: ['spotify-import'] });
          const importData = await spotifyApi.get();
          if (importData) {
            setState({ phase: 'done', data: importData });
          } else {
            setState({ phase: 'error', error: 'Import completed but data not found' });
          }
        } else if (status.status === 'error') {
          stopPolling();
          setState({ phase: 'error', error: status.error || 'Import failed' });
        } else {
          setState({ phase: 'polling', taskId, message: status.message || 'Processing...' });
        }
      } catch (err: unknown) {
        stopPolling();
        const message = err instanceof Error ? err.message : 'Polling failed';
        setState({ phase: 'error', error: message });
      }
    };

    poll();
    pollInterval.current = setInterval(poll, 2000);
  };

  // Auto-upload on mount
  useEffect(() => {
    let cancelled = false;

    const doUpload = async () => {
      try {
        const { task_id } = await spotifyApi.upload(file);
        if (!cancelled) {
          setState({ phase: 'polling', taskId: task_id, message: 'Parsing export...' });
          startPolling(task_id);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : 'Upload failed';
          setState({ phase: 'error', error: message });
        }
      }
    };

    doUpload();

    return () => {
      cancelled = true;
      stopPolling();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const retry = () => {
    setState({ phase: 'uploading' });
    stopPolling();

    const doUpload = async () => {
      try {
        const { task_id } = await spotifyApi.upload(file);
        setState({ phase: 'polling', taskId: task_id, message: 'Parsing export...' });
        startPolling(task_id);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : 'Upload failed';
        setState({ phase: 'error', error: message });
      }
    };

    doUpload();
  };

  const isLoading = state.phase === 'uploading' || state.phase === 'polling';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md mx-4 bg-zinc-900 rounded-xl shadow-2xl border border-zinc-800 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-zinc-800">
          <div className="flex items-center gap-2">
            <Disc3 className="w-5 h-5 text-green-400" />
            <h2 className="font-semibold text-white">Spotify Import</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-zinc-800 transition-colors text-zinc-400 hover:text-white"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6">
          {isLoading && (
            <div className="flex flex-col items-center gap-4 py-4">
              <Loader2 className="w-10 h-10 animate-spin text-green-400" />
              <div className="text-center">
                <p className="text-zinc-200">Processing Spotify export...</p>
                <p className="text-xs text-zinc-500 mt-1">
                  {state.phase === 'polling' ? state.message : 'Uploading...'}
                </p>
              </div>
            </div>
          )}

          {state.phase === 'error' && (
            <div className="flex flex-col items-center gap-4 py-4">
              <AlertTriangle className="w-10 h-10 text-red-400" />
              <div className="text-center">
                <p className="text-zinc-200">Import failed</p>
                <p className="text-sm text-red-400 mt-1">{state.error}</p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={retry}
                  className="px-4 py-2 bg-zinc-700 hover:bg-zinc-600 text-white rounded-lg text-sm transition-colors"
                >
                  Retry
                </button>
                <button
                  onClick={onClose}
                  className="px-4 py-2 text-zinc-400 hover:text-white text-sm transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {state.phase === 'done' && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-green-400">
                <CheckCircle className="w-5 h-5" />
                <span className="font-medium">Import complete</span>
              </div>

              {/* Summary stats */}
              <div className="grid grid-cols-2 gap-3">
                <StatCard
                  label="Favorites"
                  value={state.data.summary.total_favorites}
                  matched={state.data.summary.matched_favorites}
                />
                <StatCard
                  label="Playlists"
                  value={state.data.summary.total_playlists}
                />
                {state.data.streaming_stats.total_ms > 0 && (
                  <StatCard
                    label="Hours streamed"
                    value={Math.round(state.data.streaming_stats.total_ms / 3600000)}
                  />
                )}
                <StatCard
                  label="Total matched"
                  value={state.data.summary.total_matched}
                />
              </div>

              <button
                onClick={() => {
                  navigate('/library/spotify');
                  onClose();
                }}
                className="w-full px-4 py-2.5 bg-green-600 hover:bg-green-500 text-white rounded-lg font-medium transition-colors"
              >
                View Spotify Library
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  matched,
}: {
  label: string;
  value: number;
  matched?: number;
}) {
  const pct = matched != null && value > 0
    ? Math.round((matched / value) * 100)
    : null;

  return (
    <div className="bg-zinc-800/50 rounded-lg px-3 py-2">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="text-lg font-semibold text-zinc-100">
        {value.toLocaleString()}
      </div>
      {pct != null && (
        <div className={`text-xs ${pct >= 70 ? 'text-green-400' : pct >= 40 ? 'text-yellow-400' : 'text-red-400'}`}>
          {matched!.toLocaleString()} in library ({pct}%)
        </div>
      )}
    </div>
  );
}
