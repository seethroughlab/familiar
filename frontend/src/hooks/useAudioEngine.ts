import { useEffect, useCallback } from 'react';
import { usePlayerStore } from '../stores/playerStore';
import { useAudioSettingsStore } from '../stores/audioSettingsStore';
import { tracksApi } from '../api/client';
import type { Track } from '../types';
import {
  getOfflineTrack,
  createOfflineTrackUrl,
  revokeOfflineTrackUrl,
} from '../services/offlineService';
import { showError } from '../stores/toastStore';
import { createLogger } from '../utils/logger';
import { useAudioEngineContext } from '../contexts/AudioEngineContext';

const log = createLogger('AudioEngine');

// Minimum transition overlap on mobile to keep audio session alive.
const MOBILE_TRANSITION_OVERLAP = 0.3;

// ============================================================================
// State that is specific to the playback logic
// ============================================================================

interface CrossfadeContext {
  isActive: boolean;
  startTime: number;
  duration: number;
  timeoutId: ReturnType<typeof setTimeout> | null;
  animationFrameId?: number;
}

// Module-level tracking state
// We keep these here for now to maintain behavior across re-renders without full store refactor
// but they no longer hold the actual AUDIO NODES (which are in context)
let crossfadeContext: CrossfadeContext | null = null;
let currentOfflineUrl: string | null = null;
let nextOfflineUrl: string | null = null;
let currentMasterVolume = 1;

let preloadingTrackId: string | null = null;
let queueTransition = false;

// Track which element is currently active
let currentElementIsA = true;

// ============================================================================
// Helper Functions
// ============================================================================

async function getTrackUrl(trackId: string): Promise<{ url: string; isOffline: boolean }> {
  const offlineBlob = await getOfflineTrack(trackId);
  if (offlineBlob) {
    return { url: createOfflineTrackUrl(offlineBlob), isOffline: true };
  }
  return { url: tracksApi.getStreamUrl(trackId), isOffline: false };
}

function cleanupElement(element: HTMLAudioElement | null, offlineUrl: string | null): void {
  if (element) {
    element.pause();
    element.currentTime = 0;
    element.src = '';
    element.load();
  }
  if (offlineUrl) {
    revokeOfflineTrackUrl(offlineUrl);
  }
}

function setElementVolume(element: HTMLAudioElement | null, volume: number): void {
  if (element) {
    element.volume = Math.max(0, Math.min(1, volume));
  }
}

// ============================================================================
// Main Hook
// ============================================================================

