import { create } from 'zustand';
import { getApiUrl } from '../api/base';
import { getOfflineTrackIds } from '../services/offlineService';
import { createLogger } from '../utils/logger';

const log = createLogger('Connectivity');

export type ReachabilityState = 'unknown' | 'checking' | 'reachable' | 'unreachable';

interface ConnectivityCounters {
  network_unreachable_load_failures: number;
  offline_mode_forced: number;
  offline_queue_rebuild_count: number;
  skip_storm_circuit_breaker_triggered: number;
  recovery_to_online_success: number;
  remote_command_enablement_mismatch: number;
  pending_sync_local_url_local: number;
  pending_sync_local_url_total: number;
}

interface ConnectivityState {
  browserOnline: boolean;
  reachabilityState: ReachabilityState;
  forcedOffline: boolean;
  offlineModeActive: boolean;
  lastRecoveryAt: number | null;
  lastReachableAt: number | null;
  consecutiveNetworkFailures: number;
  offlineTrackIds: Set<string>;
  counters: ConnectivityCounters;

  startMonitoring: () => void;
  stopMonitoring: () => void;
  refreshOfflineTrackIds: () => Promise<void>;
  noteStreamLoadFailure: (category: 'network-unreachable' | 'offline-unavailable' | 'other') => void;
  noteStreamLoadSuccess: () => void;
  incrementCounter: (name: keyof ConnectivityCounters) => void;
  incrementCounterBy: (name: keyof ConnectivityCounters, amount: number) => void;
}

const PROBE_TIMEOUT_MS = 3500;
const PROBE_ONLINE_INTERVAL_MS = 20000;
const PROBE_OFFLINE_INTERVAL_MS = 8000;

let started = false;
let probeTimer: ReturnType<typeof setTimeout> | null = null;
let browserOnlineListener: (() => void) | null = null;
let browserOfflineListener: (() => void) | null = null;
let networkListenerRemove: (() => void) | null = null;

