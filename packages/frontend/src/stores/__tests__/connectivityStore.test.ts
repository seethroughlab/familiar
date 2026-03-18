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

  it('noteStreamLoadSuccess resets failure counter', () => {
    useConnectivityStore.setState({ consecutiveNetworkFailures: 3 });

    useConnectivityStore.getState().noteStreamLoadSuccess();

    expect(useConnectivityStore.getState().consecutiveNetworkFailures).toBe(0);
  });

  it('refreshOfflineTrackIds updates the Set', async () => {
    const { getOfflineTrackIds } = await import('../../services/offlineService');
    (getOfflineTrackIds as ReturnType<typeof vi.fn>).mockResolvedValueOnce(['a', 'b']);

    await useConnectivityStore.getState().refreshOfflineTrackIds();

    const ids = useConnectivityStore.getState().offlineTrackIds;
    expect(ids.has('a')).toBe(true);
    expect(ids.has('b')).toBe(true);
    expect(ids.size).toBe(2);
  });

  it('browser offline event sets offlineModeActive', async () => {
    useConnectivityStore.getState().startMonitoring();
    await vi.advanceTimersByTimeAsync(10); // let initial probe run

    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: false });
    window.dispatchEvent(new Event('offline'));

    const state = useConnectivityStore.getState();
    expect(state.browserOnline).toBe(false);
    expect(state.offlineModeActive).toBe(true);
  });

  it('browser online event triggers recovery probe', async () => {
    // Start in offline state
    useConnectivityStore.setState({
      browserOnline: false,
      reachabilityState: 'unreachable',
      offlineModeActive: true,
    });
    useConnectivityStore.getState().startMonitoring();
    await vi.advanceTimersByTimeAsync(10); // initial probe

    // Go online
    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: true });
    window.dispatchEvent(new Event('online'));

    // Recovery probe fires after 300ms delay
    await vi.advanceTimersByTimeAsync(400);

    const state = useConnectivityStore.getState();
    expect(state.browserOnline).toBe(true);
    expect(state.reachabilityState).toBe('reachable');
  });

  it('probe uses 8s interval when offline, 20s when online', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);

    useConnectivityStore.getState().startMonitoring();
    await vi.advanceTimersByTimeAsync(10); // initial probe
    const callsAfterInit = fetchMock.mock.calls.length;

    // Online: next probe at 20s — no probe before that
    await vi.advanceTimersByTimeAsync(19_000);
    expect(fetchMock.mock.calls.length).toBe(callsAfterInit);
    await vi.advanceTimersByTimeAsync(1_100);
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsAfterInit); // probe at ~20s

    // Switch to offline probing — the probe that just ran was reachable,
    // so schedule the next probe to fail
    fetchMock.mockImplementation(async () => ({ ok: false }));
    // Wait for the next online-interval probe to fire and fail
    await vi.advanceTimersByTimeAsync(20_100);
    const callsAfterFirstFail = fetchMock.mock.calls.length;

    // Now offline interval (8s) should apply
    await vi.advanceTimersByTimeAsync(7_000);
    expect(fetchMock.mock.calls.length).toBe(callsAfterFirstFail); // no probe yet at 7s
    await vi.advanceTimersByTimeAsync(1_100);
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsAfterFirstFail); // probe at ~8s
  });

  it('startMonitoring is idempotent', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);

    useConnectivityStore.getState().startMonitoring();
    useConnectivityStore.getState().startMonitoring(); // second call should be a no-op
    await vi.advanceTimersByTimeAsync(10);

    // Only one initial probe should have fired
    expect(fetchMock.mock.calls.length).toBe(1);
  });

  it('stopMonitoring clears timers', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);

    useConnectivityStore.getState().startMonitoring();
    await vi.advanceTimersByTimeAsync(10); // initial probe
    const callsAfterInit = fetchMock.mock.calls.length;

    useConnectivityStore.getState().stopMonitoring();
    await vi.advanceTimersByTimeAsync(30_000); // well past any probe interval

    expect(fetchMock.mock.calls.length).toBe(callsAfterInit); // no more probes
  });

  it('noteStreamLoadFailure with "other" category does not escalate counter', () => {
    useConnectivityStore.setState({ consecutiveNetworkFailures: 0 });

    useConnectivityStore.getState().noteStreamLoadFailure('other');

    // 'other' increments by 1 then decrements by 1 (net 0)
    const state = useConnectivityStore.getState();
    expect(state.consecutiveNetworkFailures).toBe(0);
    expect(state.forcedOffline).toBe(false);
  });
});
