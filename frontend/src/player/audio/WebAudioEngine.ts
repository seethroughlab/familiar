import type { AudioEngine, AudioEngineCapabilities, EngineEvent } from './types';
import { tracksApi } from '../../api';
import {
  getOfflineTrack,
  createOfflineTrackUrl,
  revokeOfflineTrackUrl,
} from '../../services/offlineService';
import { EffectsChain, initEffectsChain } from '../../services/audioEffects';
import { showError } from '../../stores/toastStore';
import { isCapacitorNative, log } from './platform';
import {
  shouldHandleEnded,
  getErrorAction,
} from './eventHandlers';

// ============================================================================
// WebAudioEngine — Desktop browser implementation
// ============================================================================

type EventHandler = (event: EngineEvent) => void;

export class WebAudioEngine implements AudioEngine {
  readonly capabilities: AudioEngineCapabilities = {
    crossfade: true,
    visualizer: true,
    effects: 'web',
  };

  // Audio graph
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private masterGain: GainNode | null = null;
  private effectsChain: EffectsChain | null = null;

  // Elements A/B for crossfade
  private elementA: HTMLAudioElement | null = null;
  private elementB: HTMLAudioElement | null = null;
  private mediaSourceA: MediaElementAudioSourceNode | null = null;
  private mediaSourceB: MediaElementAudioSourceNode | null = null;
  private gainA: GainNode | null = null;
  private gainB: GainNode | null = null;
  private normGainA: GainNode | null = null;
  private normGainB: GainNode | null = null;

  // Which element is current (A or B)
  private currentIsA = true;

  // Crossfade state
  private crossfadeActive = false;
  private crossfadeTimeoutId: ReturnType<typeof setTimeout> | null = null;

  // URL tracking
  private currentOfflineUrl: string | null = null;
  private nextOfflineUrl: string | null = null;
  private currentBlobUrl: string | null = null;
  private nextBlobUrl: string | null = null;

  // Playback state
  private loadedTrackId: string | null = null;
  private preloadingTrackId: string | null = null;
  private hasShownInitError = false;

  // Event subscribers
  private handlers: Set<EventHandler> = new Set();

  // Visibility recovery handler ref
  private visibilityHandler: (() => void) | null = null;

  // AudioContext statechange handler
  private contextStateHandler: (() => void) | null = null;

  // DOM event listener refs for cleanup
  private domListenerCleanups: (() => void)[] = [];

  // ========================================================================
  // Lifecycle
  // ========================================================================

  initialize(): boolean {
    try {
      if (!this.audioContext) {
        this.audioContext = new AudioContext();
      }

      if (!this.analyser) {
        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = 256;
        this.analyser.smoothingTimeConstant = 0.8;
      }

      if (!this.elementA) {
        this.elementA = this.createAudioElement();
        this.mediaSourceA = this.audioContext.createMediaElementSource(this.elementA);
      }
      if (!this.elementB) {
        this.elementB = this.createAudioElement();
        this.mediaSourceB = this.audioContext.createMediaElementSource(this.elementB);
      }

      if (!this.normGainA) {
        this.normGainA = this.audioContext.createGain();
        this.normGainA.gain.value = 1;
      }
      if (!this.normGainB) {
        this.normGainB = this.audioContext.createGain();
        this.normGainB.gain.value = 1;
      }

      if (!this.gainA) {
        this.gainA = this.audioContext.createGain();
        this.gainA.gain.value = 1;
      }
      if (!this.gainB) {
        this.gainB = this.audioContext.createGain();
        this.gainB.gain.value = 0;
      }

      if (!this.masterGain) {
        this.masterGain = this.audioContext.createGain();
      }

      if (!this.effectsChain) {
        this.effectsChain = initEffectsChain(this.audioContext);
      }

      // Connect: Source → NormGain → CrossfadeGain → MasterGain → Effects → Analyser → Destination
      this.mediaSourceA!.connect(this.normGainA);
      this.mediaSourceB!.connect(this.normGainB);
      this.normGainA.connect(this.gainA);
      this.normGainB.connect(this.gainB);
      this.gainA.connect(this.masterGain);
      this.gainB.connect(this.masterGain);

      if (this.effectsChain) {
        this.masterGain.connect(this.effectsChain.input);
        this.effectsChain.output.connect(this.analyser);
      } else {
        this.masterGain.connect(this.analyser);
      }
      this.analyser.connect(this.audioContext.destination);

      // Set up DOM event listeners on both elements
      this.setupDomEventListeners();

      // Set up visibility recovery
      this.setupVisibilityRecovery();

      // Set up AudioContext statechange auto-resume
      this.setupContextStateRecovery();

      log.info('WebAudioEngine initialized');
      return true;
    } catch (e) {
      log.error('Failed to initialize WebAudioEngine:', e);
      if (!this.hasShownInitError) {
        this.hasShownInitError = true;
        showError('Audio initialization failed', {
          description: 'Try refreshing the page. Audio playback may not work correctly.',
        });
      }
      return false;
    }
  }

