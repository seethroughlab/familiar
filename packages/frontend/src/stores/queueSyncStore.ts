/**
 * Per-device opt-in for mirroring the playback queue to the server (ADR-0003 point 7).
 *
 * Persisted and off by default. This is a rollout gate rather than a preference: the queue
 * is the most heavily tested code in the app and syncing it across devices is the highest-risk
 * change in the programme, so it is proven in the web app before the native client depends
 * on it. Per device rather than per profile, so one machine can run it while others do not.
 *
 * The server has its own `queue_sync_enabled` setting and rejects session traffic when that
 * is off — turning this on alone is not enough, by design.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface QueueSyncState {
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
}

export const useQueueSyncStore = create<QueueSyncState>()(
  persist(
    (set) => ({
      enabled: false,
      setEnabled: (enabled) => set({ enabled }),
    }),
    {
      name: 'familiar-queue-sync',
      /**
       * Version 1 forces the gate back off, because ADR-0058 point 5 removed the only control.
       *
       * The flag is persisted, so a device where it had been switched on would otherwise keep
       * mirroring its queue forever with nothing left to turn it off — an invisible behaviour with
       * no affordance, which is the same defect as an affordance with no behaviour. Off is also
       * where it started: the docstring above calls it a rollout gate, not a preference.
       *
       * `setEnabled` stays on the store: `queueSyncService` and its tests drive it directly, and
       * the gate itself is not being removed — only its settings-page switch.
       */
      version: 1,
      migrate: (persisted) => ({ ...(persisted as QueueSyncState), enabled: false }),
    }
  )
);
