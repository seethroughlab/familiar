import { useEffect, useRef } from 'react';
import type { NavigateFunction } from 'react-router-dom';
import { useAudioEngine } from '../player/useAudioEngine';
import { useScrobbling } from './useScrobbling';
import { usePlayTracking } from './usePlayTracking';
import { initSyncListeners } from '../services/syncService';
import { initOfflineManifestSync } from '../services/offlineManifestService';
import { showSuccess, showWarning } from '../stores/toastStore';
import { initRemoteLogging } from '../services/remoteLogService';
import { usePlayerStore } from '../stores/playerStore';
import { createLogger } from '../utils/logger';

const log = createLogger('AppShell');

interface AppBootstrapDeps {
  navigate: NavigateFunction;
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
  navigate,
  setShowSettings,
  setShowFullPlayer,
  closeRightPanel,
}: AppBootstrapDeps): void {
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

  // Listen for show-playlist event from ChatPanel
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.playlistId) {
        navigate(`/playlists/${detail.playlistId}`);
      }
    };
    window.addEventListener('show-playlist', handler);
    return () => window.removeEventListener('show-playlist', handler);
  }, [navigate]);

  // Listen for show-ephemeral-playlist event
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.ephemeralId) {
        navigate(`/ephemeral/${detail.ephemeralId}`);
      }
    };
    window.addEventListener('show-ephemeral-playlist', handler);
    return () => window.removeEventListener('show-ephemeral-playlist', handler);
  }, [navigate]);

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
