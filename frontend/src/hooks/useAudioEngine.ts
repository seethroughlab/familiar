import { useEffect, useRef, useCallback } from 'react';
import { usePlayerStore } from '../stores/playerStore';
import { useAudioSettingsStore } from '../stores/audioSettingsStore';
import { tracksApi } from '../api/client';
import type { Track } from '../types';
import {
  getOfflineTrack,
  createOfflineTrackUrl,
  revokeOfflineTrackUrl,
} from '../services/offlineService';
import { EffectsChain, initEffectsChain } from '../services/audioEffects';
import { showError, showInfo } from '../stores/toastStore';

// ============================================================================
// Platform Detection
// ============================================================================

const isMobilePlatform = /iPad|iPhone|iPod|Android/i.test(navigator.userAgent);

// Mobile uses direct playback (background-safe, no Web Audio)
// Desktop uses Web Audio (visualizer, effects)
const useDirectPlayback = isMobilePlatform;
const useWebAudio = !isMobilePlatform;

// Log version and platform detection on load
console.log('[AudioEngine] v5 - simplified mobile', {
  isMobilePlatform,
  useDirectPlayback,
  useWebAudio,
});

// Debug flag - set to true to enable verbose logging for track ending issues
const DEBUG_TRACK_ENDING = true;

// Track last logged time to avoid spamming (log every 10 seconds)
let lastDebugLogTime = 0;
let lastLoggedTrackId: string | null = null;

// ============================================================================
// Exported functions
// ============================================================================

export function areAudioEffectsAvailable(): boolean {
  // Effects only work in Web Audio mode on desktop
  return useWebAudio;
}

export function isVisualizerAvailable(): boolean {
  // Visualizer only works on desktop (requires Web Audio)
  return useWebAudio;
}

// Legacy function - kept for API compatibility but no longer does anything
export function setVisualizerVisible(_visible: boolean): void {
  // No-op: visualizer is disabled on mobile
}

export function getCurrentMode(): 'direct' | 'webaudio' {
  return useWebAudio ? 'webaudio' : 'direct';
}

// ============================================================================
// Global Audio Graph State
// ============================================================================

let globalAudioContext: AudioContext | null = null;
let globalAnalyser: AnalyserNode | null = null;
let globalMasterGain: GainNode | null = null;
let globalEffectsChain: EffectsChain | null = null;

// Web Audio elements (connected via createMediaElementSource)
let webAudioElementA: HTMLAudioElement | null = null;
let webAudioElementB: HTMLAudioElement | null = null;
let globalMediaSourceA: MediaElementAudioSourceNode | null = null;
let globalMediaSourceB: MediaElementAudioSourceNode | null = null;
let globalGainA: GainNode | null = null;
let globalGainB: GainNode | null = null;

// Direct playback elements (NOT connected to Web Audio - for background playback)
let directElementA: HTMLAudioElement | null = null;
let directElementB: HTMLAudioElement | null = null;

// Track which element pair is currently playing (A or B for crossfade)
let currentElementIsA = true;

// Crossfade state
interface CrossfadeContext {
  isActive: boolean;
  startTime: number;
  duration: number;
  timeoutId: ReturnType<typeof setTimeout> | null;
  animationFrameId?: number;
}
let crossfadeContext: CrossfadeContext | null = null;

// Offline URL tracking
let currentOfflineUrl: string | null = null;
let nextOfflineUrl: string | null = null;

// Current master volume
let currentMasterVolume = 1;

// Module-level tracking state (matches audio element pattern)
// These must be global so multiple hook instances share the same state
let loadedTrackId: string | null = null;
let currentLoadId = 0;
let preloadingTrackId: string | null = null;
let queueTransition = false;
let errorCount = 0;
let lastErrorTrackId: string | null = null;

// ============================================================================
// Exported functions for visualizer access
// ============================================================================

export function getAudioAnalyser(): AnalyserNode | null {
  return globalAnalyser;
}

export function getAudioContext(): AudioContext | null {
  return globalAudioContext;
}

export function getAudioEffectsChain(): EffectsChain | null {
  return useWebAudio ? globalEffectsChain : null;
}

// ============================================================================
// Element Accessors
// ============================================================================

function getCurrentElement(): HTMLAudioElement | null {
  if (useWebAudio) {
    return currentElementIsA ? webAudioElementA : webAudioElementB;
  } else {
    return currentElementIsA ? directElementA : directElementB;
  }
}

function getNextElement(): HTMLAudioElement | null {
  if (useWebAudio) {
    return currentElementIsA ? webAudioElementB : webAudioElementA;
  } else {
    return currentElementIsA ? directElementB : directElementA;
  }
}

