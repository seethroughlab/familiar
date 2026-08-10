import { useEffect, useRef } from 'react';
import { useAudioEngine } from '../player/useAudioEngine';
import { useScrobbling } from './useScrobbling';
import { usePlayTracking } from './usePlayTracking';
import { initSyncListeners } from '../services/syncService';
import { initOfflineManifestSync } from '../services/offlineManifestService';
import { initQueueSync, reconcileWithServer } from '../services/queueSyncService';
import { useQueueSyncStore } from '../stores/queueSyncStore';
import { showSuccess, showWarning } from '../stores/toastStore';
import { initRemoteLogging } from '../services/remoteLogService';
import { usePlayerStore } from '../stores/playerStore';
import { createLogger } from '../utils/logger';

const log = createLogger('AppShell');

interface AppBootstrapDeps {
  setShowSettings: (v: boolean) => void;
  setShowFullPlayer: (v: boolean) => void;
  closeRightPanel: () => void;
}

/**
 * One-time initialization effects extracted from AppShell.
 * Audio engine, sync listeners, remote logging, player hydration,
 * custom event listeners, and triple-tap recovery.
 */
export function useAppBootstrap({
  setShowSettings,
  setShowFullPlayer,
  closeRightPanel,
}: AppBootstrapDeps): void {
  const queueSyncEnabled = useQueueSyncStore((s) => s.enabled);

  // Initialize Audio Engine
  useAudioEngine();
  useScrobbling();
  usePlayTracking();

  // Initialize offline sync listeners
  useEffect(() => {
    return initSyncListeners({ onSuccess: showSuccess, onWarning: showWarning });
  }, []);

  // Keep the offline ranking manifest current (ADR-0006). Rebuilds whenever the
  // downloaded set changes — the device is online by definition when that happens,
  // since the set only changes by downloading.
  useEffect(() => {
    return initOfflineManifestSync();
  }, []);

  // Mirror the playback queue to the server (ADR-0003), behind a per-device flag.
  // Reconciliation runs after hydration has already restored the local queue, so the
  // listener never waits on the network to see their queue — the server's copy only
  // replaces it when it is genuinely newer, which is the cross-device handoff.
  //
  // Keyed on the flag so toggling it in Settings starts or stops syncing immediately;
  // without the dependency, turning it on would appear to do nothing until a reload.
  useEffect(() => {
    if (!queueSyncEnabled) return;
    const stop = initQueueSync();
    reconcileWithServer().catch(() => {
      // Non-fatal: the local replica is authoritative for playback either way.
    });
    return stop;
  }, [queueSyncEnabled]);

  // Initialize remote logging (captures frontend logs to backend)
  useEffect(() => {
    return initRemoteLogging();
  }, []);

  // Listen for navigate-to-settings event
  useEffect(() => {
    const handler = () => setShowSettings(true);
    window.addEventListener('navigate-to-settings', handler);
    return () => window.removeEventListener('navigate-to-settings', handler);
  }, [setShowSettings]);


  // Hydrate player state from IndexedDB
  const hydrate = usePlayerStore((state) => state.hydrate);
  useEffect(() => {
    hydrate();
  }, [hydrate]);

  // Triple-tap recovery for mobile
  const tapCountRef = useRef(0);
  const lastTapTimeRef = useRef(0);
  useEffect(() => {
    const handleTripleTap = () => {
      const now = Date.now();
      if (now - lastTapTimeRef.current < 500) {
        tapCountRef.current++;
        if (tapCountRef.current >= 3) {
          log.info('[AppShell] Triple-tap recovery triggered');
          setShowFullPlayer(false);
          closeRightPanel();
          setShowSettings(false);
          tapCountRef.current = 0;
        }
      } else {
        tapCountRef.current = 1;
      }
      lastTapTimeRef.current = now;
    };

    if ('ontouchstart' in window) {
      document.addEventListener('touchstart', handleTripleTap);
      return () => document.removeEventListener('touchstart', handleTripleTap);
    }
  }, [setShowFullPlayer, closeRightPanel, setShowSettings]);
}
