import { revokeOfflineTrackUrl } from '../../services/offlineService';
import type { Track } from '../../types';
import { usePlayerStore } from '../../stores/playerStore';
import { useDirectPlayback, MOBILE_TRANSITION_OVERLAP, log } from './platform';
import {
  getCurrentElement,
  getNextElement,
  getCurrentGain,
  getNextGain,
  getGlobalAudioContext,
  getGlobalMasterGain,
  getCrossfadeContext,
  setCrossfadeContext,
  getCurrentOfflineUrl,
  setCurrentOfflineUrl,
  getNextOfflineUrl,
  setNextOfflineUrl,
  getCurrentMasterVolume,
  toggleCurrentElement,
  setLoadedTrackId,
  getPreloadingTrackId,
  setPreloadingTrackId,
  setEarlyPreloadedTrackId,
  cleanupElement,
  setElementVolume,
  getTrackUrl,
} from './audioGraph';

// ============================================================================
// Preload next track
// ============================================================================

export async function preloadNextTrack(trackId: string): Promise<boolean> {
  if (getPreloadingTrackId() === trackId) return false;

  setPreloadingTrackId(trackId);
  const nextElement = getNextElement();
  if (!nextElement) return false;

  try {
    const nextOfflineUrl = getNextOfflineUrl();
    if (nextOfflineUrl) {
      revokeOfflineTrackUrl(nextOfflineUrl);
      setNextOfflineUrl(null);
    }

    const { url, isOffline } = await getTrackUrl(trackId);
    if (isOffline) setNextOfflineUrl(url);

    nextElement.src = url;
    nextElement.load();

    return new Promise((resolve) => {
      const cleanup = () => {
        clearTimeout(timeout);
        nextElement.removeEventListener('canplay', onCanPlay);
        nextElement.removeEventListener('error', onError);
      };

      const timeout = setTimeout(() => {
        cleanup();
        log.warn('Preload timeout (10s)', { trackId, readyState: nextElement.readyState, networkState: nextElement.networkState });
        setPreloadingTrackId(null);
        resolve(false);
      }, 10000);

      const onCanPlay = () => {
        cleanup();
        setPreloadingTrackId(null);
        resolve(true);
      };
      const onError = () => {
        cleanup();
        const mediaError = nextElement.error;
        log.warn('Preload error', { trackId, errorCode: mediaError?.code, errorMessage: mediaError?.message });
        setPreloadingTrackId(null);
        resolve(false);
      };
      nextElement.addEventListener('canplay', onCanPlay);
      nextElement.addEventListener('error', onError);
    });
  } catch (e) {
    log.error('Error preloading track:', e);
    setPreloadingTrackId(null);
    return false;
  }
}

// ============================================================================
// Complete crossfade
// ============================================================================

export function completeCrossfade(
  setCrossfadeStateFn: (state: 'idle' | 'preloading' | 'crossfading') => void,
  setNextTrackPreloadedFn: (preloaded: boolean) => void,
  onCompleteFn?: () => void,
): void {
  if (!getCrossfadeContext()) return; // already completed or never started

  {
    const { currentTrack: track } = usePlayerStore.getState();
    log.debug('completeCrossfade called', {
      trackId: track?.id,
      trackTitle: track?.title,
    });
  }

  const oldElement = getCurrentElement();
  cleanupElement(oldElement, getCurrentOfflineUrl());

  setCurrentOfflineUrl(getNextOfflineUrl());
  setNextOfflineUrl(null);
  toggleCurrentElement();

  const ctx = getCrossfadeContext();
  if (ctx?.timeoutId) clearTimeout(ctx.timeoutId);
  if (ctx?.animationFrameId) cancelAnimationFrame(ctx.animationFrameId);
  setCrossfadeContext(null);

  setPreloadingTrackId(null);
  setEarlyPreloadedTrackId(null);

  const currentId = usePlayerStore.getState().currentTrack?.id;
  if (currentId) setLoadedTrackId(currentId);

  if (useDirectPlayback) {
    const newCurrentElement = getCurrentElement();
    const newNextElement = getNextElement();
    setElementVolume(newCurrentElement, getCurrentMasterVolume());
    setElementVolume(newNextElement, 0);
  }

  setCrossfadeStateFn('idle');
  setNextTrackPreloadedFn(false);
  onCompleteFn?.();
}

// ============================================================================
// Execute crossfade
// ============================================================================

