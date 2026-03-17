import { createLogger } from '../../utils/logger';
import { isNativeApp, isMobile } from '../../utils/platform';

// ============================================================================
// Platform Detection
// ============================================================================

export const log = createLogger('AudioEngine', { forceVerbose: true });

export const isMobilePlatform = isMobile();

// Capacitor native app detection
export const isCapacitorNative = isNativeApp();

// On Capacitor native, bypass Web Audio entirely — iOS suspends AudioContext in background.
// Use plain HTMLAudioElement.volume for playback (direct mode). Desktop uses Web Audio (effects + visualizer).
export const useWebAudioOnThisPlatform = !isCapacitorNative;

// Capacitor native uses AVAudioEngine plugin for playback + effects (no HTMLAudioElement at all)
export const useNativeAudioEngine = isCapacitorNative;

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
log.info('v8 - native-audio-engine', {
  isMobilePlatform,
  isCapacitorNative,
  useWebAudioOnThisPlatform,
  useNativeAudioEngine,
});
