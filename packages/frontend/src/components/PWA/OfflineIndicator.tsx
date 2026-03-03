/**
 * Offline indicator component.
 * Shows a banner when the user is offline.
 */
import { useState, useEffect } from 'react';
import { WifiOff, X, RefreshCw, Loader2 } from 'lucide-react';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import * as syncService from '../../services/syncService';

export function OfflineIndicator() {
  const { isOffline, isOnline } = useOfflineStatus();
  const [pendingCount, setPendingCount] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [showReconnected, setShowReconnected] = useState(false);

  useEffect(() => {
    // Check pending count
    syncService.getPendingCount().then(setPendingCount);
  }, [isOnline]);

  useEffect(() => {
    // Show "back online" message briefly when reconnecting
    if (isOnline && pendingCount > 0) {
      setShowReconnected(true);
      setIsSyncing(true);

      syncService.processPendingActions().then(() => {
        setIsSyncing(false);
        syncService.getPendingCount().then(setPendingCount);

        // Hide after a delay
        setTimeout(() => {
          setShowReconnected(false);
        }, 3000);
      });
    }
  }, [isOnline, pendingCount]);

  // Reset dismissed state when going offline again
  useEffect(() => {
    if (isOffline) {
      setDismissed(false);
    }
  }, [isOffline]);

  // Don't show if online and not showing reconnected message
  if (isOnline && !showReconnected) {
    return null;
  }

  // Don't show if dismissed while offline
  if (isOffline && dismissed) {
    return null;
  }

  return (
    <div
      className={`fixed top-0 left-0 right-0 z-50 px-4 py-2 pt-safe flex items-center justify-between text-sm ${
        isOffline
          ? 'bg-amber-600 text-white'
          : 'bg-green-600 text-white'
      }`}
    >
      <div className="flex items-center gap-2">
        {isOffline ? (
          <>
            <WifiOff className="w-4 h-4" />
            <span>
              You're offline.
              {pendingCount > 0 && ` ${pendingCount} actions will sync when you're back online.`}
            </span>
          </>
        ) : (
          <>
            {isSyncing ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Syncing {pendingCount} pending actions...</span>
              </>
            ) : (
              <>
                <RefreshCw className="w-4 h-4" />
                <span>Back online! All synced.</span>
              </>
            )}
          </>
        )}
      </div>

      {isOffline && (
        <button
          onClick={() => setDismissed(true)}
          className="p-1 hover:bg-white/20 rounded transition-colors"
          title="Dismiss"
        >
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  );
}
