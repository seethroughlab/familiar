import { create } from 'zustand';
import { healthApi, type SystemHealth, type ServiceStatus } from '../api';
import { createLogger } from '../utils/logger';

const log = createLogger('Health');

type HealthStatus = 'healthy' | 'degraded' | 'unhealthy' | 'loading' | 'error';

interface HealthState {
  status: HealthStatus;
  warnings: string[];
  services: ServiceStatus[];
  lastChecked: Date | null;
  isPolling: boolean;

  // Worker-specific tracking for alerts
  workersHealthy: boolean;
  workerAlert: string | null;
  workerAlertDismissed: boolean;

  // Actions
  checkHealth: () => Promise<void>;
  startPolling: () => void;
  stopPolling: () => void;
  dismissWorkerAlert: () => void;
}

let pollingInterval: ReturnType<typeof setInterval> | null = null;

export const useHealthStore = create<HealthState>((set, get) => ({
  status: 'loading',
  warnings: [],
  services: [],
  lastChecked: null,
  isPolling: false,
  workersHealthy: true,
  workerAlert: null,
  workerAlertDismissed: false,

  checkHealth: async () => {
    try {
      const health: SystemHealth = await healthApi.getSystemHealth();
      const prevWorkersHealthy = get().workersHealthy;
      const workerAlertDismissed = get().workerAlertDismissed;

      // Check if background_processing service is healthy
      const bgService = health.services.find(s => s.name === 'background_processing');
      const nowWorkersHealthy = bgService?.status === 'healthy';

      // Detect worker death (was healthy, now not)
      let workerAlert = get().workerAlert;
      if (prevWorkersHealthy && !nowWorkersHealthy && !workerAlertDismissed) {
        workerAlert = bgService?.message || 'Background processing has stopped. Tasks may not complete.';
      } else if (nowWorkersHealthy) {
        // Workers recovered - clear alert
        workerAlert = null;
      }

      set({
        status: health.status as HealthStatus,
        warnings: health.warnings,
        services: health.services,
        lastChecked: new Date(),
        workersHealthy: nowWorkersHealthy,
        workerAlert,
        // Reset dismissed flag when workers recover
        workerAlertDismissed: nowWorkersHealthy ? false : workerAlertDismissed,
      });
    } catch (error) {
      log.error('Failed to check health:', error);
      set({
        status: 'error',
        warnings: ['Unable to check system status'],
        lastChecked: new Date(),
      });
    }
  },

  startPolling: () => {
    const { isPolling, checkHealth } = get();
    if (isPolling) return;

    // Initial check
    checkHealth();

    // Poll every 15 seconds for faster worker death detection
    pollingInterval = setInterval(checkHealth, 15000);
    set({ isPolling: true });
  },

  stopPolling: () => {
    if (pollingInterval) {
      clearInterval(pollingInterval);
      pollingInterval = null;
    }
    set({ isPolling: false });
  },

  dismissWorkerAlert: () => {
    set({ workerAlert: null, workerAlertDismissed: true });
  },
}));