  dispose(): void {
    // Clean up DOM event listeners
    this.domListenerCleanups.forEach(cleanup => cleanup());
    this.domListenerCleanups = [];

    if (this.visibilityHandler) {
      document.removeEventListener('visibilitychange', this.visibilityHandler);
      this.visibilityHandler = null;
    }

    if (this.contextStateHandler && this.audioContext) {
      this.audioContext.removeEventListener('statechange', this.contextStateHandler);
      this.contextStateHandler = null;
    }

    this.cleanupElement(this.elementA, this.currentOfflineUrl);
    this.cleanupElement(this.elementB, this.nextOfflineUrl);
    this.revokeBlobUrl(this.currentBlobUrl);
    this.revokeBlobUrl(this.nextBlobUrl);

    this.handlers.clear();
  }

  // ========================================================================
  // Playback
  // ========================================================================

  async load(trackId: string, url: string, options?: { isOffline?: boolean; isExternal?: boolean }): Promise<void> {
    const el = this.getCurrentElement();
    if (!el) return;

    // Already loaded
    if (el.getAttribute('data-track-id') === trackId) return;

    // Clean up previous offline/blob URLs
    if (this.currentOfflineUrl) {
      revokeOfflineTrackUrl(this.currentOfflineUrl);
      this.currentOfflineUrl = null;
    }
    this.revokeBlobUrl(this.currentBlobUrl);
    this.currentBlobUrl = null;

    const isOffline = options?.isOffline ?? false;
    const isExternal = options?.isExternal ?? false;

    if (isOffline) this.currentOfflineUrl = url;

    // On Capacitor web view, fetch audio as blob to bypass CORS
    const resolvedUrl = await this.resolveAudioUrl(url, isOffline);
    if (!isOffline && isCapacitorNative) {
      this.currentBlobUrl = resolvedUrl;
    }

    // External preview URLs don't send CORS headers
    if (isExternal) {
      el.removeAttribute('crossorigin');
    } else if (!el.crossOrigin && !isCapacitorNative) {
      el.crossOrigin = 'anonymous';
    }

    el.src = resolvedUrl;
    el.setAttribute('data-track-id', trackId);
    el.load();
    this.loadedTrackId = trackId;
  }

  async play(): Promise<void> {
    const el = this.getCurrentElement();
    if (!el) return;

    // Resume AudioContext if suspended
    if (this.audioContext?.state === 'suspended') {
      await this.audioContext.resume().catch(e => log.error('Failed to resume audio context', e));
    }

    const p = el.play();
    if (p) {
      await p.catch(e => {
        if (e.name === 'NotAllowedError') {
          log.warn('Auto-play blocked');
          throw e;
        } else if (e.name !== 'AbortError') {
          log.error('Play failed', e);
          throw e;
        }
      });
    }
  }

  pause(): void {
    const el = this.getCurrentElement();
    if (el) el.pause();
  }

