import { useEffect } from 'react';
import { toast } from 'sonner';
import { updatesApi } from '../api';

const SESSION_KEY = 'familiar-update-dismissed';

/**
 * One-time toast notification when a new version is available.
 * Shows once per session (dismissed via sessionStorage).
 */
export function useUpdateNotification() {
  useEffect(() => {
    if (sessionStorage.getItem(SESSION_KEY)) return;

    updatesApi.getStatus().then((status) => {
      if (!status.update_available || !status.latest_version) return;

      sessionStorage.setItem(SESSION_KEY, '1');
      toast.info(`Familiar ${status.latest_version} is available`, {
        description: 'A new version is ready. Check Settings for details.',
        duration: 8000,
        action: status.release_url
          ? {
              label: 'View',
              onClick: () => window.open(status.release_url!, '_blank'),
            }
          : undefined,
      });
    }).catch(() => {
      // Silently ignore — update check is non-critical
    });
  }, []);
}
