import { useState, useEffect, useCallback } from 'react';
import {
  RefreshCw,
  Disc3,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Sparkles,
} from 'lucide-react';
import { newReleasesApi, type NewRelease, type NewReleasesStatus } from '../../api';
import { NewReleaseCard } from './NewReleaseCard';
import { showError } from '../../stores/toastStore';

import { createLogger } from '../../utils/logger';

const log = createLogger('NewReleases');

interface NewReleasesViewProps {
  defaultExpanded?: boolean;
}

export function NewReleasesView({ defaultExpanded = false }: NewReleasesViewProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [releases, setReleases] = useState<NewRelease[]>([]);
  const [status, setStatus] = useState<NewReleasesStatus | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadReleases = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const [releasesData, statusData] = await Promise.all([
        newReleasesApi.list({ limit: 20 }),
        newReleasesApi.getStatus(),
      ]);
      setReleases(releasesData.releases);
      setStatus(statusData);
    } catch (err) {
      log.error('Failed to load new releases:', err);
      setError('Failed to load new releases');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isExpanded) {
      loadReleases();
    }
  }, [isExpanded, loadReleases]);

  // Poll for status while checking
  useEffect(() => {
    if (!isChecking) return;

    const pollInterval = setInterval(async () => {
      try {
        const statusData = await newReleasesApi.getStatus();
        setStatus(statusData);

        // Check if done
        if (
          statusData.progress?.status === 'completed' ||
          statusData.progress?.status === 'error'
        ) {
          setIsChecking(false);
          // Reload releases after check completes
          const releasesData = await newReleasesApi.list({ limit: 20 });
          setReleases(releasesData.releases);
        }
      } catch (err) {
        log.error('Failed to poll status:', err);
      }
    }, 2000);

    return () => clearInterval(pollInterval);
  }, [isChecking]);

  const handleCheck = async () => {
    try {
      setIsChecking(true);
      setError(null);
      await newReleasesApi.check({ days_back: 90 });
      // Start polling for status
    } catch (err) {
      log.error('Failed to check for new releases:', err);
      setError('Failed to start check');
      setIsChecking(false);
    }
  };

  const handleDismiss = async (releaseId: string) => {
    try {
      await newReleasesApi.dismiss(releaseId);
      setReleases((prev) => prev.filter((r) => r.id !== releaseId));
    } catch (err) {
      log.error('Failed to dismiss release:', err);
      showError('Failed to dismiss release');
    }
  };

  const isCheckRunning = status?.progress?.status === 'running';
  const progressPercent = status?.progress
    ? Math.round(
        (status.progress.artists_checked / Math.max(status.progress.artists_total, 1)) * 100
      )
    : 0;

  return (
    <div className="bg-zinc-900/50 dark:bg-zinc-900/50 light:bg-white rounded-lg border border-zinc-800 dark:border-zinc-800 light:border-zinc-200">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-zinc-800/30 dark:hover:bg-zinc-800/30 light:hover:bg-zinc-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-purple-500/10">
            <Sparkles className="w-5 h-5 text-purple-400" />
          </div>
          <div className="text-left">
            <h3 className="font-medium text-white dark:text-white light:text-zinc-900">
              New Releases
            </h3>
            <p className="text-xs text-zinc-500">
              {status?.new_releases_available
                ? `${status.new_releases_available} new from your artists`
                : 'Discover new music from artists you love'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {status?.new_releases_available ? (
            <span className="px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-400 text-xs font-medium">
              {status.new_releases_available}
            </span>
          ) : null}
          {isExpanded ? (
            <ChevronUp className="w-5 h-5 text-zinc-500" />
          ) : (
            <ChevronDown className="w-5 h-5 text-zinc-500" />
          )}
        </div>
      </button>

      {/* Content */}
      {isExpanded && (
        <div className="border-t border-zinc-800 dark:border-zinc-800 light:border-zinc-200">
          {/* Check button and status */}
          <div className="p-4 border-b border-zinc-800/50 dark:border-zinc-800/50 light:border-zinc-100">
            <div className="flex items-center justify-between gap-4">
              <div className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
                {status?.last_check_at ? (
                  <>
                    Last checked:{' '}
                    {new Date(status.last_check_at).toLocaleDateString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </>
                ) : (
                  'Never checked'
                )}
              </div>
              <button
                onClick={handleCheck}
                disabled={isChecking || isCheckRunning}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 disabled:bg-purple-600/50 text-white text-sm font-medium transition-colors"
              >
                <RefreshCw
                  className={`w-4 h-4 ${isChecking || isCheckRunning ? 'animate-spin' : ''}`}
                />
                {isChecking || isCheckRunning ? 'Checking...' : 'Check Now'}
              </button>
            </div>

            {/* Progress bar */}
            {(isChecking || isCheckRunning) && status?.progress && (
              <div className="mt-3">
                <div className="flex items-center justify-between text-xs text-zinc-500 mb-1">
                  <span>{status.progress.message}</span>
                  <span>{progressPercent}%</span>
                </div>
                <div className="h-1.5 bg-zinc-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-purple-500 transition-all duration-300"
                    style={{ width: `${progressPercent}%` }}
                  />
                </div>
                {status.progress.current_artist && (
                  <p className="text-xs text-zinc-500 mt-1 truncate">
                    Checking: {status.progress.current_artist}
                  </p>
                )}
              </div>
            )}
          </div>

          {/* Error state */}
          {error && (
            <div className="p-4 flex items-center gap-2 text-red-400 text-sm">
              <AlertCircle className="w-4 h-4" />
              {error}
            </div>
          )}

          {/* Loading state */}
          {isLoading && !releases.length && (
            <div className="p-8 flex items-center justify-center">
              <RefreshCw className="w-6 h-6 text-zinc-500 animate-spin" />
            </div>
          )}

          {/* Empty state */}
          {!isLoading && !releases.length && (
            <div className="p-8 text-center">
              <Disc3 className="w-12 h-12 text-zinc-600 mx-auto mb-3" />
              {status && status.total_releases_found > 0 ? (
                <>
                  <p className="text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
                    {status.total_releases_found} release{status.total_releases_found !== 1 ? 's' : ''} found, but all are already in your library
                  </p>
                  <p className="text-xs text-zinc-500 mt-1">
                    View details to see them
                  </p>
                </>
              ) : (
                <>
                  <p className="text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
                    No new releases found
                  </p>
                  <p className="text-xs text-zinc-500 mt-1">
                    Click "Check Now" to search for new music from artists in your library
                  </p>
                </>
              )}
            </div>
          )}

          {/* Releases list */}
          {releases.length > 0 && (
            <div className="p-4 space-y-3 max-h-[400px] overflow-y-auto">
              {releases.map((release) => (
                <NewReleaseCard
                  key={release.id}
                  release={release}
                  onDismiss={handleDismiss}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