  seek(time: number): void {
    if (!Number.isFinite(time)) return;
    const el = this.getCurrentElement();
    if (!el) return;
    try {
      el.currentTime = time;
    } catch (e) {
      log.error('Seek failed', e);
    }
  }

  stop(): void {
    const el = this.getCurrentElement();
    if (el) {
      el.pause();
      el.currentTime = 0;
    }
    this.loadedTrackId = null;
  }

  // ========================================================================
  // Volume & Normalization
  // ========================================================================

  setVolume(volume: number): void {
    if (this.masterGain && this.audioContext) {
      this.masterGain.gain.setTargetAtTime(volume, this.audioContext.currentTime, 0.1);
    }
  }

  setNormalizationGain(gain: number): void {
    const normGain = this.currentIsA ? this.normGainA : this.normGainB;
    if (normGain) normGain.gain.value = gain;
  }

  // ========================================================================
  // State
  // ========================================================================

  getCurrentTime(): number {
    const el = this.getCurrentElement();
    return el?.currentTime ?? 0;
  }

  getDuration(): number {
    const el = this.getCurrentElement();
    const d = el?.duration ?? 0;
    return Number.isFinite(d) ? d : 0;
  }

  getLoadedTrackId(): string | null {
    return this.loadedTrackId;
  }

  // ========================================================================
  // Events
  // ========================================================================

  on(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => { this.handlers.delete(handler); };
  }

  private emit(event: EngineEvent): void {
    this.handlers.forEach(h => h(event));
  }

  // ========================================================================
  // Media Session
  // ========================================================================

