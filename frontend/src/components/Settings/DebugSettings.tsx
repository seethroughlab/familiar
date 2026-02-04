import { useState, useEffect } from 'react';
import { Bug, RefreshCw, Trash2, Download, AlertCircle } from 'lucide-react';
import {
  getAudioContext,
  getAudioAnalyser,
  areAudioEffectsAvailable,
  getCurrentMode,
  isVisualizerAvailable,
} from '../../hooks/useAudioEngine';
import { usePlayerStore } from '../../stores/playerStore';
import { useDownloadStore } from '../../stores/downloadStore';
import * as offlineService from '../../services/offlineService';
import { apiErrorTracker } from '../../utils/apiErrorTracker';
import type { TrackedError } from '../../utils/apiErrorTracker';

// Capture console logs
const logBuffer: { time: string; level: string; message: string }[] = [];
const MAX_LOGS = 50;

// Intercept console methods (only once)
if (typeof window !== 'undefined' && !(window as unknown as { __debugLogsSetup: boolean }).__debugLogsSetup) {
  (window as unknown as { __debugLogsSetup: boolean }).__debugLogsSetup = true;

  const originalConsole = {
    log: console.log,
    warn: console.warn,
    error: console.error,
    debug: console.debug,
  };

  const captureLog = (level: string, ...args: unknown[]) => {
    const time = new Date().toLocaleTimeString();
    const message = args
      .map((arg) =>
        typeof arg === 'object' ? JSON.stringify(arg, null, 2) : String(arg)
      )
      .join(' ');

    logBuffer.unshift({ time, level, message });
    if (logBuffer.length > MAX_LOGS) {
      logBuffer.pop();
    }
  };

  console.log = (...args) => {
    captureLog('log', ...args);
    originalConsole.log(...args);
  };
  console.warn = (...args) => {
    captureLog('warn', ...args);
    originalConsole.warn(...args);
  };
  console.error = (...args) => {
    captureLog('error', ...args);
    originalConsole.error(...args);
  };
  console.debug = (...args) => {
    captureLog('debug', ...args);
    originalConsole.debug(...args);
  };
}

