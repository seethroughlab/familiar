import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, CheckCircle, AlertCircle, Loader2, Music, FolderSearch, FileText, Cpu, Sparkles } from 'lucide-react';
import { libraryApi, type SyncStatus, type SyncPhase } from '../../api/client';

import { showError } from '../../stores/toastStore';
import { createLogger } from '../../utils/logger';

const log = createLogger('LibrarySync');

export function LibrarySync() {
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [isStarting, setIsStarting] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await libraryApi.getSyncStatus();
      setSyncStatus(data);
      return data.status === 'running';
    } catch (error) {
      log.error('Failed to fetch sync status:', error);
      return false;
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Poll while running
  useEffect(() => {
    if (syncStatus?.status !== 'running') return;

    const interval = setInterval(fetchStatus, 1000);
    return () => clearInterval(interval);
  }, [syncStatus?.status, fetchStatus]);

  const startSync = async (rereadUnchanged = false) => {
    setIsStarting(true);
    try {
      await libraryApi.sync({ rereadUnchanged });
      await fetchStatus();
    } catch (error) {
      log.error('Failed to start sync:', error);
      showError('Failed to start library sync');
    } finally {
      setIsStarting(false);
    }
  };

  const cancelSync = async () => {
    try {
      await libraryApi.cancelSync();
      await fetchStatus();
    } catch (error) {
      log.error('Failed to cancel sync:', error);
      showError('Failed to cancel sync');
    }
  };

  const getPhaseIcon = (phase: SyncPhase, currentPhase: SyncPhase) => {
    const isActive = phase === currentPhase;
    const phases: SyncPhase[] = ['discovering', 'reading', 'features', 'embeddings'];
    const currentIndex = phases.indexOf(currentPhase);
    const phaseIndex = phases.indexOf(phase);
    const isPast = phaseIndex < currentIndex || currentPhase === 'complete';

    const iconClass = `w-4 h-4 ${
      isActive ? 'text-blue-400' : isPast ? 'text-green-400' : 'text-zinc-600'
    }`;

    if (isPast) {
      return <CheckCircle className={iconClass} />;
    }
    if (isActive) {
      return <Loader2 className={`${iconClass} animate-spin`} />;
    }

    switch (phase) {
      case 'discovering':
        return <FolderSearch className={iconClass} />;
      case 'reading':
        return <FileText className={iconClass} />;
      case 'features':
        return <Cpu className={iconClass} />;
      case 'embeddings':
        return <Sparkles className={iconClass} />;
      default:
        return null;
    }
  };

  const getStatusIcon = () => {
    if (isStarting) {
      return <Loader2 className="w-5 h-5 text-blue-400 animate-spin" />;
    }

    const status = syncStatus?.status;
    const phase = syncStatus?.progress?.phase;

    if (status === 'running') {
      return <Loader2 className="w-5 h-5 text-blue-400 animate-spin" />;
    }
    if (status === 'error') {
      return <AlertCircle className="w-5 h-5 text-red-400" />;
    }
    if (status === 'completed' || phase === 'complete') {
      return <CheckCircle className="w-5 h-5 text-green-400" />;
    }

    return <Music className="w-5 h-5 text-zinc-400" />;
  };

  const getStatusMessage = () => {
    if (isStarting) return 'Starting sync...';

    const status = syncStatus?.status;
    const progress = syncStatus?.progress;

    if (status === 'running' && progress) {
      return progress.phase_message || 'Syncing...';
    }
    if (status === 'error') {
      return syncStatus?.message || 'An error occurred';
    }
    if (status === 'completed') {
      const p = progress;
      if (p) {
        return `Synced: ${p.new_tracks} new, ${p.updated_tracks} updated, ${p.tracks_analyzed} analyzed`;
      }
      return 'Sync complete';
    }

    return 'Keep your library up to date';
  };

  const isRunning = syncStatus?.status === 'running';
  const progress = syncStatus?.progress;

  // Calculate overall progress percentage (4 phases)
  const getOverallProgress = () => {
    if (!progress) return 0;
    const phase = progress.phase;

    if (phase === 'discovering') {
      return 5; // Discovery is quick (0-5%)
    }
    if (phase === 'reading') {
      const readProgress = progress.files_total > 0
        ? (progress.files_processed / progress.files_total) * 100
        : 0;
      // Reading is 5-30% of overall
      return 5 + (readProgress * 0.25);
    }
    if (phase === 'features') {
      // Features phase is 30-65%
      return 30 + (progress.analysis_percent * 0.35);
    }
    if (phase === 'embeddings') {
      // Embeddings phase is 65-100%
      return 65 + (progress.analysis_percent * 0.35);
    }
    if (phase === 'complete') {
      return 100;
    }
    return 0;
  };

  return (
    <div className="bg-zinc-800/50 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          {getStatusIcon()}
          <div>
            <h4 className="font-medium text-white">Library Sync</h4>
            <p className="text-sm text-zinc-400">
              {getStatusMessage()}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {isRunning && (
            <button
              onClick={cancelSync}
              className="px-3 py-1.5 text-sm text-zinc-400 hover:text-white"
            >
              Cancel
            </button>
          )}
          <button
            onClick={() => startSync(false)}
            disabled={isRunning || isStarting}
            aria-label="Sync library"
            className="px-3 py-1.5 text-sm bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 disabled:cursor-not-allowed rounded-md flex items-center gap-2"
          >
            {isStarting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
            Sync Now
          </button>
        </div>
      </div>

      {/* Phase indicators when running */}
      {isRunning && progress && (
        <div className="mt-4 space-y-3">
          {/* Phase steps - 4 phases: Discover → Read → Features → Embeddings */}
          <div className="flex items-center justify-between">
            {/* Discover */}
            <div className="flex items-center">
              <div className="flex items-center gap-1.5">
                {getPhaseIcon('discovering', progress.phase)}
                <span className={`text-xs ${
                  progress.phase === 'discovering' ? 'text-blue-400' :
                  ['reading', 'features', 'embeddings', 'complete'].includes(progress.phase) ? 'text-green-400' : 'text-zinc-600'
                }`}>
                  Discover
                </span>
              </div>
              <div className="w-4 sm:w-8 h-px bg-zinc-700 mx-1 sm:mx-2" />
            </div>

            {/* Read */}
            <div className="flex items-center">
              <div className="flex items-center gap-1.5">
                {getPhaseIcon('reading', progress.phase)}
                <span className={`text-xs ${
                  progress.phase === 'reading' ? 'text-blue-400' :
                  ['features', 'embeddings', 'complete'].includes(progress.phase) ? 'text-green-400' : 'text-zinc-600'
                }`}>
                  Read
                </span>
              </div>
              <div className="w-4 sm:w-8 h-px bg-zinc-700 mx-1 sm:mx-2" />
            </div>

            {/* Features */}
            <div className="flex items-center">
              <div className="flex items-center gap-1.5">
                {progress.phase === 'features' ? (
                  <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
                ) : ['embeddings', 'complete'].includes(progress.phase) ? (
                  <CheckCircle className="w-4 h-4 text-green-400" />
                ) : (
                  <Cpu className="w-4 h-4 text-zinc-600" />
                )}
                <span className={`text-xs ${
                  progress.phase === 'features' ? 'text-blue-400' :
                  ['embeddings', 'complete'].includes(progress.phase) ? 'text-green-400' : 'text-zinc-600'
                }`}>
                  Features
                </span>
              </div>
              <div className="w-4 sm:w-8 h-px bg-zinc-700 mx-1 sm:mx-2" />
            </div>

            {/* Embeddings */}
            <div className="flex items-center">
              <div className="flex items-center gap-1.5">
                {progress.phase === 'embeddings' ? (
                  <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
                ) : progress.phase === 'complete' ? (
                  <CheckCircle className="w-4 h-4 text-green-400" />
                ) : (
                  <Sparkles className="w-4 h-4 text-zinc-600" />
                )}
                <span className={`text-xs ${
                  progress.phase === 'embeddings' ? 'text-blue-400' :
                  progress.phase === 'complete' ? 'text-green-400' : 'text-zinc-600'
                }`}>
                  Embeddings
                </span>
              </div>
            </div>
          </div>

          {/* Progress bar */}
          <div className="w-full bg-zinc-700 rounded-full h-2">
            <div
              className="bg-blue-500 h-2 rounded-full transition-all duration-300"
              style={{ width: `${getOverallProgress()}%` }}
            />
          </div>

          {/* Current item */}
          {progress.current_item && (
            <p className="text-xs text-zinc-500 truncate">
              {progress.current_item}
            </p>
          )}

          {/* Stats grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-xs">
            <div className="bg-zinc-700/50 rounded p-2">
              <div className="text-green-400 font-medium">{progress.new_tracks}</div>
              <div className="text-zinc-500">New</div>
            </div>
            <div className="bg-zinc-700/50 rounded p-2">
              <div className="text-blue-400 font-medium">{progress.updated_tracks}</div>
              <div className="text-zinc-500">Updated</div>
            </div>
            <div className="bg-zinc-700/50 rounded p-2">
              <div className="text-zinc-400 font-medium">{progress.unchanged_tracks}</div>
              <div className="text-zinc-500">Unchanged</div>
            </div>
            <div className="bg-zinc-700/50 rounded p-2">
              <div className="text-purple-400 font-medium">{progress.tracks_analyzed}</div>
              <div className="text-zinc-500">Analyzed</div>
            </div>
          </div>

          {/* Errors */}
          {Array.isArray(progress.errors) && progress.errors.length > 0 && (
            <div className="mt-2 p-2 bg-red-900/20 border border-red-800 rounded text-xs text-red-300">
              <p className="font-medium mb-1">Errors ({progress.errors.length}):</p>
              <ul className="list-disc list-inside">
                {progress.errors.slice(0, 3).map((err, i) => (
                  <li key={i} className="truncate">{err}</li>
                ))}
                {progress.errors.length > 3 && (
                  <li>...and {progress.errors.length - 3} more</li>
                )}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Completed summary */}
      {syncStatus?.status === 'completed' && progress && (
        <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-xs">
          <div className="bg-zinc-700/50 rounded p-2">
            <div className="text-green-400 font-medium">{progress.new_tracks}</div>
            <div className="text-zinc-500">New</div>
          </div>
          <div className="bg-zinc-700/50 rounded p-2">
            <div className="text-blue-400 font-medium">{progress.updated_tracks}</div>
            <div className="text-zinc-500">Updated</div>
          </div>
          <div className="bg-zinc-700/50 rounded p-2">
            <div className="text-zinc-400 font-medium">{progress.unchanged_tracks}</div>
            <div className="text-zinc-500">Unchanged</div>
          </div>
          <div className="bg-zinc-700/50 rounded p-2">
            <div className="text-purple-400 font-medium">{progress.tracks_analyzed}</div>
            <div className="text-zinc-500">Analyzed</div>
          </div>
        </div>
      )}

      {/* Error state */}
      {syncStatus?.status === 'error' && (
        <div className="mt-4 p-4 bg-red-900/20 border border-red-800 rounded-lg">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-400 mt-0.5 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="font-medium text-red-400">Sync failed</p>
              <p className="text-sm text-zinc-400 mt-1">
                {syncStatus.message || 'An unknown error occurred'}
              </p>
              <button
                onClick={() => startSync(false)}
                className="mt-3 px-3 py-1.5 bg-red-600 hover:bg-red-500 rounded text-sm"
              >
                Retry
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