function getCurrentGain(): GainNode | null {
  if (!useWebAudio) return null;
  return currentElementIsA ? globalGainA : globalGainB;
}

function getNextGain(): GainNode | null {
  if (!useWebAudio) return null;
  return currentElementIsA ? globalGainB : globalGainA;
}

// ============================================================================
// Audio Graph Initialization
// ============================================================================

function createAudioElement(): HTMLAudioElement {
  const el = new Audio();
  el.preload = 'auto';
  el.crossOrigin = 'anonymous';
  el.style.display = 'none';
  document.body.appendChild(el);
  return el;
}

// Track if we've shown init error (avoid spam)
let hasShownInitError = false;

function initializeAudioGraph(): boolean {
  try {
    if (useDirectPlayback) {
      // Mobile: create direct playback elements only (no Web Audio)
      if (!directElementA) {
        directElementA = createAudioElement();
      }
      if (!directElementB) {
        directElementB = createAudioElement();
      }
      console.log('[AudioEngine] Initialized in direct playback mode (mobile)');
    } else {
      // Desktop: create Web Audio graph with visualizer and effects support
      if (!globalAudioContext) {
        globalAudioContext = new AudioContext();
      }

      if (!globalAnalyser) {
        globalAnalyser = globalAudioContext.createAnalyser();
        globalAnalyser.fftSize = 256;
        globalAnalyser.smoothingTimeConstant = 0.8;
      }

      if (!webAudioElementA) {
        webAudioElementA = createAudioElement();
        globalMediaSourceA = globalAudioContext.createMediaElementSource(webAudioElementA);
      }
      if (!webAudioElementB) {
        webAudioElementB = createAudioElement();
        globalMediaSourceB = globalAudioContext.createMediaElementSource(webAudioElementB);
      }

      if (!globalGainA) {
        globalGainA = globalAudioContext.createGain();
        globalGainA.gain.value = 1;
      }
      if (!globalGainB) {
        globalGainB = globalAudioContext.createGain();
        globalGainB.gain.value = 0;
      }

      if (!globalMasterGain) {
        globalMasterGain = globalAudioContext.createGain();
      }

      if (!globalEffectsChain) {
        globalEffectsChain = initEffectsChain(globalAudioContext);
      }

      // Connect the Web Audio graph
      globalMediaSourceA!.connect(globalGainA);
      globalMediaSourceB!.connect(globalGainB);
      globalGainA.connect(globalMasterGain);
      globalGainB.connect(globalMasterGain);

      if (globalEffectsChain) {
        globalMasterGain.connect(globalEffectsChain.input);
        globalEffectsChain.output.connect(globalAnalyser);
      } else {
        globalMasterGain.connect(globalAnalyser);
      }
      globalAnalyser.connect(globalAudioContext.destination);
      console.log('[AudioEngine] Initialized in Web Audio mode (desktop)');
    }

    return true;
  } catch (e) {
    console.error('Failed to initialize audio graph:', e);
    // Only show error toast once per session
    if (!hasShownInitError) {
      hasShownInitError = true;
      showError('Audio initialization failed', {
        description: 'Try refreshing the page. Audio playback may not work correctly.',
      });
    }
    return false;
  }
}


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

function updateDirectPlaybackVolumes(): void {
  if (!useDirectPlayback) return;
  if (!crossfadeContext?.isActive) {
    const currentElement = getCurrentElement();
    const nextElement = getNextElement();
    setElementVolume(currentElement, currentMasterVolume);
    setElementVolume(nextElement, 0);
  }
}

// ============================================================================
// Main Hook
// ============================================================================