export function useAudioEngine() {
  const { audioGraph, isInitialized, initializeAudioGraph, platform } = useAudioEngineContext();
  const { useDirectPlayback, useWebAudio } = platform;

  const {
    currentTrack,
    isPlaying,
    volume,
    setCurrentTime,
    setDuration,
    setIsPlaying,
    playNext,
    setCrossfadeState,
    setNextTrackPreloaded,
    advanceToNextTrack,
    setIsLoadingAudio,
  } = usePlayerStore();

  const { crossfadeDuration, crossfadeEnabled, normalizationEnabled, normalizationTargetLufs, normalizationPreamp, normalizationPreventClipping } = useAudioSettingsStore();

  // --------------------------------------------------------------------------
  // Element Accessors (scoped to context)
  // --------------------------------------------------------------------------

  const getCurrentElement = useCallback((): HTMLAudioElement | null => {
    const graph = audioGraph.current;
    if (useWebAudio) {
      return currentElementIsA ? graph.webAudioElementA : graph.webAudioElementB;
    } else {
      return currentElementIsA ? graph.directElementA : graph.directElementB;
    }
  }, [audioGraph, useWebAudio]);

  const getNextElement = useCallback((): HTMLAudioElement | null => {
    const graph = audioGraph.current;
    if (useWebAudio) {
      return currentElementIsA ? graph.webAudioElementB : graph.webAudioElementA;
    } else {
      return currentElementIsA ? graph.directElementB : graph.directElementA;
    }
  }, [audioGraph, useWebAudio]);

  const getCurrentGain = useCallback((): GainNode | null => {
    if (!useWebAudio) return null;
    const graph = audioGraph.current;
    return currentElementIsA ? graph.gainA : graph.gainB;
  }, [audioGraph, useWebAudio]);

  const getNextGain = useCallback((): GainNode | null => {
    if (!useWebAudio) return null;
    const graph = audioGraph.current;
    return currentElementIsA ? graph.gainB : graph.gainA;
  }, [audioGraph, useWebAudio]);

  const getCurrentNormGain = useCallback((): GainNode | null => {
    if (!useWebAudio) return null;
    const graph = audioGraph.current;
    return currentElementIsA ? graph.normGainA : graph.normGainB;
  }, [audioGraph, useWebAudio]);

  const getNextNormGain = useCallback((): GainNode | null => {
    if (!useWebAudio) return null;
    const graph = audioGraph.current;
    return currentElementIsA ? graph.normGainB : graph.normGainA;
  }, [audioGraph, useWebAudio]);


  // --------------------------------------------------------------------------
  // Normalization
  // --------------------------------------------------------------------------

  const computeNormalizationGain = useCallback((track: Track | null): number => {
    if (!track?.features?.loudness_lufs) return 1;
    if (!normalizationEnabled) return 1;

    const lufs = track.features.loudness_lufs;
    // gain_db = target - measured + preamp
    let gainDb = normalizationTargetLufs - lufs + normalizationPreamp;

    if (normalizationPreventClipping && track.features.track_peak) {
      const maxGainDb = -20 * Math.log10(track.features.track_peak + 1e-10);
      gainDb = Math.min(gainDb, maxGainDb);
    }

    return Math.pow(10, gainDb / 20);
  }, [normalizationEnabled, normalizationTargetLufs, normalizationPreamp, normalizationPreventClipping]);

  const applyNormalizationGain = useCallback((track: Track | null, isCurrent: boolean): void => {
    if (!useWebAudio) return;
    const normGain = isCurrent ? getCurrentNormGain() : getNextNormGain();
    if (!normGain) return;

    const linearGain = computeNormalizationGain(track);
    normGain.gain.value = linearGain;
  }, [useWebAudio, getCurrentNormGain, getNextNormGain, computeNormalizationGain]);


  // --------------------------------------------------------------------------
  // Lifecycle & Initialization
  // --------------------------------------------------------------------------

  useEffect(() => {
    initializeAudioGraph();
  }, [initializeAudioGraph]);

  // Handle errors and ended events
  useEffect(() => {
    if (!isInitialized) return;

    const graph = audioGraph.current;
    const elements = [
      graph.webAudioElementA, graph.webAudioElementB,
      graph.directElementA, graph.directElementB
    ].filter((e): e is HTMLAudioElement => e !== null);

    const handleEnded = (e: Event) => {
      const target = e.target as HTMLAudioElement;

      // Identify if this element is A or B
      const isA = (target === graph.webAudioElementA || target === graph.directElementA);

      if (queueTransition) return;

      // Only trigger playNext if this is the CURRENT element ending and we aren't crossfading
      if (currentElementIsA === isA && !crossfadeContext?.isActive) {
        playNext();
      }
    };

    const handleError = (e: Event) => {
      const target = e.target as HTMLAudioElement;
      if (!target.src || target.src === window.location.href) return;

      const currentElement = getCurrentElement();
      if (target !== currentElement) return;

      const { isPlaying: playing } = usePlayerStore.getState();
      if (!playing) return;

      const mediaError = target.error;
      log.error('Playback error:', mediaError);

      // Only show error toast if we haven't shown one recently for this track
      // (Simple implementation for now)
      showError('Playback error', {
        description: mediaError?.message || 'Failed to play track'
      });

      setIsPlaying(false);
      setIsLoadingAudio(false);
    };

    elements.forEach(el => {
      el.addEventListener('ended', handleEnded);
      el.addEventListener('error', handleError);
    });

    return () => {
      elements.forEach(el => {
        el.removeEventListener('ended', handleEnded);
        el.removeEventListener('error', handleError);
      });
    };
  }, [isInitialized, audioGraph, playNext, setIsPlaying, setIsLoadingAudio, getCurrentElement]);


  // --------------------------------------------------------------------------
  // Preload next track
  // --------------------------------------------------------------------------
  const preloadNextTrack = useCallback(async (trackId: string): Promise<boolean> => {
    if (preloadingTrackId === trackId) return false;

    preloadingTrackId = trackId;
    const nextElement = getNextElement();
    if (!nextElement) return false;

    try {
      if (nextOfflineUrl) {
        revokeOfflineTrackUrl(nextOfflineUrl);
        nextOfflineUrl = null;
      }

      const { url, isOffline } = await getTrackUrl(trackId);
      if (isOffline) nextOfflineUrl = url;

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
          preloadingTrackId = null;
          resolve(false);
        }, 10000);

        const onCanPlay = () => {
          cleanup();
          preloadingTrackId = null;
          resolve(true);
        };
        const onError = () => {
          cleanup();
          preloadingTrackId = null;
          resolve(false);
        };
        nextElement.addEventListener('canplay', onCanPlay);
        nextElement.addEventListener('error', onError);
      });
    } catch (e) {
      log.error('Error preloading track:', e);
      preloadingTrackId = null;
      return false;
    }
  }, [getNextElement]);

  // --------------------------------------------------------------------------
  // Complete crossfade
  // --------------------------------------------------------------------------
  const completeCrossfade = useCallback(() => {
    const oldElement = getCurrentElement();
    cleanupElement(oldElement, currentOfflineUrl);

    currentOfflineUrl = nextOfflineUrl;
    nextOfflineUrl = null;
    currentElementIsA = !currentElementIsA;

    if (crossfadeContext?.timeoutId) clearTimeout(crossfadeContext.timeoutId);
    if (crossfadeContext?.animationFrameId) cancelAnimationFrame(crossfadeContext.animationFrameId);
    crossfadeContext = null;

    preloadingTrackId = null;

    // Resume volume levels
    if (useDirectPlayback) {
      const newCurrentElement = getCurrentElement();
      const newNextElement = getNextElement();
      setElementVolume(newCurrentElement, currentMasterVolume);
      setElementVolume(newNextElement, 0);
    }

    setCrossfadeState('idle');
    setNextTrackPreloaded(false);
  }, [getCurrentElement, getNextElement, useDirectPlayback, setCrossfadeState, setNextTrackPreloaded]);

  // --------------------------------------------------------------------------
  // Cancel crossfade
  // --------------------------------------------------------------------------
  const cancelCrossfade = useCallback(() => {
    if (!crossfadeContext) return;

    const graph = audioGraph.current;

    if (useDirectPlayback) {
      if (crossfadeContext.animationFrameId) cancelAnimationFrame(crossfadeContext.animationFrameId);
      const current = getCurrentElement();
      const next = getNextElement();
      setElementVolume(current, currentMasterVolume);
      setElementVolume(next, 0);
    } else {
      const ctx = graph.audioContext;
      if (ctx) {
        const now = ctx.currentTime;
        const currentGain = getCurrentGain();
        const nextGain = getNextGain();
        currentGain?.gain.cancelScheduledValues(now);
        nextGain?.gain.cancelScheduledValues(now);
        currentGain?.gain.setValueAtTime(1, now);
        nextGain?.gain.setValueAtTime(0, now);
      }
    }

    const nextEl = getNextElement();
    cleanupElement(nextEl, nextOfflineUrl);
    nextOfflineUrl = null;

    if (crossfadeContext.timeoutId) clearTimeout(crossfadeContext.timeoutId);
    crossfadeContext = null;
    setCrossfadeState('idle');
  }, [audioGraph, useDirectPlayback, getCurrentElement, getNextElement, getCurrentGain, getNextGain, setCrossfadeState]);


  // --------------------------------------------------------------------------
  // Execute crossfade
  // --------------------------------------------------------------------------
  const executeCrossfade = useCallback((duration: number, nextTrack: Track) => {
    const nextElement = getNextElement();
    if (!nextElement) return;

    applyNormalizationGain(nextTrack, false);

    if (useDirectPlayback) {
      if (duration <= MOBILE_TRANSITION_OVERLAP) {
        nextElement.volume = currentMasterVolume;
        nextElement.play().catch(log.error);
        crossfadeContext = {
          isActive: true,
          startTime: performance.now(),
          duration,
          timeoutId: setTimeout(() => completeCrossfade(), duration * 1000),
        };
      } else {
        const startTime = performance.now();
        const durationMs = duration * 1000;

        nextElement.volume = 0;
        nextElement.play().catch(log.error);

        const animateCrossfade = () => {
          const elapsed = performance.now() - startTime;
          const progress = Math.min(elapsed / durationMs, 1);
          const currentVol = (1 - progress) * currentMasterVolume;
          const nextVol = progress * currentMasterVolume;

          const currentElement = getCurrentElement();

          if (currentElement) currentElement.volume = currentVol;
          nextElement.volume = nextVol;

          if (progress < 1) {
            crossfadeContext!.animationFrameId = requestAnimationFrame(animateCrossfade);
          } else {
            completeCrossfade();
          }
        };

        crossfadeContext = {
          isActive: true,
          startTime: performance.now(),
          duration,
          timeoutId: null,
          animationFrameId: requestAnimationFrame(animateCrossfade),
        };
      }
    } else {
      const graph = audioGraph.current;
      if (!graph.audioContext || !graph.masterGain) return;

      const currentGain = getCurrentGain();
      const nextGain = getNextGain();
      if (!currentGain || !nextGain) return;

      const ctx = graph.audioContext;
      const now = ctx.currentTime;

      currentGain.gain.cancelScheduledValues(now);
      nextGain.gain.cancelScheduledValues(now);

      if (duration === 0) {
        currentGain.gain.setValueAtTime(0, now);
        nextGain.gain.setValueAtTime(1, now);
        nextElement.play().catch(log.error);
      } else {
        currentGain.gain.setValueAtTime(1, now);
        currentGain.gain.linearRampToValueAtTime(0, now + duration);

        nextGain.gain.setValueAtTime(0, now);
        nextGain.gain.linearRampToValueAtTime(1, now + duration);

        nextElement.play().catch(log.error);
      }

      crossfadeContext = {
        isActive: true,
        startTime: now,
        duration,
        timeoutId: setTimeout(() => completeCrossfade(), duration * 1000),
      };
    }

    advanceToNextTrack(nextTrack);
  }, [audioGraph, useDirectPlayback, getNextElement, getCurrentElement, getCurrentGain, getNextGain, advanceToNextTrack, applyNormalizationGain, completeCrossfade]);

  // --------------------------------------------------------------------------
  // Update Media Session
  // --------------------------------------------------------------------------
  const updateMediaSession = useCallback(() => {
    if (!('mediaSession' in navigator) || !currentTrack) return;

    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: currentTrack.title || 'Unknown',
        artist: currentTrack.artist || 'Unknown',
        album: currentTrack.album || 'Unknown',
        artwork: currentTrack.id ? [{ src: tracksApi.getArtworkUrl(currentTrack.id), sizes: '512x512', type: 'image/jpeg' }] : [],
      });

      navigator.mediaSession.setActionHandler('play', () => setIsPlaying(true));
      navigator.mediaSession.setActionHandler('pause', () => setIsPlaying(false));
      navigator.mediaSession.setActionHandler('nexttrack', () => playNext());
      navigator.mediaSession.setActionHandler('previoustrack', () => usePlayerStore.getState().playPrevious());
      navigator.mediaSession.setActionHandler('seekto', (details) => {
        if (details.seekTime !== undefined) {
          seek(details.seekTime);
        }
      });
    } catch (e) {
      log.warn('Failed to update media session', e);
    }
  }, [currentTrack, setIsPlaying, playNext]);

  // --------------------------------------------------------------------------
  // Seek
  // --------------------------------------------------------------------------
  const seek = useCallback((time: number) => {
    const currentElement = getCurrentElement();
    if (!currentElement) return;

    if (crossfadeContext?.isActive) {
      const duration = currentElement.duration;
      // If seeking near the end during a crossfade, cancel it to avoid confusion
      const effectiveCrossfade = crossfadeEnabled
        ? (useDirectPlayback ? Math.max(crossfadeDuration, MOBILE_TRANSITION_OVERLAP) : crossfadeDuration)
        : (useDirectPlayback ? MOBILE_TRANSITION_OVERLAP : 0);

      if (duration - time > effectiveCrossfade + 1) cancelCrossfade();
    }

    if (!Number.isFinite(time)) return;

    try {
      currentElement.currentTime = time;
      setCurrentTime(time);
    } catch (e) {
      log.error('Seek failed', e);
    }
  }, [setCurrentTime, crossfadeEnabled, crossfadeDuration, cancelCrossfade, getCurrentElement, useDirectPlayback]);

  // --------------------------------------------------------------------------
  // Toggle play/pause
  // --------------------------------------------------------------------------
  const togglePlayPause = useCallback(() => {
    setIsPlaying(!isPlaying);
  }, [isPlaying, setIsPlaying]);

  // --------------------------------------------------------------------------
  // Effect: Update Media Session when track changes
  // --------------------------------------------------------------------------
  useEffect(() => {
    updateMediaSession();
  }, [updateMediaSession]);

  // --------------------------------------------------------------------------
  // Effect: Handle Play/Pause State
  // --------------------------------------------------------------------------
  useEffect(() => {
    if (!isInitialized) return;

    const currentElement = getCurrentElement();
    if (!currentElement) return;

    if (isPlaying) {
      const ctx = audioGraph.current.audioContext;
      if (ctx && ctx.state === 'suspended') {
        ctx.resume().catch(e => log.error('Failed to resume audio context', e));
      }

      const playPromise = currentElement.play();
      if (playPromise !== undefined) {
        playPromise.catch(e => {
          if (e.name === 'NotAllowedError') {
            log.warn('Auto-play blocked');
            setIsPlaying(false);
          } else if (e.name !== 'AbortError') {
            log.error('Play failed', e);
          }
        });
      }
    } else {
      currentElement.pause();
    }
  }, [isPlaying, isInitialized, getCurrentElement, audioGraph, setIsPlaying]);

  // --------------------------------------------------------------------------
  // Effect: Handle Volume Changes
  // --------------------------------------------------------------------------
  useEffect(() => {
    if (!isInitialized) return;

    currentMasterVolume = volume;

    if (useDirectPlayback) {
      if (!crossfadeContext?.isActive) {
        const currentElement = getCurrentElement();
        const nextElement = getNextElement();
        setElementVolume(currentElement, volume);
        setElementVolume(nextElement, 0);
      }
    } else {
      const graph = audioGraph.current;
      if (graph.masterGain) {
        graph.masterGain.gain.setTargetAtTime(volume, graph.audioContext?.currentTime || 0, 0.1);
      }
    }
  }, [volume, isInitialized, useDirectPlayback, getCurrentElement, getNextElement, audioGraph]);
  // --------------------------------------------------------------------------
  // Effect: Load track when currentTrack changes (Manual navigation)
  // --------------------------------------------------------------------------
  useEffect(() => {
    if (!isInitialized || !currentTrack) return;

    // If we are crossfading, the "next" track is already playing on the other element.
    if (crossfadeContext?.isActive) return;

    const currentElement = getCurrentElement();
    if (!currentElement) return;

    // Check if expected track is already loaded
    if (currentElement.getAttribute('data-track-id') === currentTrack.id) {
      return;
    }

    const loadTrack = async () => {
      try {
        const { url, isOffline } = await getTrackUrl(currentTrack.id);

        // Re-check state after async op
        if (usePlayerStore.getState().currentTrack?.id !== currentTrack.id) return;
        if (crossfadeContext?.isActive) return;

        // Cleanup old offline URL
        if (currentOfflineUrl) revokeOfflineTrackUrl(currentOfflineUrl);
        currentOfflineUrl = isOffline ? url : null;

        currentElement.src = url;
        currentElement.setAttribute('data-track-id', currentTrack.id);
        currentElement.load();

        if (isPlaying) {
          const p = currentElement.play();
          if (p) p.catch(e => {
            if (e.name !== 'AbortError') log.error('Play failed after load', e);
          });
        }
      } catch (e) {
        log.error('Failed to load track', e);
      }
    };

    loadTrack();

    // We only want to run this when the track ID changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentTrack?.id, isInitialized, getCurrentElement]);
  // --------------------------------------------------------------------------
  // Animation/Update Loop
  // --------------------------------------------------------------------------
  useEffect(() => {
    let animationFrameId: number;
    let lastTimeUpdate = 0;

    const loop = () => {
      animationFrameId = requestAnimationFrame(loop);

      const now = performance.now();
      if (now - lastTimeUpdate < 16) return;
      lastTimeUpdate = now;

      const currentElement = getCurrentElement();
      if (currentElement) {
        if (!currentElement.paused) {
          setCurrentTime(currentElement.currentTime);
        }

        if (Number.isFinite(currentElement.duration) && currentElement.duration > 0) {
          setDuration(currentElement.duration);
        }

        // Check for crossfade trigger
        if (!crossfadeContext?.isActive && !queueTransition && currentTrack) {
          const timeRemaining = currentElement.duration - currentElement.currentTime;

          // Calculate effective crossfade duration
          const effectiveCrossfade = crossfadeEnabled
            ? (useDirectPlayback ? Math.max(crossfadeDuration, MOBILE_TRANSITION_OVERLAP) : crossfadeDuration)
            : (useDirectPlayback ? MOBILE_TRANSITION_OVERLAP : 0);

          // Trigger crossfade when we reach the threshold
          if (timeRemaining <= effectiveCrossfade && timeRemaining > 0.1) {
            const nextTrack = usePlayerStore.getState().getNextTrack();
            if (nextTrack) {
              queueTransition = true;
              executeCrossfade(effectiveCrossfade, nextTrack);
              // Reset queueTransition flag after a moment
              setTimeout(() => { queueTransition = false; }, 1000);
            }
          }
        }
      }
    };

    if (isPlaying) {
      loop();
    }

    return () => {
      // Cancel the current frame, not the last one
      if (animationFrameId) cancelAnimationFrame(animationFrameId);
    };
  }, [isPlaying, getCurrentElement, setCurrentTime, setDuration]);

  return {
    preloadNextTrack,
    executeCrossfade,
    togglePlayPause,
    seek,
    audioGraph: audioGraph.current,
  };
}
