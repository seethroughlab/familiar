import { MonitorSmartphone } from 'lucide-react';
import { useQueueSyncStore } from '../../stores/queueSyncStore';

/**
 * Per-device opt-in for the server-owned playback queue (ADR-0003 point 7).
 *
 * Off by default. This is a rollout gate, not a preference — the queue is the most heavily
 * tested code in the app, and this is the highest-risk change in the programme, so it is
 * proven in the web app before the native client depends on it.
 *
 * Takes effect immediately: `useAppBootstrap` keys the sync effect on this flag, so there
 * is no reload step to explain.
 */
export function QueueSyncSettings() {
  const enabled = useQueueSyncStore((s) => s.enabled);
  const setEnabled = useQueueSyncStore((s) => s.setEnabled);

  return (
    <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
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
        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="sr-only peer"
          />
          <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-sky-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-sky-500"></div>
        </label>
      </div>

      {enabled && (
        <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-500 light:text-zinc-600">
          Your queue is kept locally and mirrored when connected, so playback never waits on the
          network. If two devices change the queue while apart, the most recent one wins and the
          other is kept so nothing you built is lost. Needs to be enabled on the server too.
        </p>
      )}
    </div>
  );
}