export function useAudioEngine() {
  // Keep animationFrameRef as local (used for cleanup per instance)
  const animationFrameRef = useRef<number | undefined>(undefined);

  const {
    currentTrack,
    isPlaying,
    volume,
    crossfadeState,
    nextTrackPreloaded,
    setCurrentTime,
    setDuration,
    setIsPlaying,
    playNext,
    setCrossfadeState,
    setNextTrackPreloaded,
    getNextTrack,
    advanceToNextTrack,
    setIsLoadingAudio,
  } = usePlayerStore();

  const { crossfadeDuration, crossfadeEnabled } = useAudioSettingsStore();

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
      console.error('Error preloading track:', e);
      preloadingTrackId = null;
      return false;
    }
  }, []);

  // --------------------------------------------------------------------------
  // Execute crossfade
  // --------------------------------------------------------------------------
  const executeCrossfade = useCallback((duration: number, nextTrack: Track) => {
    const currentElement = getCurrentElement();
    const nextElement = getNextElement();
    if (!nextElement) return;

    if (DEBUG_TRACK_ENDING) {
      console.log('[AudioEngine] executeCrossfade called', {
        crossfadeDuration: duration,
        nextTrackId: nextTrack.id,
        nextTrackTitle: nextTrack.title,
        currentElementTime: currentElement?.currentTime,
        currentElementDuration: currentElement?.duration,
        nextElementReadyState: nextElement?.readyState,
      });
    }

    if (useDirectPlayback) {
      // Direct mode (mobile): animate audioElement.volume
      const startTime = performance.now();
      const durationMs = duration * 1000;

      nextElement.volume = 0;
      nextElement.play().catch(console.error);

      const animateCrossfade = () => {
        const elapsed = performance.now() - startTime;
        const progress = Math.min(elapsed / durationMs, 1);
        const currentVol = (1 - progress) * currentMasterVolume;
        const nextVol = progress * currentMasterVolume;

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
    } else {
      // Web Audio mode: use gain nodes
      if (!globalAudioContext || !globalMasterGain) return;
      const currentGain = getCurrentGain();
      const nextGain = getNextGain();
      if (!currentGain || !nextGain) return;

      const ctx = globalAudioContext;
      const now = ctx.currentTime;

      currentGain.gain.cancelScheduledValues(now);
      nextGain.gain.cancelScheduledValues(now);

      if (duration === 0) {
        currentGain.gain.setValueAtTime(0, now);
        nextGain.gain.setValueAtTime(1, now);
        nextElement.play().catch(console.error);
      } else {
        currentGain.gain.setValueAtTime(1, now);
        currentGain.gain.linearRampToValueAtTime(0, now + duration);
        nextGain.gain.setValueAtTime(0, now);
        nextGain.gain.linearRampToValueAtTime(1, now + duration);
        nextElement.play().catch(console.error);
      }

      crossfadeContext = {
        isActive: true,
        startTime: now,
        duration,
        timeoutId: setTimeout(() => completeCrossfade(), duration * 1000),
      };
    }

    loadedTrackId = nextTrack.id;
    advanceToNextTrack(nextTrack);
  }, [advanceToNextTrack]);

  // --------------------------------------------------------------------------
  // Complete crossfade
  // --------------------------------------------------------------------------
  const completeCrossfade = useCallback(() => {
    if (DEBUG_TRACK_ENDING) {
      const { currentTrack: track } = usePlayerStore.getState();
      console.log('[AudioEngine] completeCrossfade called', {
        trackId: track?.id,
        trackTitle: track?.title,
      });
    }

    const oldElement = getCurrentElement();
    cleanupElement(oldElement, currentOfflineUrl);

    currentOfflineUrl = nextOfflineUrl;
    nextOfflineUrl = null;
    currentElementIsA = !currentElementIsA;

    if (crossfadeContext?.timeoutId) clearTimeout(crossfadeContext.timeoutId);
    if (crossfadeContext?.animationFrameId) cancelAnimationFrame(crossfadeContext.animationFrameId);
    crossfadeContext = null;

    preloadingTrackId = null;

    const currentId = usePlayerStore.getState().currentTrack?.id;
    if (currentId) loadedTrackId = currentId;

    if (useDirectPlayback) {
      const newCurrentElement = getCurrentElement();
      const newNextElement = getNextElement();
      setElementVolume(newCurrentElement, currentMasterVolume);
      setElementVolume(newNextElement, 0);
    }

    setCrossfadeState('idle');
    setNextTrackPreloaded(false);
  }, [setCrossfadeState, setNextTrackPreloaded]);

  // --------------------------------------------------------------------------
  // Cancel crossfade
  // --------------------------------------------------------------------------
  const cancelCrossfade = useCallback(() => {
    if (!crossfadeContext) return;

    const currentElement = getCurrentElement();
    const nextElement = getNextElement();

    if (useDirectPlayback) {
      if (crossfadeContext.animationFrameId) cancelAnimationFrame(crossfadeContext.animationFrameId);
      setElementVolume(currentElement, currentMasterVolume);
      setElementVolume(nextElement, 0);
    } else {
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

    cleanupElement(nextElement, nextOfflineUrl);
    nextOfflineUrl = null;

    if (crossfadeContext.timeoutId) clearTimeout(crossfadeContext.timeoutId);
    crossfadeContext = null;

    preloadingTrackId = null;
    setCrossfadeState('idle');
    setNextTrackPreloaded(false);
  }, [setCrossfadeState, setNextTrackPreloaded]);

  // --------------------------------------------------------------------------
  // Update Media Session
  // --------------------------------------------------------------------------
  const updateMediaSession = useCallback(() => {
    if (!('mediaSession' in navigator) || !currentTrack) return;

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
      if (details.seekTime !== undefined) seek(details.seekTime);
    });
  }, [currentTrack, setIsPlaying, playNext]);

  // --------------------------------------------------------------------------
  // Seek
  // --------------------------------------------------------------------------
  const seek = useCallback((time: number) => {
    const currentElement = getCurrentElement();
    if (!currentElement) return;

    if (crossfadeContext?.isActive) {
      const duration = currentElement.duration;
      const effectiveCrossfade = crossfadeEnabled ? crossfadeDuration : 0;
      if (duration - time > effectiveCrossfade + 1) cancelCrossfade();
    }

    currentElement.currentTime = time;
    setCurrentTime(time);
  }, [setCurrentTime, crossfadeEnabled, crossfadeDuration, cancelCrossfade]);

  // --------------------------------------------------------------------------
  // Toggle play/pause
  // --------------------------------------------------------------------------
  const togglePlayPause = useCallback(() => {
    setIsPlaying(!isPlaying);
  }, [isPlaying, setIsPlaying]);

  // --------------------------------------------------------------------------
  // Initialize
  // --------------------------------------------------------------------------
  useEffect(() => {
    initializeAudioGraph();

    // Setup ended handlers for elements
    const handleEnded = (isA: boolean) => () => {
      const element = isA
        ? (useDirectPlayback ? directElementA : webAudioElementA)
        : (useDirectPlayback ? directElementB : webAudioElementB);
      const { currentTrack: track } = usePlayerStore.getState();

      if (DEBUG_TRACK_ENDING) {
        console.warn('[AudioEngine] 🔴 ENDED EVENT FIRED', {
          elementIsA: isA,
          currentElementIsA,
          isCurrentElement: currentElementIsA === isA,
          queueTransition,
          crossfadeActive: crossfadeContext?.isActive,
          trackId: track?.id,
          trackTitle: track?.title,
          elementCurrentTime: element?.currentTime,
          elementDuration: element?.duration,
          elementPaused: element?.paused,
          elementEnded: element?.ended,
          elementReadyState: element?.readyState,
          elementNetworkState: element?.networkState,
          elementSrc: element?.src?.slice(-50), // Last 50 chars of URL
          timestamp: new Date().toISOString(),
        });
      }

      if (queueTransition) {
        if (DEBUG_TRACK_ENDING) console.log('[AudioEngine] Ignoring ended event - queueTransition active');
        return;
      }
      if (currentElementIsA === isA && !crossfadeContext?.isActive) {
        if (DEBUG_TRACK_ENDING) console.log('[AudioEngine] Calling playNext() from ended handler');
        playNext();
      } else {
        if (DEBUG_TRACK_ENDING) console.log('[AudioEngine] Ignoring ended event - not current element or crossfade active');
      }
    };

    const handleError = (e: Event) => {
      const target = e.target as HTMLAudioElement;
      if (!target.src || target.src === window.location.href) return;

      const currentElement = getCurrentElement();
      if (target !== currentElement) return;

      // Get the media error code for better diagnostics
      const mediaError = target.error;
      const errorCode = mediaError?.code;
      const isDecodeError = errorCode === MediaError.MEDIA_ERR_DECODE;
      const isUnsupported = errorCode === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED;

      console.error('Audio error:', e, 'code:', errorCode, 'message:', mediaError?.message);

      const { currentTrack: track, isPlaying: playing } = usePlayerStore.getState();
      const currentId = track?.id;
      const currentTrackTitle = track?.title;

      // Only show error toast if user was trying to play
      // (Don't show errors during background preloading on hydration)
      if (!playing) {
        return;
      }

      // For decode/format errors, skip immediately with a single toast
      // (no point retrying - the file is corrupted or unsupported)
      if (isDecodeError || isUnsupported) {
        showError('Skipped unplayable track', {
          description: `"${currentTrackTitle || 'Track'}" appears to be corrupted or unsupported.`,
        });
        setIsLoadingAudio(false);
        // Reset error tracking
        errorCount = 0;
        lastErrorTrackId = null;
        playNext();
        return;
      }

      // For other errors (network, etc.), retry a few times before skipping
      if (currentId === lastErrorTrackId) {
        errorCount++;
        if (errorCount >= 3) {
          errorCount = 0;
          lastErrorTrackId = null;
          showError('Playback failed', {
            description: `Unable to play "${currentTrackTitle || 'track'}". Skipping to next track.`,
          });
          setIsLoadingAudio(false);
          playNext();
          return;
        }
      } else {
        errorCount = 1;
        lastErrorTrackId = currentId ?? null;
      }
      showError('Playback error', {
        description: `Failed to play "${currentTrackTitle || 'track'}"`,
      });
      setIsPlaying(false);
      setIsLoadingAudio(false);
    };

    const endedA = handleEnded(true);
    const endedB = handleEnded(false);

    // Debug handlers for buffering issues
    const handleStalled = (label: string) => (e: Event) => {
      if (!DEBUG_TRACK_ENDING) return;
      const el = e.target as HTMLAudioElement;
      const { currentTrack: track } = usePlayerStore.getState();
      console.warn(`[AudioEngine] ⚠️ ${label} STALLED`, {
        trackTitle: track?.title,
        currentTime: el.currentTime,
        duration: el.duration,
        readyState: el.readyState,
        networkState: el.networkState,
      });
    };

    const handleWaiting = (label: string) => (e: Event) => {
      if (!DEBUG_TRACK_ENDING) return;
      const el = e.target as HTMLAudioElement;
      const { currentTrack: track } = usePlayerStore.getState();
      console.warn(`[AudioEngine] ⏳ ${label} WAITING (buffering)`, {
        trackTitle: track?.title,
        currentTime: el.currentTime,
        duration: el.duration,
        readyState: el.readyState,
      });
    };

    const handleSeeked = (label: string) => (e: Event) => {
      if (!DEBUG_TRACK_ENDING) return;
      const el = e.target as HTMLAudioElement;
      const { currentTrack: track } = usePlayerStore.getState();
      console.log(`[AudioEngine] ⏩ ${label} SEEKED`, {
        trackTitle: track?.title,
        currentTime: el.currentTime,
        duration: el.duration,
      });
    };

    const stalledA = handleStalled('A');
    const stalledB = handleStalled('B');
    const waitingA = handleWaiting('A');
    const waitingB = handleWaiting('B');
    const seekedA = handleSeeked('A');
    const seekedB = handleSeeked('B');

    // Add listeners only to the elements that exist for this platform
    if (useDirectPlayback) {
      directElementA?.addEventListener('ended', endedA);
      directElementB?.addEventListener('ended', endedB);
      directElementA?.addEventListener('error', handleError);
      directElementB?.addEventListener('error', handleError);
      directElementA?.addEventListener('stalled', stalledA);
      directElementB?.addEventListener('stalled', stalledB);
      directElementA?.addEventListener('waiting', waitingA);
      directElementB?.addEventListener('waiting', waitingB);
      directElementA?.addEventListener('seeked', seekedA);
      directElementB?.addEventListener('seeked', seekedB);
    } else {
      webAudioElementA?.addEventListener('ended', endedA);
      webAudioElementB?.addEventListener('ended', endedB);
      webAudioElementA?.addEventListener('error', handleError);
      webAudioElementB?.addEventListener('error', handleError);
      webAudioElementA?.addEventListener('stalled', stalledA);
      webAudioElementB?.addEventListener('stalled', stalledB);
      webAudioElementA?.addEventListener('waiting', waitingA);
      webAudioElementB?.addEventListener('waiting', waitingB);
      webAudioElementA?.addEventListener('seeked', seekedA);
      webAudioElementB?.addEventListener('seeked', seekedB);
    }

    return () => {
      if (useDirectPlayback) {
        directElementA?.removeEventListener('ended', endedA);
        directElementB?.removeEventListener('ended', endedB);
        directElementA?.removeEventListener('error', handleError);
        directElementB?.removeEventListener('error', handleError);
        directElementA?.removeEventListener('stalled', stalledA);
        directElementB?.removeEventListener('stalled', stalledB);
        directElementA?.removeEventListener('waiting', waitingA);
        directElementB?.removeEventListener('waiting', waitingB);
        directElementA?.removeEventListener('seeked', seekedA);
        directElementB?.removeEventListener('seeked', seekedB);
      } else {
        webAudioElementA?.removeEventListener('ended', endedA);
        webAudioElementB?.removeEventListener('ended', endedB);
        webAudioElementA?.removeEventListener('error', handleError);
        webAudioElementB?.removeEventListener('error', handleError);
        webAudioElementA?.removeEventListener('stalled', stalledA);
        webAudioElementB?.removeEventListener('stalled', stalledB);
        webAudioElementA?.removeEventListener('waiting', waitingA);
        webAudioElementB?.removeEventListener('waiting', waitingB);
        webAudioElementA?.removeEventListener('seeked', seekedA);
        webAudioElementB?.removeEventListener('seeked', seekedB);
      }
    };
  }, [playNext, setIsPlaying]);

  // --------------------------------------------------------------------------
  // Load track
  // --------------------------------------------------------------------------
  useEffect(() => {
    const currentElement = getCurrentElement();

    if (!currentTrack) {
      cleanupElement(directElementA, null);
      cleanupElement(directElementB, null);
      cleanupElement(webAudioElementA, null);
      cleanupElement(webAudioElementB, null);
      if (currentOfflineUrl) {
        revokeOfflineTrackUrl(currentOfflineUrl);
        currentOfflineUrl = null;
      }
      loadedTrackId = null;
      return;
    }

    if (loadedTrackId === currentTrack.id) return;
    if (crossfadeContext?.isActive) return;

    // Check if this track has external info (from playlist with suggested tracks)
    const { queue, playPreview } = usePlayerStore.getState();
    const queueItem = queue.find(q => q.track.id === currentTrack.id);
    const externalInfo = queueItem?.externalInfo;

    // Handle external tracks that don't have a matched local version
    if (externalInfo && !externalInfo.matchedTrackId) {
      if (externalInfo.previewUrl) {
        // Play 30-second preview
        loadedTrackId = currentTrack.id; // Mark as loaded to prevent re-triggering
        setIsLoadingAudio(false);
        playPreview({
          id: currentTrack.id,
          title: currentTrack.title || 'Unknown',
          artist: currentTrack.artist || 'Unknown',
          previewUrl: externalInfo.previewUrl,
        });
        return;
      } else {
        // No preview available - skip with clear message
        loadedTrackId = currentTrack.id; // Mark as loaded to prevent re-triggering
        setIsLoadingAudio(false);
        showInfo('Track not in library', {
          description: `"${currentTrack.title || 'Track'}" is a suggested track without a preview.`,
        });
        // Skip to next track after a short delay
        setTimeout(() => playNext(), 100);
        return;
      }
    }

    queueTransition = true;
    setIsLoadingAudio(true); // Show loading spinner on play button
    const thisLoadId = ++currentLoadId;
    const trackIdToLoad = currentTrack.id;

    const loadTrack = async () => {
      if (currentOfflineUrl) {
        revokeOfflineTrackUrl(currentOfflineUrl);
        currentOfflineUrl = null;
      }

      const { url, isOffline } = await getTrackUrl(trackIdToLoad);

      if (currentLoadId !== thisLoadId) {
        if (isOffline) revokeOfflineTrackUrl(url);
        return;
      }

      if (isOffline) currentOfflineUrl = url;

      if (currentElement) {
        currentElement.src = url;
        currentElement.load();

        const transitionTimeout = setTimeout(() => {
          if (currentLoadId === thisLoadId && queueTransition) {
            queueTransition = false;
          }
        }, 10000);

        const playWhenReady = () => {
          if (currentLoadId !== thisLoadId) return;
          clearTimeout(transitionTimeout);
          queueTransition = false;
          setIsLoadingAudio(false); // Audio is ready, hide spinner

          // Restore position if we have one (from hydration)
          const storedTime = usePlayerStore.getState().currentTime;
          if (storedTime > 0 && currentElement.currentTime === 0) {
            currentElement.currentTime = storedTime;
          }

          const shouldPlay = usePlayerStore.getState().isPlaying;
          if (shouldPlay) {
            currentElement.play().catch((err) => {
              if (err.name !== 'AbortError') console.error('Play failed:', err);
            });
          }
          currentElement.removeEventListener('canplay', playWhenReady);
        };

        const handleMetadata = () => {
          if (currentLoadId !== thisLoadId) return;
          if (DEBUG_TRACK_ENDING) {
            const { currentTrack: track } = usePlayerStore.getState();
            console.log('[AudioEngine] 📀 Track metadata loaded', {
              trackId: trackIdToLoad,
              trackTitle: track?.title,
              duration: currentElement.duration,
              readyState: currentElement.readyState,
            });
          }
          setDuration(currentElement.duration);
          loadedTrackId = trackIdToLoad;
          currentElement.removeEventListener('loadedmetadata', handleMetadata);
        };

        const handleLoadError = () => {
          if (currentLoadId !== thisLoadId) return;
          clearTimeout(transitionTimeout);
          queueTransition = false;
          setIsLoadingAudio(false); // Clear loading state on error
          currentElement.removeEventListener('error', handleLoadError);
        };

        currentElement.addEventListener('canplay', playWhenReady);
        currentElement.addEventListener('loadedmetadata', handleMetadata);
        currentElement.addEventListener('error', handleLoadError);

        // iOS PWA load timeout detection - detect hung loads that never fire events
        const loadTimeout = setTimeout(() => {
          if (currentLoadId === thisLoadId && currentElement.readyState < HTMLMediaElement.HAVE_FUTURE_DATA) {
            console.error('[Audio] Load timeout - iOS PWA may have suspended network');
            window.dispatchEvent(
              new CustomEvent('audio-load-timeout', {
                detail: { trackId: trackIdToLoad },
              })
            );
            // Don't auto-stop playback, but log for debugging
          }
        }, 30000);

        currentElement.addEventListener(
          'canplay',
          () => clearTimeout(loadTimeout),
          { once: true }
        );
        currentElement.addEventListener(
          'error',
          () => clearTimeout(loadTimeout),
          { once: true }
        );
      }
    };

    loadTrack();
    updateMediaSession();
  }, [currentTrack?.id, setDuration, updateMediaSession, setIsLoadingAudio, playNext]);

  // --------------------------------------------------------------------------
  // Play/pause
  // --------------------------------------------------------------------------
  useEffect(() => {
    if (!currentTrack) return;

    const currentElement = getCurrentElement();
    if (!currentElement) return;

    if (isPlaying) {
      if (globalAudioContext?.state === 'suspended') {
        globalAudioContext.resume();
      }

      const hasValidSource = currentElement.src && currentElement.src !== window.location.href && !currentElement.src.endsWith('/');
      const isReady = currentElement.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA;

      if (hasValidSource && isReady) {
        currentElement.play().catch((err) => {
          if (err.name !== 'AbortError') {
            console.error('Play failed:', err);
            if (err.name === 'NotAllowedError') {
              setIsPlaying(false);
              // Notify user about autoplay policy block
              showError('Playback blocked', {
                description: 'Click the play button to start playback. Your browser requires user interaction.',
              });
            }
          }
        });
      }

      if (crossfadeContext?.isActive) {
        getNextElement()?.play().catch(console.error);
      }

      if ('mediaSession' in navigator) navigator.mediaSession.playbackState = 'playing';
    } else {
      currentElement.pause();
      if (crossfadeContext?.isActive) getNextElement()?.pause();
      if ('mediaSession' in navigator) navigator.mediaSession.playbackState = 'paused';
    }
  }, [isPlaying, currentTrack, setIsPlaying]);

  // --------------------------------------------------------------------------
  // Volume
  // --------------------------------------------------------------------------
  useEffect(() => {
    currentMasterVolume = volume;

    if (useDirectPlayback) {
      updateDirectPlaybackVolumes();
    } else {
      if (globalMasterGain) globalMasterGain.gain.value = volume;
    }
  }, [volume]);

  // --------------------------------------------------------------------------
  // Time update loop
  // --------------------------------------------------------------------------
  useEffect(() => {
    const updateTime = () => {
      const currentElement = getCurrentElement();
      if (!currentElement || !isPlaying) return;

      const currentTime = currentElement.currentTime;
      const duration = currentElement.duration;

      setCurrentTime(currentTime);

      if ('mediaSession' in navigator && 'setPositionState' in navigator.mediaSession) {
        try {
          navigator.mediaSession.setPositionState({ duration: duration || 0, playbackRate: 1, position: currentTime });
        } catch { /* ignore */ }
      }

      const timeRemaining = duration - currentTime;
      const nextTrack = getNextTrack();
      const hasNextTrack = nextTrack !== null;
      const effectiveCrossfade = crossfadeEnabled ? crossfadeDuration : 0;
      const preloadThreshold = effectiveCrossfade + 3;

      // Periodic debug logging (every 10 seconds or on track change)
      if (DEBUG_TRACK_ENDING) {
        const now = Date.now();
        const trackId = usePlayerStore.getState().currentTrack?.id;
        const trackChanged = trackId !== lastLoggedTrackId;
        if (trackChanged || now - lastDebugLogTime >= 10000) {
          lastDebugLogTime = now;
          lastLoggedTrackId = trackId ?? null;
          console.log('[AudioEngine] 📊 Playback status', {
            trackId,
            currentTime: currentTime.toFixed(2),
            duration: duration.toFixed(2),
            timeRemaining: timeRemaining.toFixed(2),
            crossfadeState,
            nextTrackPreloaded,
            effectiveCrossfade,
            elementPaused: currentElement.paused,
            elementReadyState: currentElement.readyState,
            elementNetworkState: currentElement.networkState,
            buffered: currentElement.buffered.length > 0
              ? `${currentElement.buffered.start(0).toFixed(1)}-${currentElement.buffered.end(currentElement.buffered.length - 1).toFixed(1)}`
              : 'none',
          });
        }
      }

      if (hasNextTrack && crossfadeState === 'idle' && timeRemaining <= preloadThreshold && timeRemaining > effectiveCrossfade) {
        setCrossfadeState('preloading');
        preloadNextTrack(nextTrack.id).then((success) => {
          if (success) setNextTrackPreloaded(true);
          else setCrossfadeState('idle');
        });
      }

      if (hasNextTrack && nextTrackPreloaded && crossfadeState === 'preloading' && timeRemaining <= effectiveCrossfade && timeRemaining > 0.1) {
        if (DEBUG_TRACK_ENDING) {
          console.log('[AudioEngine] 🔄 Starting crossfade', {
            currentTime,
            duration,
            timeRemaining,
            effectiveCrossfade,
            nextTrackId: nextTrack.id,
            nextTrackTitle: nextTrack.title,
          });
        }
        setCrossfadeState('crossfading');
        executeCrossfade(effectiveCrossfade, nextTrack);
      }

      animationFrameRef.current = requestAnimationFrame(updateTime);
    };

    if (isPlaying) animationFrameRef.current = requestAnimationFrame(updateTime);

    return () => {
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
    };
  }, [isPlaying, setCurrentTime, crossfadeState, nextTrackPreloaded, crossfadeEnabled, crossfadeDuration, getNextTrack, setCrossfadeState, setNextTrackPreloaded, preloadNextTrack, executeCrossfade]);

  // --------------------------------------------------------------------------
  // Preview playback (for external tracks with preview URLs)
  // --------------------------------------------------------------------------
  const previewElementRef = useRef<HTMLAudioElement | null>(null);
  const { isPreviewMode, previewTrack, stopPreview } = usePlayerStore();

  useEffect(() => {
    // Create preview element if needed
    if (!previewElementRef.current) {
      const el = new Audio();
      el.preload = 'auto';
      el.style.display = 'none';
      document.body.appendChild(el);
      previewElementRef.current = el;
    }

    const previewEl = previewElementRef.current;

    if (isPreviewMode && previewTrack?.previewUrl) {
      // Stop main playback
      const currentElement = getCurrentElement();
      if (currentElement) {
        currentElement.pause();
      }

      // Start preview playback
      previewEl.src = previewTrack.previewUrl;
      previewEl.volume = currentMasterVolume;
      previewEl.load();

      const handleCanPlay = () => {
        previewEl.play().catch(console.error);
        setDuration(previewEl.duration || 30); // Previews are typically 30 seconds
        previewEl.removeEventListener('canplay', handleCanPlay);
      };

      const handleEnded = () => {
        // Preview ended - advance to next track
        stopPreview();
        playNext();
      };

      const handleTimeUpdate = () => {
        setCurrentTime(previewEl.currentTime);
      };

      previewEl.addEventListener('canplay', handleCanPlay);
      previewEl.addEventListener('ended', handleEnded);
      previewEl.addEventListener('timeupdate', handleTimeUpdate);

      return () => {
        previewEl.removeEventListener('canplay', handleCanPlay);
        previewEl.removeEventListener('ended', handleEnded);
        previewEl.removeEventListener('timeupdate', handleTimeUpdate);
      };
    } else {
      // Stop preview if it was playing
      previewEl.pause();
      previewEl.src = '';
    }
  }, [isPreviewMode, previewTrack, stopPreview, playNext, setDuration, setCurrentTime]);

  // Handle play/pause for preview mode
  useEffect(() => {
    const previewEl = previewElementRef.current;
    if (!previewEl || !isPreviewMode) return;

    if (isPlaying) {
      previewEl.play().catch(console.error);
    } else {
      previewEl.pause();
    }
  }, [isPlaying, isPreviewMode]);

  // Handle volume changes for preview mode
  useEffect(() => {
    const previewEl = previewElementRef.current;
    if (previewEl && isPreviewMode) {
      previewEl.volume = currentMasterVolume;
    }
  }, [volume, isPreviewMode]);

  // --------------------------------------------------------------------------
  // Return
  // --------------------------------------------------------------------------
  const getContext = useCallback(() => globalAudioContext, []);
  const getOutputNode = useCallback(() => globalAnalyser, []);

  return { seek, togglePlayPause, getContext, getOutputNode, cancelCrossfade };
}
