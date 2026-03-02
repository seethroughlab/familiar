import type { AudioEngine } from './types';
import { useNativeAudioEngine } from './platform';
import { WebAudioEngine } from './WebAudioEngine';
import { CapacitorEngine } from './CapacitorEngine';

/**
 * Factory: creates the appropriate AudioEngine for the current platform.
 * - Desktop/web: WebAudioEngine (AudioContext + HTMLAudioElement)
 * - Native iOS/Android: CapacitorEngine (FamiliarAudio Capacitor plugin)
 */
export function createEngine(): AudioEngine {
  return useNativeAudioEngine ? new CapacitorEngine() : new WebAudioEngine();
}