async function probeBackendReachability(): Promise<boolean> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    const response = await fetch(getApiUrl('/health'), {
      method: 'GET',
      cache: 'no-store',
      signal: controller.signal,
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

function setOfflineDerivedState(browserOnline: boolean, forcedOffline: boolean): Pick<ConnectivityState, 'browserOnline' | 'forcedOffline' | 'offlineModeActive'> {
  const offlineModeActive = !browserOnline || forcedOffline;
  return {
    browserOnline,
    forcedOffline,
    offlineModeActive,
  };
}

function scheduleProbe(delayMs: number): void {
  if (probeTimer) clearTimeout(probeTimer);
  probeTimer = setTimeout(runProbe, delayMs);
}

async function runProbe(): Promise<void> {
  const state = useConnectivityStore.getState();
  if (!started) return;

  if (!state.browserOnline) {
    useConnectivityStore.setState({
      reachabilityState: 'unreachable',
      ...setOfflineDerivedState(false, state.forcedOffline),
    });
    scheduleProbe(PROBE_OFFLINE_INTERVAL_MS);
    return;
  }

  useConnectivityStore.setState({ reachabilityState: 'checking' });
  const reachable = await probeBackendReachability();
  const now = Date.now();
  const current = useConnectivityStore.getState();

  if (reachable) {
    useConnectivityStore.setState({
      reachabilityState: 'reachable',
      lastReachableAt: now,
      consecutiveNetworkFailures: 0,
      ...(current.forcedOffline
        ? {
            ...setOfflineDerivedState(current.browserOnline, false),
            lastRecoveryAt: now,
            counters: {
              ...current.counters,
              recovery_to_online_success: current.counters.recovery_to_online_success + 1,
            },
          }
        : {}),
    });
  } else {
    const shouldForce = current.browserOnline;
    useConnectivityStore.setState({
      reachabilityState: 'unreachable',
      ...(shouldForce
        ? {
            ...setOfflineDerivedState(current.browserOnline, true),
            counters: {
              ...current.counters,
              offline_mode_forced: current.counters.offline_mode_forced + (current.forcedOffline ? 0 : 1),
            },
          }
        : {}),
    });
  }

  const next = useConnectivityStore.getState();
  scheduleProbe(next.offlineModeActive ? PROBE_OFFLINE_INTERVAL_MS : PROBE_ONLINE_INTERVAL_MS);
}

async function setupNativeNetworkListener(): Promise<void> {
  const cap = (window as unknown as {
    Capacitor?: {
      Plugins?: {
        Network?: {
          getStatus?: () => Promise<{ connected: boolean }>;
          addListener?: (
            eventName: string,
            listenerFunc: (status: { connected: boolean }) => void,
          ) => Promise<{ remove: () => Promise<void> }>;
        };
      };
    };
  }).Capacitor;

  const network = cap?.Plugins?.Network;
  if (!network) return;

  try {
    const status = await network.getStatus?.();
    if (status) {
      const state = useConnectivityStore.getState();
      useConnectivityStore.setState(setOfflineDerivedState(status.connected, state.forcedOffline));
    }

    const handle = await network.addListener?.('networkStatusChange', (status) => {
      const state = useConnectivityStore.getState();
      useConnectivityStore.setState({
        ...setOfflineDerivedState(status.connected, state.forcedOffline),
      });
      scheduleProbe(status.connected ? 500 : 0);
    });

    if (handle) {
      networkListenerRemove = () => {
        handle.remove().catch(() => {});
      };
    }
  } catch (error) {
    log.warn('Native Network listener unavailable', error);
  }
}

const defaultCounters = (): ConnectivityCounters => ({
  network_unreachable_load_failures: 0,
  offline_mode_forced: 0,
  offline_queue_rebuild_count: 0,
  skip_storm_circuit_breaker_triggered: 0,
  recovery_to_online_success: 0,
  remote_command_enablement_mismatch: 0,
  pending_sync_local_url_local: 0,
  pending_sync_local_url_total: 0,
});

export const useConnectivityStore = create<ConnectivityState>((set, get) => ({
  browserOnline: typeof navigator !== 'undefined' ? navigator.onLine : true,
  reachabilityState: 'unknown',
  forcedOffline: false,
  offlineModeActive: typeof navigator !== 'undefined' ? !navigator.onLine : false,
  lastRecoveryAt: null,
  lastReachableAt: null,
  consecutiveNetworkFailures: 0,
  offlineTrackIds: new Set<string>(),
  counters: defaultCounters(),

  startMonitoring: () => {
    if (started || typeof window === 'undefined') return;
    started = true;

    browserOnlineListener = () => {
      const state = get();
      set({ ...setOfflineDerivedState(true, state.forcedOffline) });
      scheduleProbe(300);
    };
    browserOfflineListener = () => {
      const state = get();
      set({
        reachabilityState: 'unreachable',
        ...setOfflineDerivedState(false, state.forcedOffline),
      });
      scheduleProbe(PROBE_OFFLINE_INTERVAL_MS);
    };

    window.addEventListener('online', browserOnlineListener);
    window.addEventListener('offline', browserOfflineListener);
    window.addEventListener('offline-tracks-updated', () => {
      get().refreshOfflineTrackIds().catch(() => {});
    });

    get().refreshOfflineTrackIds().catch(() => {});
    void setupNativeNetworkListener();
    scheduleProbe(0);
  },

  stopMonitoring: () => {
    if (!started) return;
    started = false;
    if (probeTimer) {
      clearTimeout(probeTimer);
      probeTimer = null;
    }
    if (browserOnlineListener) window.removeEventListener('online', browserOnlineListener);
    if (browserOfflineListener) window.removeEventListener('offline', browserOfflineListener);
    browserOnlineListener = null;
    browserOfflineListener = null;
    if (networkListenerRemove) {
      networkListenerRemove();
      networkListenerRemove = null;
    }
  },

  refreshOfflineTrackIds: async () => {
    const ids = await getOfflineTrackIds();
    set({ offlineTrackIds: new Set(ids) });
  },

  noteStreamLoadFailure: (category) => {
    const state = get();
    const nextFailures = state.consecutiveNetworkFailures + 1;

    if (category === 'network-unreachable') {
      const shouldForce = !state.offlineModeActive;
      set({
        consecutiveNetworkFailures: nextFailures,
        reachabilityState: 'unreachable',
        ...setOfflineDerivedState(state.browserOnline, true),
        counters: {
          ...state.counters,
          network_unreachable_load_failures: state.counters.network_unreachable_load_failures + 1,
          offline_mode_forced: state.counters.offline_mode_forced + (shouldForce ? 1 : 0),
        },
      });
      scheduleProbe(PROBE_OFFLINE_INTERVAL_MS);
      return;
    }

    if (category === 'offline-unavailable') {
      set({ consecutiveNetworkFailures: 0 });
      return;
    }

    set({ consecutiveNetworkFailures: Math.max(0, nextFailures - 1) });
  },

  noteStreamLoadSuccess: () => {
    const state = get();
    if (state.consecutiveNetworkFailures !== 0) {
      set({ consecutiveNetworkFailures: 0 });
    }
  },

  incrementCounter: (name) => {
    const state = get();
    set({
      counters: {
        ...state.counters,
        [name]: state.counters[name] + 1,
      },
    });
  },

  incrementCounterBy: (name, amount) => {
    if (!Number.isFinite(amount) || amount === 0) return;
    const state = get();
    set({
      counters: {
        ...state.counters,
        [name]: state.counters[name] + amount,
      },
    });
  },
}));
