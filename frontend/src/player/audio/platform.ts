import { createLogger } from '../../utils/logger';

// ============================================================================
// Platform Detection
// ============================================================================

export const log = createLogger('AudioEngine', { forceVerbose: true });

export const isMobilePlatform = /iPad|iPhone|iPod|Android/i.test(navigator.userAgent);

// Capacitor native app keeps the Web Audio context alive via AVAudioSession,
// so we can safely use Web Audio for effects and visualizers.
const isCapacitorNative = !!(window as unknown as Record<string, unknown>).Capacitor &&
  (window as unknown as { Capacitor: { isNativePlatform?: () => boolean } })
    .Capacitor.isNativePlatform?.() === true;

// Mobile PWA/Safari uses direct playback (background-safe, no Web Audio)
// Desktop and Capacitor native use Web Audio (visualizer, effects)
export const useDirectPlayback = isMobilePlatform && !isCapacitorNative;
export const useWebAudio = !isMobilePlatform || isCapacitorNative;

// Minimum transition overlap on mobile to keep audio session alive.
// Without this, play() after the 'ended' event is rejected by iOS Safari
// because the audio session has ended and there's no recent user gesture.
export const MOBILE_TRANSITION_OVERLAP = 0.3;

// Track last logged time to avoid spamming (log every 10 seconds)
export let lastDebugLogTime = 0;
export let lastLoggedTrackId: string | null = null;

export function setLastDebugLogTime(time: number): void {
  lastDebugLogTime = time;
}

export function setLastLoggedTrackId(id: string | null): void {
  lastLoggedTrackId = id;
}

// Log version and platform detection on load
log.info('v5 - simplified mobile', {
  isMobilePlatform,
  useDirectPlayback,
  useWebAudio,
});
