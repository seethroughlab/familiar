import { createLogger } from '../../utils/logger';

// ============================================================================
// Platform Detection
// ============================================================================

export const log = createLogger('AudioEngine');

export const isMobilePlatform = /iPad|iPhone|iPod|Android/i.test(navigator.userAgent);

// Mobile uses direct playback (background-safe, no Web Audio)
// Desktop uses Web Audio (visualizer, effects)
export const useDirectPlayback = isMobilePlatform;
export const useWebAudio = !isMobilePlatform;

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
