import { useState, useEffect } from 'react';
import { HardDrive, AlertTriangle } from 'lucide-react';
import * as offlineService from '../../services/offlineService';

interface Props {
  refreshTrigger?: number;
}

export function StorageQuotaDisplay({ refreshTrigger }: Props) {
  const [quota, setQuota] = useState<{
    used: number;
    quota: number;
    usedFormatted: string;
    quotaFormatted: string;
    percentUsed: number;
  } | null>(null);
  const [isSupported, setIsSupported] = useState(true);

  useEffect(() => {
    const loadQuota = async () => {
      const info = await offlineService.getStorageQuota();
      if (info === null) {
        setIsSupported(false);
      } else {
        setQuota(info);
      }
    };
    loadQuota();
  }, [refreshTrigger]);

  if (!isSupported) {
    return null; // Don't show anything if storage API not available
  }

  if (!quota) {
    return null;
  }

  const isWarning = quota.percentUsed >= 80;
  const isCritical = quota.percentUsed >= 95;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center gap-2 text-zinc-400">
          <HardDrive className="w-4 h-4" />
          <span>Storage</span>
        </div>
        <div className="flex items-center gap-2">
          {(isWarning || isCritical) && (
            <AlertTriangle
              className={`w-4 h-4 ${isCritical ? 'text-red-400' : 'text-amber-400'}`}
            />
          )}
          <span
            className={
              isCritical
                ? 'text-red-400'
                : isWarning
                  ? 'text-amber-400'
                  : 'text-zinc-300'
            }
          >
            {quota.usedFormatted} / {quota.quotaFormatted}
          </span>
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-2 bg-zinc-700 rounded-full overflow-hidden">
        <div
          className={`h-full transition-all duration-300 ${
            isCritical
              ? 'bg-red-500'
              : isWarning
                ? 'bg-amber-500'
                : 'bg-purple-500'
          }`}
          style={{ width: `${Math.min(100, quota.percentUsed)}%` }}
        />
      </div>

      {isCritical && (
        <p className="text-xs text-red-400">
          Storage is almost full. Remove some downloaded tracks to free up
          space.
        </p>
      )}
      {isWarning && !isCritical && (
        <p className="text-xs text-amber-400">
          Storage is getting low. Consider removing unused tracks.
        </p>
      )}
    </div>
  );
}