  updateNowPlaying(metadata: {
    title: string;
    artist: string;
    album: string;
    artworkUrl?: string;
  }): void {
    if (!('mediaSession' in navigator)) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: metadata.title,
        artist: metadata.artist,
        album: metadata.album,
        artwork: metadata.artworkUrl
          ? [{ src: metadata.artworkUrl, sizes: '512x512', type: 'image/jpeg' }]
          : [],
      });

      navigator.mediaSession.setActionHandler('play', () => this.emit({ type: 'remotePlay' }));
      navigator.mediaSession.setActionHandler('pause', () => this.emit({ type: 'remotePause' }));
      navigator.mediaSession.setActionHandler('nexttrack', () => this.emit({ type: 'remoteNext' }));
      navigator.mediaSession.setActionHandler('previoustrack', () => this.emit({ type: 'remotePrevious' }));
      navigator.mediaSession.setActionHandler('seekto', (details) => {
        if (details.seekTime !== undefined && Number.isFinite(details.seekTime)) {
          this.seek(details.seekTime);
          this.emit({ type: 'remoteSeek', time: details.seekTime });
        }
      });
    } catch (e) {
      log.warn('Failed to update media session', e);
    }
  }

  // ========================================================================
  // Crossfade
  // ========================================================================

  async preloadNext(trackId: string, url: string, opts?: { isOffline?: boolean; isExternal?: boolean }): Promise<boolean> {
    if (this.preloadingTrackId === trackId) return false;

    this.preloadingTrackId = trackId;
    const nextEl = this.getNextElement();
    if (!nextEl) return false;

    try {
      // Clean up previous next offline/blob URLs
      if (this.nextOfflineUrl) {
        revokeOfflineTrackUrl(this.nextOfflineUrl);
        this.nextOfflineUrl = null;
      }
      this.revokeBlobUrl(this.nextBlobUrl);
      this.nextBlobUrl = null;

      const isOffline = opts?.isOffline ?? false;
      if (isOffline) this.nextOfflineUrl = url;

      const resolvedUrl = await this.resolveAudioUrl(url, isOffline);
      if (!isOffline && isCapacitorNative) {
        this.nextBlobUrl = resolvedUrl;
      }

      nextEl.src = resolvedUrl;
      nextEl.setAttribute('data-track-id', trackId);
      nextEl.load();

      return new Promise((resolve) => {
        const cleanup = () => {
          clearTimeout(timeout);
          nextEl.removeEventListener('canplay', onCanPlay);
          nextEl.removeEventListener('error', onError);
        };

        const timeout = setTimeout(() => {
          cleanup();
          log.warn('Preload timeout (10s)', { trackId, readyState: nextEl.readyState, networkState: nextEl.networkState });
          this.preloadingTrackId = null;
          resolve(false);
        }, 10000);

        const onCanPlay = () => {
          cleanup();
          this.preloadingTrackId = null;
          resolve(true);
        };
        const onError = () => {
          cleanup();
          log.warn('Preload error', { trackId, errorCode: nextEl.error?.code, errorMessage: nextEl.error?.message });
          this.preloadingTrackId = null;
          resolve(false);
        };
        nextEl.addEventListener('canplay', onCanPlay);
        nextEl.addEventListener('error', onError);
      });
    } catch (e) {
      log.error('Error preloading track:', e);
      this.preloadingTrackId = null;
      return false;
    }
  }

  setNextNormalizationGain(gain: number): void {
    const normGain = this.currentIsA ? this.normGainB : this.normGainA;
    if (normGain) normGain.gain.value = gain;
  }

  executeCrossfade(duration: number, onComplete: () => void): void {
    const currentEl = this.getCurrentElement();
    const nextEl = this.getNextElement();
    if (!nextEl || !this.audioContext) return;

    const currentGain = this.getCurrentGain();
    const nextGain = this.getNextGain();
    if (!currentGain || !nextGain) return;

    log.debug('executeCrossfade', {
      duration,
      nextTrackId: nextEl.getAttribute('data-track-id'),
      currentTime: currentEl?.currentTime,
      currentDuration: currentEl?.duration,
      nextReadyState: nextEl.readyState,
    });

    const now = this.audioContext.currentTime;

    currentGain.gain.cancelScheduledValues(now);
    nextGain.gain.cancelScheduledValues(now);

    if (duration === 0) {
      currentGain.gain.setValueAtTime(0, now);
      nextGain.gain.setValueAtTime(1, now);
    } else {
      currentGain.gain.setValueAtTime(1, now);
      currentGain.gain.linearRampToValueAtTime(0, now + duration);
      nextGain.gain.setValueAtTime(0, now);
      nextGain.gain.linearRampToValueAtTime(1, now + duration);
    }

    nextEl.play().catch(err => log.error('Play failed:', err));

    this.crossfadeActive = true;
    this.crossfadeTimeoutId = setTimeout(() => {
      this.completeCrossfade(onComplete);
    }, duration * 1000);

    // Update loaded track to next
    const nextTrackId = nextEl.getAttribute('data-track-id');
    if (nextTrackId) this.loadedTrackId = nextTrackId;
  }

  cancelCrossfade(): void {
    if (!this.crossfadeActive) return;

    log.debug('cancelCrossfade');

    const currentGain = this.getCurrentGain();
    const nextGain = this.getNextGain();

    if (currentGain && nextGain && this.audioContext) {
      const now = this.audioContext.currentTime;
      currentGain.gain.cancelScheduledValues(now);
      nextGain.gain.cancelScheduledValues(now);
      currentGain.gain.setValueAtTime(1, now);
      nextGain.gain.setValueAtTime(0, now);
    }

    this.cleanupElement(this.getNextElement(), this.nextOfflineUrl);
    this.nextOfflineUrl = null;
    this.revokeBlobUrl(this.nextBlobUrl);
    this.nextBlobUrl = null;

    if (this.crossfadeTimeoutId) clearTimeout(this.crossfadeTimeoutId);
    this.crossfadeActive = false;
    this.crossfadeTimeoutId = null;
    this.preloadingTrackId = null;
  }

  isCrossfading(): boolean {
    return this.crossfadeActive;
  }

  // ========================================================================
  // Visualizer
  // ========================================================================

  getAnalyser(): AnalyserNode | null {
    return this.analyser;
  }

  getAudioContext(): AudioContext | null {
    return this.audioContext;
  }

  getMasterGainNode(): GainNode | null {
    return this.masterGain;
  }

  // ========================================================================
  // Public helpers (used by the hook for time-based crossfade triggering)
  // ========================================================================

  /** Get the preloading track ID (to avoid duplicate preloads) */
  getPreloadingTrackId(): string | null {
    return this.preloadingTrackId;
  }

  /** Check if the next element is ready for crossfade */
  isNextReady(): boolean {
    const nextEl = this.getNextElement();
    return !!nextEl && nextEl.readyState > 0;
  }

  /** Resolve a track URL, getting offline track if available */
  async resolveTrackUrl(trackId: string): Promise<{ url: string; isOffline: boolean }> {
    const offlineBlob = await getOfflineTrack(trackId);
    if (offlineBlob) {
      return { url: createOfflineTrackUrl(offlineBlob), isOffline: true };
    }
    return { url: tracksApi.getStreamUrl(trackId), isOffline: false };
  }

  // ========================================================================
  // Private helpers
  // ========================================================================

  private getCurrentElement(): HTMLAudioElement | null {
    return this.currentIsA ? this.elementA : this.elementB;
  }

  private getNextElement(): HTMLAudioElement | null {
    return this.currentIsA ? this.elementB : this.elementA;
  }

  private getCurrentGain(): GainNode | null {
    return this.currentIsA ? this.gainA : this.gainB;
  }

  private getNextGain(): GainNode | null {
    return this.currentIsA ? this.gainB : this.gainA;
  }

  private createAudioElement(): HTMLAudioElement {
    const el = new Audio();
    el.preload = 'auto';
    if (!isCapacitorNative) {
      el.crossOrigin = 'anonymous';
    }
    el.style.display = 'none';
    document.body.appendChild(el);
    return el;
  }

  private async resolveAudioUrl(url: string, isOffline: boolean): Promise<string> {
    if (isOffline || !isCapacitorNative) return url;
    const response = await fetch(url);
    const blob = await response.blob();
    return URL.createObjectURL(blob);
  }

  private cleanupElement(element: HTMLAudioElement | null, offlineUrl: string | null): void {
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

  private revokeBlobUrl(url: string | null): void {
    if (url) URL.revokeObjectURL(url);
  }

  private completeCrossfade(onComplete: () => void): void {
    if (!this.crossfadeActive) return;

    const oldElement = this.getCurrentElement();
    this.cleanupElement(oldElement, this.currentOfflineUrl);
    this.revokeBlobUrl(this.currentBlobUrl);

    // Promote next to current
    this.currentOfflineUrl = this.nextOfflineUrl;
    this.nextOfflineUrl = null;
    this.currentBlobUrl = this.nextBlobUrl;
    this.nextBlobUrl = null;
    this.currentIsA = !this.currentIsA;

    this.crossfadeActive = false;
    this.crossfadeTimeoutId = null;
    this.preloadingTrackId = null;

    onComplete();
  }

  // ========================================================================
  // DOM Event Listeners
  // ========================================================================

  private setupDomEventListeners(): void {
    const elements = [this.elementA, this.elementB].filter((e): e is HTMLAudioElement => e !== null);

    const handleEnded = (e: Event) => {
      const target = e.target as HTMLAudioElement;
      const willHandle = shouldHandleEnded(
        target,
        this.elementA,
        false, // queueTransition — checked by the hook, not the engine
        this.currentIsA,
        this.crossfadeActive,
      );
      if (willHandle) {
        this.emit({ type: 'ended' });
      }
    };

    const handleError = (e: Event) => {
      const target = e.target as HTMLAudioElement;
      const currentElement = this.getCurrentElement();
      const action = getErrorAction(
        target,
        currentElement,
        this.crossfadeActive,
        true, // we assume playing — the hook will check
      );

      if (action === 'ignore') return;

      const mediaError = target.error;
      const message = mediaError?.message || 'Failed to play track';

      if (action === 'cancel-crossfade') {
        this.cancelCrossfade();
        // Don't emit error — just cancelled the crossfade preload
        return;
      }

      if (action === 'cancel-crossfade-and-stop') {
        this.cancelCrossfade();
      }

      this.emit({ type: 'error', message });
    };

    const handlePlaying = (e: Event) => {
      const target = e.target as HTMLAudioElement;
      const trackId = target.getAttribute('data-track-id');
      if (trackId) {
        this.emit({ type: 'playing', trackId });
      }
    };

    const handleWaiting = (e: Event) => {
      const target = e.target as HTMLAudioElement;
      if (target === this.getCurrentElement()) {
        this.emit({ type: 'waiting' });
      }
    };

    const handleStalled = (e: Event) => {
      const target = e.target as HTMLAudioElement;
      const isCurrent = target === this.getCurrentElement();
      log.warn('stalled event', {
        isCurrent,
        readyState: target.readyState,
        networkState: target.networkState,
        currentTime: target.currentTime,
      });
    };

    const handlePause = (e: Event) => {
      const target = e.target as HTMLAudioElement;
      const isCurrent = target === this.getCurrentElement();
      if (isCurrent && !target.ended) {
        log.debug('pause event (external interruption)', { currentTime: target.currentTime });
      }
    };

    // timeupdate fires ~4Hz from the browser media engine, even in background tabs.
    // This is the primary source of time updates for the seek bar and crossfade timing.
    const handleTimeUpdate = (e: Event) => {
      const target = e.target as HTMLAudioElement;
      if (target !== this.getCurrentElement()) return;
      if (target.paused) return;

      const duration = Number.isFinite(target.duration) && target.duration > 0 ? target.duration : 0;
      this.emit({
        type: 'timeUpdate',
        currentTime: target.currentTime,
        duration,
      });
    };

    elements.forEach(el => {
      el.addEventListener('ended', handleEnded);
      el.addEventListener('error', handleError);
      el.addEventListener('playing', handlePlaying);
      el.addEventListener('waiting', handleWaiting);
      el.addEventListener('stalled', handleStalled);
      el.addEventListener('pause', handlePause);
      el.addEventListener('timeupdate', handleTimeUpdate);
    });

    this.domListenerCleanups.push(() => {
      elements.forEach(el => {
        el.removeEventListener('ended', handleEnded);
        el.removeEventListener('error', handleError);
        el.removeEventListener('playing', handlePlaying);
        el.removeEventListener('waiting', handleWaiting);
        el.removeEventListener('stalled', handleStalled);
        el.removeEventListener('pause', handlePause);
        el.removeEventListener('timeupdate', handleTimeUpdate);
      });
    });
  }

  // ========================================================================
  // Visibility Recovery
  // ========================================================================

  private setupVisibilityRecovery(): void {
    this.visibilityHandler = () => {
      if (document.hidden) return;
      const el = this.getCurrentElement();
      // Resume AudioContext if suspended
      if (this.audioContext?.state === 'suspended') {
        this.audioContext.resume().catch(e => log.error('Failed to resume AudioContext', e));
      }
      // Element pause recovery is handled by the hook's play/pause effect
      if (el?.paused && !el.ended) {
        log.debug('visibility recovery: element paused, emitting for hook handling');
      }
    };
    document.addEventListener('visibilitychange', this.visibilityHandler);
  }

  // ========================================================================
  // AudioContext State Recovery
  // ========================================================================

  private setupContextStateRecovery(): void {
    if (!this.audioContext) return;
    this.contextStateHandler = () => {
      if (this.audioContext?.state === 'suspended') {
        log.debug('AudioContext suspended, attempting resume');
        this.audioContext.resume().catch(e => log.error('Failed to resume AudioContext', e));
      }
    };
    this.audioContext.addEventListener('statechange', this.contextStateHandler);
  }

}
