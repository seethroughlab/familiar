import { MonitorSmartphone } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { appSettingsApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { useQueueSyncStore } from '../../stores/queueSyncStore';

/**
 * Opt-in for the server-owned playback queue (ADR-0003 point 7).
 *
 * Off by default. This is a rollout gate, not a preference — the queue is the most heavily
 * tested code in the app, and this is the highest-risk change in the programme, so it is
 * proven in the web app before the native client depends on it.
 *
 * Two switches, deliberately. The server one decides whether sessions are stored at all;
 * the device one decides whether *this* device takes part, so sync can be tried on one
 * machine without dragging the others in. Both are shown together because either alone
 * does nothing, and a half-enabled feature that silently no-ops is the worst outcome here.
 *
 * The device toggle takes effect immediately: `useAppBootstrap` keys the sync effect on it.
 */
export function QueueSyncSettings() {
  const queryClient = useQueryClient();
  const deviceEnabled = useQueueSyncStore((s) => s.enabled);
  const setDeviceEnabled = useQueueSyncStore((s) => s.setEnabled);

  const { data: settings, isLoading } = useQuery({
    queryKey: queryKeys.appSettings.all,
    queryFn: appSettingsApi.get,
  });

  const updateMutation = useMutation({
    mutationFn: appSettingsApi.update,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.appSettings.all });
    },
  });

  const serverEnabled = settings?.queue_sync_enabled ?? false;
  const active = serverEnabled && deviceEnabled;

  return (
    <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4">
      <div className="flex items-center gap-3 mb-4">
        <MonitorSmartphone className="w-5 h-5 text-sky-400" />
        <div>
          <h4 className="text-sm font-medium text-white dark:text-white light:text-zinc-900">
            Sync Queue Across Devices
          </h4>
          <p className="text-xs text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
            Pick up on another device where you left off, down to the position in the track
          </p>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between py-2 border-t border-zinc-700">
          <div>
            <p className="text-sm text-white dark:text-white light:text-zinc-900">On this server</p>
            <p className="text-xs text-zinc-500">Stores the queue so other devices can read it</p>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={serverEnabled}
              disabled={isLoading || updateMutation.isPending}
              onChange={(e) => updateMutation.mutate({ queue_sync_enabled: e.target.checked })}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-sky-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-sky-500 peer-disabled:opacity-50"></div>
          </label>
        </div>

        <div className="flex items-center justify-between py-2 border-t border-zinc-700">
          <div>
            <p className="text-sm text-white dark:text-white light:text-zinc-900">On this device</p>
            <p className="text-xs text-zinc-500">Whether this device joins in</p>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={deviceEnabled}
              onChange={(e) => setDeviceEnabled(e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-sky-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-sky-500"></div>
          </label>
        </div>
      </div>

      {/* Say so explicitly: one switch on and the other off looks identical to a bug. */}
      {deviceEnabled && !serverEnabled && (
        <p className="mt-3 text-xs text-amber-400">
          This device is ready, but the server is not storing queues yet — turn on the server
          switch above.
        </p>
      )}
      {serverEnabled && !deviceEnabled && (
        <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-500 light:text-zinc-600">
          The server is storing queues, but this device is not taking part.
        </p>
      )}
      {active && (
        <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-500 light:text-zinc-600">
          Your queue is kept locally and mirrored when connected, so playback never waits on the
          network. If two devices change the queue while apart, the most recent one wins and the
          other is kept so nothing you built is lost.
        </p>
      )}
    </div>
  );
}
