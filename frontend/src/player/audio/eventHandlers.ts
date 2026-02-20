/**
 * Pure functions extracted from useAudioEngine event handlers for testability.
 * These encode the guard/decision logic without side effects.
 */

/**
 * Determines whether a 'ended' event should trigger playNext.
 * Returns false if the event should be ignored (wrong element, crossfade active, queue transition).
 */
export function shouldHandleEnded(
  target: HTMLAudioElement,
  elementA: HTMLAudioElement | null,
  directElementA: HTMLAudioElement | null,
  queueTransition: boolean,
  currentElementIsA: boolean,
  crossfadeActive: boolean,
): boolean {
  if (queueTransition) return false;
  const isA = (target === elementA || target === directElementA);
  if (currentElementIsA !== isA) return false;
  if (crossfadeActive) return false;
  return true;
}

/**
 * Determines what action to take when an audio element errors.
 * - 'ignore': do nothing (empty src, non-current element, not playing)
 * - 'cancel-crossfade': cancel the crossfade but keep playing current (next element errored)
 * - 'cancel-crossfade-and-stop': cancel crossfade and stop playback (current element errored during crossfade)
 * - 'stop': stop playback (current element errored, no crossfade)
 */
export function getErrorAction(
  target: HTMLAudioElement,
  currentElement: HTMLAudioElement | null,
  crossfadeActive: boolean,
  isPlaying: boolean,
): 'ignore' | 'cancel-crossfade' | 'cancel-crossfade-and-stop' | 'stop' {
  if (!target.src || target.src === window.location.href) return 'ignore';
  if (crossfadeActive) {
    if (target === currentElement) return 'cancel-crossfade-and-stop';
    return 'cancel-crossfade';
  }
  if (target !== currentElement) return 'ignore';
  if (!isPlaying) return 'ignore';
  return 'stop';
}

/**
 * Computes the effective crossfade duration based on settings and playback mode.
 * Centralizes the logic that was duplicated in the animation loop, seek, and getCrossfadeTrigger.
 */
export function getEffectiveCrossfadeDuration(
  crossfadeEnabled: boolean,
  crossfadeDuration: number,
  isDirectPlayback: boolean,
  mobileOverlap: number,
): number {
  return crossfadeEnabled
    ? (isDirectPlayback ? Math.max(crossfadeDuration, mobileOverlap) : crossfadeDuration)
    : (isDirectPlayback ? mobileOverlap : 0);
}

/**
 * Determines the crossfade/preload action based on time remaining.
 * - 'none': too early or too late for any action
 * - 'preload': in the preload window (~15s before crossfade point)
 * - 'crossfade': at or past the crossfade trigger point
 */
export function getCrossfadeTrigger(
  timeRemaining: number,
  crossfadeEnabled: boolean,
  crossfadeDuration: number,
  isDirectPlayback: boolean,
  mobileOverlap: number,
): 'none' | 'preload' | 'crossfade' {
  const effectiveCrossfade = getEffectiveCrossfadeDuration(
    crossfadeEnabled, crossfadeDuration, isDirectPlayback, mobileOverlap,
  );

  if (timeRemaining <= effectiveCrossfade && timeRemaining > 0.1) return 'crossfade';
  if (timeRemaining <= effectiveCrossfade + 15 && timeRemaining > effectiveCrossfade + 1) return 'preload';
  return 'none';
}
