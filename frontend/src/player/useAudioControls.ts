/**
 * Lightweight hook that provides audio control functions (seek, togglePlayPause).
 *
 * Unlike useAudioEngine (which registers event listeners and effects and must only
 * be called once in AppShell), this hook is safe to call from multiple components
 * simultaneously — it contains no effects, only callbacks that operate on the
 * singleton engine instance.
 */
import { useCallback } from 'react';
import { usePlayerStore } from './playerStore';
import { useAudioSettingsStore } from './audioSettingsStore';
import { getEngine, getWebEngine } from './audio/engineInstance';
import { getEffectiveCrossfadeDuration } from './audio/eventHandlers';

export function useAudioControls() {
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const setCurrentTime = usePlayerStore((s) => s.setCurrentTime);
  const setCrossfadeState = usePlayerStore((s) => s.setCrossfadeState);
  const setNextTrackPreloaded = usePlayerStore((s) => s.setNextTrackPreloaded);

  const { crossfadeDuration, crossfadeEnabled } = useAudioSettingsStore();

  const seek = useCallback((time: number) => {
    if (!Number.isFinite(time)) return;

    const engine = getEngine();

    // Cancel crossfade if seeking back past the trigger point
    if (engine.isCrossfading?.()) {
      const webEngine = getWebEngine();
      if (webEngine) {
        const effectiveCrossfade = getEffectiveCrossfadeDuration(crossfadeEnabled, crossfadeDuration);
        const duration = engine.getDuration();
        if (duration - time > effectiveCrossfade + 1) {
          webEngine.cancelCrossfade();
          setCrossfadeState('idle');
          setNextTrackPreloaded(false);
        }
      }
    }

    engine.seek(time);
    setCurrentTime(time);
  }, [setCurrentTime, crossfadeEnabled, crossfadeDuration, setCrossfadeState, setNextTrackPreloaded]);

  const togglePlayPause = useCallback(() => {
    setIsPlaying(!isPlaying);
  }, [isPlaying, setIsPlaying]);

  return { seek, togglePlayPause };
}
