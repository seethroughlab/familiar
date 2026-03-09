/* @vitest-environment jsdom */
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { useConnectivityStore } from '../connectivityStore';

vi.mock('../../services/offlineService', () => ({
  getOfflineTrackIds: vi.fn(async () => []),
}));

vi.mock('../../api/base', () => ({
  getApiUrl: (path: string) => path,
}));

const defaultCounters = () => ({
  network_unreachable_load_failures: 0,
  offline_mode_forced: 0,
  offline_queue_rebuild_count: 0,
  skip_storm_circuit_breaker_triggered: 0,
  recovery_to_online_success: 0,
  remote_command_enablement_mismatch: 0,
  pending_sync_local_url_local: 0,
  pending_sync_local_url_total: 0,
});

describe('connectivityStore', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    Object.defineProperty(window.navigator, 'onLine', {
      configurable: true,
      value: true,
    });
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true })));

    useConnectivityStore.getState().stopMonitoring();
    useConnectivityStore.setState({
      browserOnline: true,
      reachabilityState: 'unknown',
      forcedOffline: false,
      offlineModeActive: false,
      lastRecoveryAt: null,
      lastReachableAt: null,
      consecutiveNetworkFailures: 0,
      consecutiveProbeFailures: 0,
      offlineTrackIds: new Set<string>(),
      counters: defaultCounters(),
    });
  });

  afterEach(() => {
    useConnectivityStore.getState().stopMonitoring();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('does not force offline on first network-unreachable load failure', () => {
    useConnectivityStore.getState().noteStreamLoadFailure('network-unreachable');

    const state = useConnectivityStore.getState();
    expect(state.forcedOffline).toBe(false);
    expect(state.offlineModeActive).toBe(false);
    expect(state.reachabilityState).toBe('unreachable');
    expect(state.counters.network_unreachable_load_failures).toBe(1);
    expect(state.counters.offline_mode_forced).toBe(0);
  });

  it('forces offline mode after 2 consecutive network-unreachable load failures', () => {
    useConnectivityStore.getState().noteStreamLoadFailure('network-unreachable');
    useConnectivityStore.getState().noteStreamLoadFailure('network-unreachable');

    const state = useConnectivityStore.getState();
    expect(state.forcedOffline).toBe(true);
    expect(state.offlineModeActive).toBe(true);
    expect(state.reachabilityState).toBe('unreachable');
    expect(state.counters.network_unreachable_load_failures).toBe(2);
    expect(state.counters.offline_mode_forced).toBe(1);
  });

  it('does not force offline after a single failed probe', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false })));

    useConnectivityStore.getState().startMonitoring();
    await vi.advanceTimersByTimeAsync(10);

    const state = useConnectivityStore.getState();
    expect(state.reachabilityState).toBe('unreachable');
    expect(state.forcedOffline).toBe(false);
    expect(state.offlineModeActive).toBe(false);
    expect(state.consecutiveProbeFailures).toBe(1);
  });

  it('forces offline after 2 consecutive failed probes', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false })));

    useConnectivityStore.getState().startMonitoring();
    await vi.advanceTimersByTimeAsync(10);  // first probe fails
    await vi.advanceTimersByTimeAsync(8000 + 10);  // second probe fails (PROBE_OFFLINE_INTERVAL_MS)

    const state = useConnectivityStore.getState();
    expect(state.forcedOffline).toBe(true);
    expect(state.offlineModeActive).toBe(true);
    expect(state.consecutiveProbeFailures).toBe(2);
    expect(state.counters.offline_mode_forced).toBe(1);
  });

  it('clears forced offline automatically after successful reachability probe', async () => {
    useConnectivityStore.setState({
      forcedOffline: true,
      offlineModeActive: true,
      reachabilityState: 'unreachable',
      counters: {
        ...defaultCounters(),
        offline_mode_forced: 1,
      },
    });

    useConnectivityStore.getState().startMonitoring();
    await vi.advanceTimersByTimeAsync(10);

    const state = useConnectivityStore.getState();
    expect(state.reachabilityState).toBe('reachable');
    expect(state.forcedOffline).toBe(false);
    expect(state.offlineModeActive).toBe(false);
    expect(state.lastRecoveryAt).not.toBeNull();
    expect(state.counters.recovery_to_online_success).toBe(1);
  });

  it('does not force offline on offline-unavailable media errors', () => {
    useConnectivityStore.setState({ consecutiveNetworkFailures: 3 });

    useConnectivityStore.getState().noteStreamLoadFailure('offline-unavailable');

    const state = useConnectivityStore.getState();
    expect(state.forcedOffline).toBe(false);
    expect(state.offlineModeActive).toBe(false);
    expect(state.consecutiveNetworkFailures).toBe(0);
  });

  it('increments counters by amount for ratio tracking', () => {
    useConnectivityStore.getState().incrementCounterBy('pending_sync_local_url_total', 2);
    useConnectivityStore.getState().incrementCounterBy('pending_sync_local_url_local', 1);

    const state = useConnectivityStore.getState();
    expect(state.counters.pending_sync_local_url_total).toBe(2);
    expect(state.counters.pending_sync_local_url_local).toBe(1);
  });
});