export function DebugSettings() {
  const [expanded, setExpanded] = useState(false);
  const [logs, setLogs] = useState<typeof logBuffer>([]);
  const [offlineCount, setOfflineCount] = useState<number | null>(null);
  const [apiErrors, setApiErrors] = useState<TrackedError[]>([]);
  const { isPlaying, currentTrack } = usePlayerStore();
  const { jobs, activeJobId } = useDownloadStore();

  // Subscribe to API errors
  useEffect(() => {
    const unsubscribe = apiErrorTracker.subscribe((errors) => {
      setApiErrors(errors);
    });
    // Initial load
    setApiErrors(apiErrorTracker.getErrors());
    return unsubscribe;
  }, []);

  // Refresh logs and offline count periodically when expanded
  useEffect(() => {
    if (!expanded) return;

    const refreshData = async () => {
      setLogs([...logBuffer]);
      const ids = await offlineService.getOfflineTrackIds();
      setOfflineCount(ids.length);
    };

    const interval = setInterval(refreshData, 500);

    // Initial load
    refreshData();

    return () => clearInterval(interval);
  }, [expanded]);

  const audioContext = getAudioContext();
  const analyser = getAudioAnalyser();
  const effectsAvailable = areAudioEffectsAvailable();
  const visualizerAvailable = isVisualizerAvailable();
  const currentMode = getCurrentMode();

  // Platform detection
  const isMobilePlatform = /iPad|iPhone|iPod|Android/i.test(navigator.userAgent);
  const isIOS = /iPad|iPhone|iPod/i.test(navigator.userAgent);
  const useHybridMode = isIOS;

  const clearLogs = () => {
    logBuffer.length = 0;
    setLogs([]);
  };

  const refreshLogs = () => {
    setLogs([...logBuffer]);
  };

  const getLevelColor = (level: string) => {
    switch (level) {
      case 'error':
        return 'text-red-400';
      case 'warn':
        return 'text-yellow-400';
      case 'debug':
        return 'text-zinc-500';
      default:
        return 'text-zinc-300';
    }
  };

  return (
    <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-white rounded-lg p-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3"
      >
        <Bug className="w-5 h-5 text-orange-400" />
        <div className="flex-1 text-left">
          <h4 className="font-medium text-white dark:text-white light:text-zinc-900">
            Debug Info
          </h4>
          <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
            Platform detection, audio state, and console logs
          </p>
        </div>
        <span className="text-zinc-400">{expanded ? '▼' : '▶'}</span>
      </button>

      {expanded && (
        <div className="mt-4 space-y-4">
          {/* Platform Detection */}
          <div className="bg-zinc-900/50 rounded-lg p-3">
            <h5 className="text-sm font-medium text-zinc-300 mb-2">Platform Detection</h5>
            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
              <div className="text-zinc-400">User Agent:</div>
              <div className="text-zinc-200 break-all">{navigator.userAgent.slice(0, 50)}...</div>

              <div className="text-zinc-400">isMobilePlatform:</div>
              <div className={isMobilePlatform ? 'text-green-400' : 'text-red-400'}>
                {String(isMobilePlatform)}
              </div>

              <div className="text-zinc-400">isIOS:</div>
              <div className={isIOS ? 'text-green-400' : 'text-red-400'}>
                {String(isIOS)}
              </div>

              <div className="text-zinc-400">useHybridMode:</div>
              <div className={useHybridMode ? 'text-green-400' : 'text-red-400'}>
                {String(useHybridMode)}
              </div>

              <div className="text-zinc-400">currentMode:</div>
              <div className={currentMode === 'webaudio' ? 'text-purple-400' : 'text-blue-400'}>
                {currentMode}
              </div>

              <div className="text-zinc-400">effectsAvailable:</div>
              <div className={effectsAvailable ? 'text-green-400' : 'text-red-400'}>
                {String(effectsAvailable)}
              </div>

              <div className="text-zinc-400">visualizerAvailable:</div>
              <div className={visualizerAvailable ? 'text-green-400' : 'text-red-400'}>
                {String(visualizerAvailable)}
              </div>
            </div>
          </div>

          {/* Audio State */}
          <div className="bg-zinc-900/50 rounded-lg p-3">
            <h5 className="text-sm font-medium text-zinc-300 mb-2">Audio State</h5>
            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
              <div className="text-zinc-400">AudioContext:</div>
              <div className={audioContext ? 'text-green-400' : 'text-yellow-400'}>
                {audioContext ? `exists (${audioContext.state})` : 'null'}
              </div>

              <div className="text-zinc-400">Analyser:</div>
              <div className={analyser ? 'text-green-400' : 'text-yellow-400'}>
                {analyser ? 'exists' : 'null'}
              </div>

              <div className="text-zinc-400">isPlaying:</div>
              <div className={isPlaying ? 'text-green-400' : 'text-zinc-400'}>
                {String(isPlaying)}
              </div>

              <div className="text-zinc-400">currentTrack:</div>
              <div className="text-zinc-200 truncate">
                {currentTrack ? currentTrack.title : 'none'}
              </div>
            </div>
          </div>

          {/* Download State */}
          <div className="bg-zinc-900/50 rounded-lg p-3">
            <h5 className="text-sm font-medium text-zinc-300 mb-2 flex items-center gap-2">
              <Download className="w-4 h-4" />
              Download State
            </h5>
            <div className="grid grid-cols-2 gap-2 text-xs font-mono mb-3">
              <div className="text-zinc-400">Offline tracks in DB:</div>
              <div className="text-zinc-200">{offlineCount ?? 'loading...'}</div>

              <div className="text-zinc-400">Active jobs:</div>
              <div className="text-zinc-200">{jobs.size}</div>

              <div className="text-zinc-400">Active job ID:</div>
              <div className="text-zinc-200">{activeJobId || 'none'}</div>
            </div>

            {jobs.size > 0 && (
              <div className="space-y-2">
                {Array.from(jobs.values()).map((job) => (
                  <div key={job.id} className="bg-zinc-800 rounded p-2 text-xs font-mono">
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-zinc-300 font-medium truncate">{job.name}</span>
                      <span className={`px-1.5 py-0.5 rounded text-xs ${
                        job.status === 'downloading' ? 'bg-blue-500/20 text-blue-400' :
                        job.status === 'queued' ? 'bg-yellow-500/20 text-yellow-400' :
                        job.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                        job.status === 'failed' ? 'bg-red-500/20 text-red-400' :
                        'bg-zinc-500/20 text-zinc-400'
                      }`}>
                        {job.status}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-1 text-zinc-400">
                      <div>trackIds: {job.trackIds.length}</div>
                      <div>completed: {job.completedIds.length}</div>
                      <div>failed: {job.failedIds.length}</div>
                      <div>progress: {job.currentProgress}%</div>
                      <div className="col-span-2">currentTrack: {job.currentTrackId || 'none'}</div>
                    </div>
                    {job.error && (
                      <div className="text-red-400 mt-1">{job.error}</div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {jobs.size === 0 && (
              <div className="text-zinc-500 text-xs italic">No active download jobs</div>
            )}
          </div>

          {/* API Errors */}
          <div className="bg-zinc-900/50 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <h5 className="text-sm font-medium text-zinc-300 flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-red-400" />
                API Errors ({apiErrors.length})
              </h5>
              <button
                onClick={() => apiErrorTracker.clear()}
                className="p-1 text-zinc-400 hover:text-red-400"
                title="Clear errors"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
            <div className="max-h-48 overflow-y-auto space-y-2 text-xs font-mono">
              {apiErrors.length === 0 ? (
                <div className="text-zinc-500 italic">No API errors recorded</div>
              ) : (
                apiErrors.slice(0, 20).map((err) => (
                  <div
                    key={err.id}
                    className={`p-2 rounded ${
                      err.severity === 'error'
                        ? 'bg-red-900/30 border border-red-800/50'
                        : err.severity === 'warning'
                        ? 'bg-yellow-900/30 border border-yellow-800/50'
                        : 'bg-zinc-800/50 border border-zinc-700/50'
                    }`}
                  >
                    <div className="flex justify-between items-start mb-1">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] ${
                          err.category === 'network'
                            ? 'bg-orange-500/20 text-orange-400'
                            : err.category === 'auth'
                            ? 'bg-red-500/20 text-red-400'
                            : err.category === 'server'
                            ? 'bg-red-500/20 text-red-400'
                            : err.category === 'external'
                            ? 'bg-yellow-500/20 text-yellow-400'
                            : 'bg-zinc-500/20 text-zinc-400'
                        }`}
                      >
                        {err.category}
                        {err.statusCode && ` (${err.statusCode})`}
                      </span>
                      <span className="text-zinc-500">
                        {err.timestamp.toLocaleTimeString()}
                      </span>
                    </div>
                    <div className="text-zinc-400 mb-1">
                      <span className="text-zinc-500">{err.method}</span>{' '}
                      <span className="text-zinc-300">{err.endpoint}</span>
                    </div>
                    <div className="text-zinc-200 break-all">{err.message}</div>
                    {err.context && (
                      <div className="text-zinc-500 mt-1">Context: {err.context}</div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Console Logs */}
          <div className="bg-zinc-900/50 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <h5 className="text-sm font-medium text-zinc-300">Console Logs</h5>
              <div className="flex gap-2">
                <button
                  onClick={refreshLogs}
                  className="p-1 text-zinc-400 hover:text-white"
                  title="Refresh"
                >
                  <RefreshCw className="w-4 h-4" />
                </button>
                <button
                  onClick={clearLogs}
                  className="p-1 text-zinc-400 hover:text-red-400"
                  title="Clear"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
            <div className="max-h-64 overflow-y-auto space-y-1 text-xs font-mono">
              {logs.length === 0 ? (
                <div className="text-zinc-500 italic">No logs captured yet</div>
              ) : (
                logs.map((log, i) => (
                  <div key={i} className={`${getLevelColor(log.level)} break-all`}>
                    <span className="text-zinc-500">[{log.time}]</span>{' '}
                    <span className="text-zinc-400">[{log.level}]</span>{' '}
                    {log.message}
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Test Actions */}
          <div className="bg-zinc-900/50 rounded-lg p-3">
            <h5 className="text-sm font-medium text-zinc-300 mb-2">Test Actions</h5>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => console.log('[Test] Manual log test')}
                className="px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-xs rounded"
              >
                Log Test
              </button>
              <button
                onClick={async () => {
                  console.log('[Test] Checking IndexedDB...');
                  try {
                    const ids = await offlineService.getOfflineTrackIds();
                    console.log('[Test] Offline track IDs:', ids.length, ids.slice(0, 5));
                    const usage = await offlineService.getOfflineStorageUsage();
                    console.log('[Test] Storage usage:', usage);
                  } catch (e) {
                    console.error('[Test] IndexedDB error:', e);
                  }
                }}
                className="px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-xs rounded"
              >
                Check IndexedDB
              </button>
              <button
                onClick={async () => {
                  console.log('[Test] Testing track stream API...');
                  try {
                    // Try to fetch headers only for a test track
                    const response = await fetch('/api/v1/tracks/test-id/stream', { method: 'HEAD' });
                    console.log('[Test] Stream API response:', response.status, response.statusText);
                  } catch (e) {
                    console.error('[Test] Stream API error:', e);
                  }
                }}
                className="px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-xs rounded"
              >
                Test Stream API
              </button>
              <button
                onClick={() => {
                  const ctx = getAudioContext();
                  if (ctx) {
                    console.log('[Test] AudioContext state:', ctx.state);
                    if (ctx.state === 'suspended') {
                      ctx.resume().then(() => {
                        console.log('[Test] AudioContext resumed');
                      });
                    }
                  } else {
                    console.log('[Test] No AudioContext');
                  }
                }}
                className="px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-xs rounded"
              >
                Check/Resume Context
              </button>
              <button
                onClick={() => {
                  console.log('[Test] Visibility state:', document.visibilityState);
                  console.log('[Test] Hidden:', document.hidden);
                }}
                className="px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-xs rounded"
              >
                Check Visibility
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
