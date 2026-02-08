import { create } from 'zustand';
import { backgroundApi, type BackgroundJob } from '../api/client';
import { createLogger } from '../utils/logger';

const log = createLogger('BackgroundJobs');

interface BackgroundJobsState {
  jobs: BackgroundJob[];
  activeCount: number;
  isPolling: boolean;
  lastChecked: Date | null;

  // Actions
  checkJobs: () => Promise<void>;
  startPolling: () => void;
  stopPolling: () => void;
}

let pollingInterval: ReturnType<typeof setInterval> | null = null;

// Poll faster when jobs are active, slower when idle
const ACTIVE_POLL_INTERVAL = 2000; // 2 seconds
const IDLE_POLL_INTERVAL = 10000; // 10 seconds

export const useBackgroundJobsStore = create<BackgroundJobsState>((set, get) => ({
  jobs: [],
  activeCount: 0,
  isPolling: false,
  lastChecked: null,

  checkJobs: async () => {
    try {
      const response = await backgroundApi.getJobs();
      const prevActiveCount = get().activeCount;

      set({
        jobs: response.jobs,
        activeCount: response.active_count,
        lastChecked: new Date(),
      });

      // Adjust polling interval based on activity
      if (pollingInterval) {
        const newInterval = response.active_count > 0 ? ACTIVE_POLL_INTERVAL : IDLE_POLL_INTERVAL;
        const wasActive = prevActiveCount > 0;
        const isActive = response.active_count > 0;

        // Only restart interval if activity state changed
        if (wasActive !== isActive) {
          clearInterval(pollingInterval);
          pollingInterval = setInterval(get().checkJobs, newInterval);
        }
      }
    } catch (error) {
      log.error('Failed to check background jobs:', error);
    }
  },

  startPolling: () => {
    const { isPolling, checkJobs, activeCount } = get();
    if (isPolling) return;

    // Initial check
    checkJobs();

    // Start with appropriate interval
    const interval = activeCount > 0 ? ACTIVE_POLL_INTERVAL : IDLE_POLL_INTERVAL;
    pollingInterval = setInterval(checkJobs, interval);
    set({ isPolling: true });
  },

  stopPolling: () => {
    if (pollingInterval) {
      clearInterval(pollingInterval);
      pollingInterval = null;
    }
    set({ isPolling: false });
  },
}));
