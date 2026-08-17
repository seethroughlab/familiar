import { createLogger } from '../../utils/logger';
import { isMobile } from '../../utils/platform';

// ============================================================================
// Platform Detection
// ============================================================================

export const log = createLogger('AudioEngine', { forceVerbose: true });

export const isMobilePlatform = isMobile();

// `isCapacitorNative`, `useWebAudioOnThisPlatform` and `useNativeAudioEngine` were here. The first
// tested for a Capacitor app deleted on 2026-08-11 (ADR-0001 point 6), so it was permanently false;
// the other two were derived from it and had no consumers at all. Every remaining audio path is
// Web Audio in an ordinary browser.

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
log.info('v9 - web audio only', { isMobilePlatform });
