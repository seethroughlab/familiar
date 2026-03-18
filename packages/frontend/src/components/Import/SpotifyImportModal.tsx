/**
 * SpotifyImportModal - Shown when a Spotify data export ZIP is dropped.
 *
 * Flow: options -> uploading -> ready (show library button immediately,
 *       background matching spinner until done) -> or error
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Disc3, Loader2, X, CheckCircle, AlertTriangle } from 'lucide-react';
import { queryKeys } from '../../api/queryKeys';
import { spotifyApi } from '../../api/spotify';
import type { SpotifyImportData, UploadOptions } from '../../api/spotify';

interface SpotifyImportModalProps {
  file: File;
  onClose: () => void;
}

type ReadyState = {
  data: SpotifyImportData;
  matchingTaskId: string;
  matchingDone: boolean;
};

type ImportState =
  | { phase: 'options' }
  | { phase: 'uploading' }
  | { phase: 'ready'; ready: ReadyState }
  | { phase: 'error'; error: string };

export function SpotifyImportModal({ file, onClose }: SpotifyImportModalProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [state, setState] = useState<ImportState>({ phase: 'options' });
  const [options, setOptions] = useState<UploadOptions>({
    favorites: true,
    playlists: true,
    streaming: true,
  });
  const pollInterval = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollInterval.current) {
      clearInterval(pollInterval.current);
      pollInterval.current = null;
    }
  };

  const startMatchingPoll = (taskId: string) => {
    const poll = async () => {
      try {
        const status = await spotifyApi.pollStatus(taskId);
        if (status.status === 'completed') {
          stopPolling();
          queryClient.invalidateQueries({ queryKey: queryKeys.spotifyImport.all });
          const updated = await spotifyApi.get();
          setState((prev) => {
            if (prev.phase !== 'ready') return prev;
            return {
              phase: 'ready',
              ready: {
                ...prev.ready,
                data: updated ?? prev.ready.data,
                matchingDone: true,
              },
            };
          });
        } else if (status.status === 'error') {
          stopPolling();
          // Matching failed but import data is still available — just mark done
          setState((prev) => {
            if (prev.phase !== 'ready') return prev;
            return { phase: 'ready', ready: { ...prev.ready, matchingDone: true } };
          });
        }
      } catch {
        // Ignore transient poll errors
      }
    };

    poll();
    pollInterval.current = setInterval(poll, 2000);
  };

  const doUpload = async () => {
    setState({ phase: 'uploading' });
    try {
      const result = await spotifyApi.upload(file, options);
      queryClient.invalidateQueries({ queryKey: queryKeys.spotifyImport.all });
      setState({
        phase: 'ready',
        ready: {
          data: result,
          matchingTaskId: result.matching_task_id,
          matchingDone: result.summary.matching_status !== 'pending',
        },
      });
      if (result.summary.matching_status === 'pending') {
        startMatchingPoll(result.matching_task_id);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Upload failed';
      setState({ phase: 'error', error: message });
    }
  };

  useEffect(() => {
    return () => stopPolling();
  }, []);

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
          {state.phase === 'options' && (
            <div className="space-y-4">
              <p className="text-sm text-zinc-400">
                <span className="text-zinc-200 font-medium">{file.name}</span>
                <br />Select what to import:
              </p>
              <div className="space-y-2">
                <ToggleRow
                  label="Liked Songs"
                  checked={options.favorites}
                  onChange={(v) => setOptions((o) => ({ ...o, favorites: v }))}
                />
                <ToggleRow
                  label="Playlists"
                  checked={options.playlists}
                  onChange={(v) => setOptions((o) => ({ ...o, playlists: v }))}
                />
                <ToggleRow
                  label="Streaming History"
                  checked={options.streaming}
                  onChange={(v) => setOptions((o) => ({ ...o, streaming: v }))}
                />
              </div>
              <button
                onClick={doUpload}
                className="w-full px-4 py-2.5 bg-green-600 hover:bg-green-500 text-white rounded-lg font-medium transition-colors"
              >
                Import
              </button>
            </div>
          )}

          {state.phase === 'uploading' && (
            <div className="flex flex-col items-center gap-4 py-4">
              <Loader2 className="w-10 h-10 animate-spin text-green-400" />
              <p className="text-zinc-200">Uploading and parsing...</p>
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
                  onClick={() => setState({ phase: 'options' })}
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

          {state.phase === 'ready' && (
            <ReadyView
              ready={state.ready}
              onViewLibrary={() => {
                navigate('/library/spotify');
                onClose();
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function ToggleRow({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between cursor-pointer py-1">
      <span className="text-sm text-zinc-300">{label}</span>
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative w-9 h-5 rounded-full transition-colors ${
          checked ? 'bg-green-600' : 'bg-zinc-600'
        }`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
            checked ? 'translate-x-4' : 'translate-x-0'
          }`}
        />
      </button>
    </label>
  );
}

function ReadyView({
  ready,
  onViewLibrary,
}: {
  ready: ReadyState;
  onViewLibrary: () => void;
}) {
  const { data, matchingDone } = ready;
  const s = data.summary;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-green-400">
        <CheckCircle className="w-5 h-5" />
        <span className="font-medium">Import complete</span>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 gap-3">
        {s.total_favorites > 0 && (
          <StatCard
            label="Favorites"
            value={s.total_favorites}
            matched={matchingDone ? s.matched_favorites : undefined}
          />
        )}
        {s.total_playlists > 0 && (
          <StatCard label="Playlists" value={s.total_playlists} />
        )}
        {data.streaming_stats.total_ms > 0 && (
          <StatCard
            label="Hours streamed"
            value={Math.round(data.streaming_stats.total_ms / 3600000)}
          />
        )}
        <StatCard
          label="Matched"
          value={matchingDone ? s.total_matched : 0}
          pending={!matchingDone}
        />
      </div>

      {!matchingDone && (
        <div className="flex items-center gap-2 text-xs text-zinc-400 bg-zinc-800/50 rounded-lg px-3 py-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin flex-shrink-0" />
          Matching tracks in background...
        </div>
      )}

      <button
        onClick={onViewLibrary}
        className="w-full px-4 py-2.5 bg-green-600 hover:bg-green-500 text-white rounded-lg font-medium transition-colors"
      >
        View Spotify Library
      </button>
    </div>
  );
}

function StatCard({
  label,
  value,
  matched,
  pending,
}: {
  label: string;
  value: number;
  matched?: number;
  pending?: boolean;
}) {
  const pct = matched != null && value > 0
    ? Math.round((matched / value) * 100)
    : null;

  return (
    <div className="bg-zinc-800/50 rounded-lg px-3 py-2">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="text-lg font-semibold text-zinc-100">
        {pending ? <span className="text-zinc-500">—</span> : value.toLocaleString()}
      </div>
      {pct != null && (
        <div className={`text-xs ${pct >= 70 ? 'text-green-400' : pct >= 40 ? 'text-yellow-400' : 'text-red-400'}`}>
          {matched!.toLocaleString()} in library ({pct}%)
        </div>
      )}
    </div>
  );
}
