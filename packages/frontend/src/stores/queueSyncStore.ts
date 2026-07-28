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
    { name: 'familiar-queue-sync' }
  )
);
