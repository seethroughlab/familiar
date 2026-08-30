/**
 * Server-reachability banner.
 *
 * Shows when the server cannot be reached, which an administration tool needs to say — a scan
 * that appears to do nothing and a server that is simply unreachable look identical otherwise.
 *
 * **It no longer reports queued actions.** ADR-0071 deleted the offline action queue along with
 * the rest of the Dexie stack, so there is nothing pending to sync and nothing to count. What is
 * left is the one fact the banner was always most useful for.
 */
import { useState, useEffect } from 'react';
import { WifiOff, X } from 'lucide-react';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';

export function OfflineIndicator() {
  const { isOffline } = useOfflineStatus();
  const [dismissed, setDismissed] = useState(false);

  // Reset dismissed state when the server goes unreachable again
  useEffect(() => {
    if (isOffline) {
      setDismissed(false);
    }
  }, [isOffline]);

  if (!isOffline || dismissed) {
    return null;
  }

  return (
    <div className="fixed top-0 left-0 right-0 z-50 px-4 py-2 pt-safe flex items-center justify-between text-sm bg-warning-strong text-white">
      <div className="flex items-center gap-2">
        <WifiOff className="w-4 h-4" />
        <span>Can't reach the server.</span>
      </div>

      <button
        onClick={() => setDismissed(true)}
        className="p-1 hover:bg-white/20 rounded transition-colors"
        title="Dismiss"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
