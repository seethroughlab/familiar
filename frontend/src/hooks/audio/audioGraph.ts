import { tracksApi } from '../../api/client';
import {
  getOfflineTrack,
  createOfflineTrackUrl,
  revokeOfflineTrackUrl,
} from '../../services/offlineService';
import { EffectsChain, initEffectsChain } from '../../services/audioEffects';
import { showError } from '../../stores/toastStore';
import { useDirectPlayback, useWebAudio, log } from './platform';

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
export interface CrossfadeContext {
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
let earlyPreloadedTrackId: string | null = null;
let queueTransition = false;
let errorCount = 0;
let lastErrorTrackId: string | null = null;

// Track if we've shown init error (avoid spam)
let hasShownInitError = false;

// ============================================================================
// Exported Getters for Visualizer / External Access
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
// Exported Functions for Platform Capabilities
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
// Element Accessors
// ============================================================================

export function getCurrentElement(): HTMLAudioElement | null {
  if (useWebAudio) {
    return currentElementIsA ? webAudioElementA : webAudioElementB;
  } else {
    return currentElementIsA ? directElementA : directElementB;
  }
}

export function getNextElement(): HTMLAudioElement | null {
  if (useWebAudio) {
    return currentElementIsA ? webAudioElementB : webAudioElementA;
  } else {
    return currentElementIsA ? directElementB : directElementA;
  }
}

export function getCurrentGain(): GainNode | null {
  if (!useWebAudio) return null;
  return currentElementIsA ? globalGainA : globalGainB;
}

export function getNextGain(): GainNode | null {
  if (!useWebAudio) return null;
  return currentElementIsA ? globalGainB : globalGainA;
}

// ============================================================================
// State Accessors / Mutators
// ============================================================================

export function getGlobalAudioContext(): AudioContext | null {
  return globalAudioContext;
}

export function getGlobalMasterGain(): GainNode | null {
  return globalMasterGain;
}

export function getCrossfadeContext(): CrossfadeContext | null {
  return crossfadeContext;
}

export function setCrossfadeContext(ctx: CrossfadeContext | null): void {
  crossfadeContext = ctx;
}

export function getCurrentElementIsA(): boolean {
  return currentElementIsA;
}

export function toggleCurrentElement(): void {
  currentElementIsA = !currentElementIsA;
}

export function getCurrentOfflineUrl(): string | null {
  return currentOfflineUrl;
}

export function setCurrentOfflineUrl(url: string | null): void {
  currentOfflineUrl = url;
}

export function getNextOfflineUrl(): string | null {
  return nextOfflineUrl;
}

export function setNextOfflineUrl(url: string | null): void {
  nextOfflineUrl = url;
}

export function getCurrentMasterVolume(): number {
  return currentMasterVolume;
}

export function setCurrentMasterVolume(vol: number): void {
  currentMasterVolume = vol;
}

export function getLoadedTrackId(): string | null {
  return loadedTrackId;
}

export function setLoadedTrackId(id: string | null): void {
  loadedTrackId = id;
}

export function getCurrentLoadId(): number {
  return currentLoadId;
}

export function incrementLoadId(): number {
  return ++currentLoadId;
}

export function getPreloadingTrackId(): string | null {
  return preloadingTrackId;
}

export function setPreloadingTrackId(id: string | null): void {
  preloadingTrackId = id;
}

export function getEarlyPreloadedTrackId(): string | null {
  return earlyPreloadedTrackId;
}

export function setEarlyPreloadedTrackId(id: string | null): void {
  earlyPreloadedTrackId = id;
}

export function getQueueTransition(): boolean {
  return queueTransition;
}

export function setQueueTransition(val: boolean): void {
  queueTransition = val;
}

export function getErrorCount(): number {
  return errorCount;
}

export function setErrorCount(count: number): void {
  errorCount = count;
}

export function incrementErrorCount(): void {
  errorCount++;
}

export function getLastErrorTrackId(): string | null {
  return lastErrorTrackId;
}

export function setLastErrorTrackId(id: string | null): void {
  lastErrorTrackId = id;
}

// Direct element accessors (for event listeners in the coordinator)
export function getDirectElementA(): HTMLAudioElement | null {
  return directElementA;
}

export function getDirectElementB(): HTMLAudioElement | null {
  return directElementB;
}

export function getWebAudioElementA(): HTMLAudioElement | null {
  return webAudioElementA;
}

export function getWebAudioElementB(): HTMLAudioElement | null {
  return webAudioElementB;
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

export function initializeAudioGraph(): boolean {
  try {
    if (useDirectPlayback) {
      // Mobile: create direct playback elements only (no Web Audio)
      if (!directElementA) {
        directElementA = createAudioElement();
      }
      if (!directElementB) {
        directElementB = createAudioElement();
      }
      log.info('Initialized in direct playback mode (mobile)');
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
      log.info('Initialized in Web Audio mode (desktop)');
    }

    return true;
  } catch (e) {
    log.error('Failed to initialize audio graph:', e);
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

export async function getTrackUrl(trackId: string): Promise<{ url: string; isOffline: boolean }> {
  const offlineBlob = await getOfflineTrack(trackId);
  if (offlineBlob) {
    return { url: createOfflineTrackUrl(offlineBlob), isOffline: true };
  }
  return { url: tracksApi.getStreamUrl(trackId), isOffline: false };
}

export function cleanupElement(element: HTMLAudioElement | null, offlineUrl: string | null): void {
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

export function setElementVolume(element: HTMLAudioElement | null, volume: number): void {
  if (element) {
    element.volume = Math.max(0, Math.min(1, volume));
  }
}

export function updateDirectPlaybackVolumes(): void {
  if (!useDirectPlayback) return;
  if (!crossfadeContext?.isActive) {
    const currentElement = getCurrentElement();
    const nextElement = getNextElement();
    setElementVolume(currentElement, currentMasterVolume);
    setElementVolume(nextElement, 0);
  }
}
