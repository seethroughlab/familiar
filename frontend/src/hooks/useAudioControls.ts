/**
 * Lightweight hook that provides audio control functions (seek, togglePlayPause).
 *
 * Unlike useAudioEngine (which registers event listeners and effects and must only
 * be called once in AppShell), this hook is safe to call from multiple components
 * simultaneously — it contains no effects, only callbacks that operate on the
 * singleton audio graph state.
 */
import { useCallback } from 'react';
import { usePlayerStore } from '../stores/playerStore';
import { useAudioSettingsStore } from '../stores/audioSettingsStore';

import {
  getCurrentElement,
  getCrossfadeContext,
} from './audio/audioGraph';

import {
  cancelCrossfade as cancelCrossfadeModule,
} from './audio/crossfade';

import {
  getEffectiveCrossfadeDuration,
} from './audio/eventHandlers';

import {
  useDirectPlayback,
  MOBILE_TRANSITION_OVERLAP,
  log,
} from './audio/platform';

export function useAudioControls() {
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const setCurrentTime = usePlayerStore((s) => s.setCurrentTime);
  const setCrossfadeState = usePlayerStore((s) => s.setCrossfadeState);
  const setNextTrackPreloaded = usePlayerStore((s) => s.setNextTrackPreloaded);

  const { crossfadeDuration, crossfadeEnabled } = useAudioSettingsStore();

  const cancelCrossfade = useCallback(() => {
    cancelCrossfadeModule(setCrossfadeState, setNextTrackPreloaded);
  }, [setCrossfadeState, setNextTrackPreloaded]);

  const seek = useCallback((time: number) => {
    const el = getCurrentElement();
    if (!el) return;

    if (getCrossfadeContext()?.isActive) {
      const effectiveCrossfade = getEffectiveCrossfadeDuration(
        crossfadeEnabled, crossfadeDuration, useDirectPlayback, MOBILE_TRANSITION_OVERLAP,
      );
      if (el.duration - time > effectiveCrossfade + 1) cancelCrossfade();
    }

    if (!Number.isFinite(time)) return;

    try {
      el.currentTime = time;
      setCurrentTime(time);
    } catch (e) {
      log.error('Seek failed', e);
    }
  }, [setCurrentTime, crossfadeEnabled, crossfadeDuration, cancelCrossfade]);

  const togglePlayPause = useCallback(() => {
    setIsPlaying(!isPlaying);
  }, [isPlaying, setIsPlaying]);

  return { seek, togglePlayPause };
}
