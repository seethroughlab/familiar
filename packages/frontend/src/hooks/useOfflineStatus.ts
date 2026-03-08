import { useEffect } from 'react';
import { useConnectivityStore } from '../stores/connectivityStore';

export interface OfflineStatus {
  isOnline: boolean;
  isOffline: boolean;
  offlineModeActive: boolean;
  reachabilityState: 'unknown' | 'checking' | 'reachable' | 'unreachable';
  lastRecoveryAt: number | null;
}

export function useOfflineStatus(): OfflineStatus {
  const offlineModeActive = useConnectivityStore((s) => s.offlineModeActive);
  const reachabilityState = useConnectivityStore((s) => s.reachabilityState);
  const lastRecoveryAt = useConnectivityStore((s) => s.lastRecoveryAt);
  const startMonitoring = useConnectivityStore((s) => s.startMonitoring);

  useEffect(() => {
    startMonitoring();
  }, [startMonitoring]);

  return {
    isOnline: !offlineModeActive,
    isOffline: offlineModeActive,
    offlineModeActive,
    reachabilityState,
    lastRecoveryAt,
  };
}