export function executeCrossfade(
  duration: number,
  nextTrack: Track,
  advanceToNextTrackFn: (track: Track) => void,
  setCrossfadeStateFn: (state: 'idle' | 'preloading' | 'crossfading') => void,
  setNextTrackPreloadedFn: (preloaded: boolean) => void,
  onCompleteFn?: () => void,
): void {
  const currentElement = getCurrentElement();
  const nextElement = getNextElement();
  if (!nextElement) return;

  log.debug('executeCrossfade called', {
    crossfadeDuration: duration,
    nextTrackId: nextTrack.id,
    nextTrackTitle: nextTrack.title,
    currentElementTime: currentElement?.currentTime,
    currentElementDuration: currentElement?.duration,
    nextElementReadyState: nextElement?.readyState,
  });

  const masterVolume = getCurrentMasterVolume();

  if (useDirectPlayback) {
    if (duration <= MOBILE_TRANSITION_OVERLAP) {
      // Gapless / instant transition: play next at full volume with brief overlap
      nextElement.volume = masterVolume;
      nextElement.play().catch(err => log.error('Play failed:', err));
      setCrossfadeContext({
        isActive: true,
        startTime: performance.now(),
        duration,
        timeoutId: setTimeout(
          () => completeCrossfade(setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn),
          duration * 1000,
        ),
      });
    } else {
      // Direct mode (mobile): animate audioElement.volume
      const startTime = performance.now();
      const durationMs = duration * 1000;

      nextElement.volume = 0;
      nextElement.play().catch(err => log.error('Play failed:', err));

      const animateCrossfade = () => {
        const elapsed = performance.now() - startTime;
        const progress = Math.min(elapsed / durationMs, 1);
        const currentVol = (1 - progress) * masterVolume;
        const nextVol = progress * masterVolume;

        if (currentElement) currentElement.volume = currentVol;
        nextElement.volume = nextVol;

        if (progress < 1) {
          const ctx = getCrossfadeContext();
          if (ctx) {
            ctx.animationFrameId = requestAnimationFrame(animateCrossfade);
          }
        } else {
          completeCrossfade(setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);
        }
      };

      setCrossfadeContext({
        isActive: true,
        startTime: performance.now(),
        duration,
        timeoutId: null,
        animationFrameId: requestAnimationFrame(animateCrossfade),
      });
    }
  } else {
    // Web Audio mode: use gain nodes
    const globalAudioContext = getGlobalAudioContext();
    const globalMasterGain = getGlobalMasterGain();
    if (!globalAudioContext || !globalMasterGain) return;
    const currentGain = getCurrentGain();
    const nextGain = getNextGain();
    if (!currentGain || !nextGain) return;

    const now = globalAudioContext.currentTime;

    currentGain.gain.cancelScheduledValues(now);
    nextGain.gain.cancelScheduledValues(now);

    if (duration === 0) {
      currentGain.gain.setValueAtTime(0, now);
      nextGain.gain.setValueAtTime(1, now);
      nextElement.play().catch(err => log.error('Play failed:', err));
    } else {
      currentGain.gain.setValueAtTime(1, now);
      currentGain.gain.linearRampToValueAtTime(0, now + duration);
      nextGain.gain.setValueAtTime(0, now);
      nextGain.gain.linearRampToValueAtTime(1, now + duration);
      nextElement.play().catch(err => log.error('Play failed:', err));
    }

    setCrossfadeContext({
      isActive: true,
      startTime: now,
      duration,
      timeoutId: setTimeout(
        () => completeCrossfade(setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn),
        duration * 1000,
      ),
    });
  }

  setLoadedTrackId(nextTrack.id);
  advanceToNextTrackFn(nextTrack);
}

// ============================================================================
// Cancel crossfade
// ============================================================================

export function cancelCrossfade(
  setCrossfadeStateFn: (state: 'idle' | 'preloading' | 'crossfading') => void,
  setNextTrackPreloadedFn: (preloaded: boolean) => void,
): void {
  const ctx = getCrossfadeContext();
  if (!ctx) return;

  log.debug('cancelCrossfade', {
    trackId: usePlayerStore.getState().currentTrack?.id,
    crossfadeActive: ctx.isActive,
  });

  const currentElement = getCurrentElement();
  const nextElement = getNextElement();
  const masterVolume = getCurrentMasterVolume();

  if (useDirectPlayback) {
    if (ctx.animationFrameId) cancelAnimationFrame(ctx.animationFrameId);
    setElementVolume(currentElement, masterVolume);
    setElementVolume(nextElement, 0);
  } else {
    const globalAudioContext = getGlobalAudioContext();
    if (globalAudioContext) {
      const now = globalAudioContext.currentTime;
      const currentGain = getCurrentGain();
      const nextGain = getNextGain();
      currentGain?.gain.cancelScheduledValues(now);
      nextGain?.gain.cancelScheduledValues(now);
      currentGain?.gain.setValueAtTime(1, now);
      nextGain?.gain.setValueAtTime(0, now);
    }
  }

  cleanupElement(nextElement, getNextOfflineUrl());
  setNextOfflineUrl(null);

  if (ctx.timeoutId) clearTimeout(ctx.timeoutId);
  setCrossfadeContext(null);

  setPreloadingTrackId(null);
  setEarlyPreloadedTrackId(null);
  setCrossfadeStateFn('idle');
  setNextTrackPreloadedFn(false);
}
