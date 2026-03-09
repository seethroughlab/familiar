import type { AudioEngine, AudioEngineCapabilities, EngineEvent } from '@familiar/frontend/src/player/audio/types';
import { FamiliarAudio } from './plugins/familiarAudio';
import { setNativeAnalysisBuffers, clearNativeAnalysisBuffers } from '@familiar/frontend/src/hooks/useAudioAnalyser';
import { log } from '@familiar/frontend/src/player/audio/platform';
import { tracksApi } from '@familiar/frontend/src/api';
import { getOfflineTrackNativeUri } from '@familiar/frontend/src/services/offlineService';
import { prefetchService } from '@familiar/frontend/src/services/prefetchService';
import { useConnectivityStore } from '@familiar/frontend/src/stores/connectivityStore';

// ============================================================================
// CapacitorEngine — Native iOS/Android via FamiliarAudio Capacitor plugin
// ============================================================================

type EventHandler = (event: EngineEvent) => void;
type EngineDiagnostic = { ts: number; event: string; details?: Record<string, unknown> };

export class CapacitorEngine implements AudioEngine {
  readonly capabilities: AudioEngineCapabilities = {
    crossfade: true,
    visualizer: true,
    effects: 'native',
  };

  // State
  private loadedTrackId: string | null = null;
  private masterVolume = 1;
  private normalizationGain = 1;
  private consecutiveLoadFailures = 0;
  private lastKnownDuration = 0;

  // Crossfade state (tracked locally to keep sync interface)
  private nextLoadedTrackId: string | null = null;
  private localPreloadingTrackId: string | null = null;
  private localIsCrossfading = false;

  // Pre-allocated analysis buffers (reused each bridge event to avoid per-frame allocations)
  private analysisFreqBuffer: Uint8Array | null = null;
  private analysisTimeBuffer: Uint8Array | null = null;

  // Event subscribers
  private handlers: Set<EventHandler> = new Set();

  // Plugin listener cleanup functions
  private listenerCleanups: (() => void)[] = [];
  private diagnostics: EngineDiagnostic[] = [];

  // ========================================================================
  // Lifecycle
  // ========================================================================

  initialize(): boolean {
    this.setupPluginListeners();
    this.recordDiagnostic('initialize');
    log.info('CapacitorEngine initialized (AVAudioEngine plugin)');
    return true;
  }

  dispose(): void {
    clearNativeAnalysisBuffers();
    this.analysisFreqBuffer = null;
    this.analysisTimeBuffer = null;
    this.listenerCleanups.forEach(cleanup => cleanup());
    this.listenerCleanups = [];
    this.handlers.clear();
    this.recordDiagnostic('dispose');
  }

  // ========================================================================
  // Playback
  // ========================================================================

  private isNativeFileUrl(url: string): boolean {
    return url.startsWith('file://') || url.startsWith('capacitor://') || url.startsWith('content://');
  }

  async load(trackId: string, url: string): Promise<void> {
    try {
      if (this.isNativeFileUrl(url)) {
        await FamiliarAudio.loadLocal({ path: url, trackId });
      } else {
        await FamiliarAudio.load({ url, trackId });
      }
      this.recordDiagnostic('load', { trackId, source: url.startsWith('file://') ? 'local' : 'remote' });
      this.loadedTrackId = trackId;
      this.consecutiveLoadFailures = 0;

      // Query duration eagerly so progress bar works even if early timeUpdate events lack it
      try {
        const { duration } = await FamiliarAudio.getDuration();
        if (Number.isFinite(duration) && duration > 0) {
          this.lastKnownDuration = duration;
          this.emit({ type: 'timeUpdate', currentTime: 0, duration });
        }
      } catch { /* ignore — timer-based updates will provide it later */ }
    } catch (e) {
      this.consecutiveLoadFailures++;
      this.recordDiagnostic('load-error', { trackId });
      const cleanUrl = url.split('?')[0]; // strip query params (auth tokens)
      const errMsg = e instanceof Error ? e.message : String(e);
      log.error('Failed to load track (native) trackId=%s url=%s err=%s', trackId, cleanUrl, errMsg);

      if (this.consecutiveLoadFailures > 3) {
        log.error('Too many consecutive native load failures (%d)', this.consecutiveLoadFailures);
        this.consecutiveLoadFailures = 0;
      }
      throw e;
    }
  }

  async play(): Promise<void> {
    await FamiliarAudio.play();
  }

  pause(): void {
    FamiliarAudio.pause().catch(e => log.error('Native pause failed', e));
  }

  seek(time: number): void {
    if (!Number.isFinite(time)) return;
    try {
      FamiliarAudio.seek({ time });
    } catch (e) {
      log.error('Native seek failed', e);
    }
  }

  stop(): void {
    FamiliarAudio.stop().catch(e => log.error('Native stop failed', e));
    this.loadedTrackId = null;
    this.nextLoadedTrackId = null;
    this.localPreloadingTrackId = null;
    this.localIsCrossfading = false;
  }

  // ========================================================================
  // Volume & Normalization
  // ========================================================================

  setVolume(volume: number): void {
    this.masterVolume = volume;
    FamiliarAudio.setVolume({ volume: Math.min(1, this.masterVolume * this.normalizationGain) });
  }

  setNormalizationGain(gain: number): void {
    this.normalizationGain = gain;
    FamiliarAudio.setVolume({ volume: Math.min(1, this.masterVolume * this.normalizationGain) });
  }

  // ========================================================================
  // Crossfade
  // ========================================================================

  async preloadNext(trackId: string, url: string): Promise<boolean> {
    this.localPreloadingTrackId = trackId;
    try {
      const result = this.isNativeFileUrl(url)
        ? await FamiliarAudio.preloadNextLocal({ path: url, trackId })
        : await FamiliarAudio.preloadNext({ url, trackId });
      const { success } = result;
      if (!success && result.reason) {
        log.warn('preloadNext rejected by native engine', { trackId, reason: result.reason, state: result.state });
      }
      if (success) {
        this.nextLoadedTrackId = trackId;
      }
      this.recordDiagnostic('preload-next', { trackId, success });
      this.localPreloadingTrackId = null;
      return success;
    } catch (e) {
      this.localPreloadingTrackId = null;
      log.error('preloadNext failed', e);
      return false;
    }
  }

  isNextReady(): boolean {
    return this.nextLoadedTrackId !== null;
  }

  getPreloadingTrackId(): string | null {
    return this.localPreloadingTrackId;
  }

  isCrossfading(): boolean {
    return this.localIsCrossfading;
  }

  setNextNormalizationGain(gain: number): void {
    FamiliarAudio.setNextNormalizationVolume({ volume: this.masterVolume * gain }).catch(e =>
      log.error('setNextNormalizationVolume failed', e)
    );
  }

  executeCrossfade(duration: number, onComplete: () => void): void {
    this.localIsCrossfading = true;
    this.recordDiagnostic('crossfade-start', { duration });
    FamiliarAudio.executeCrossfade({ duration })
      .then((result) => {
        if (result.success === false) {
          this.localIsCrossfading = false;
          this.recordDiagnostic('crossfade-rejected', { reason: result.reason });
          log.warn('executeCrossfade rejected by native engine', { reason: result.reason });
          onComplete();
          return;
        }
        // Update loadedTrackId to the track that just faded in
        if (this.nextLoadedTrackId) {
          this.loadedTrackId = this.nextLoadedTrackId;
        }
        this.nextLoadedTrackId = null;
        this.localIsCrossfading = false;
        this.recordDiagnostic('crossfade-complete');
        onComplete();
      })
      .catch(e => {
        this.localIsCrossfading = false;
        this.recordDiagnostic('crossfade-error');
        log.error('executeCrossfade failed', e);
        onComplete();
      });
  }

  cancelCrossfade(): void {
    FamiliarAudio.cancelCrossfade().catch(e => log.error('cancelCrossfade failed', e));
    this.nextLoadedTrackId = null;
    this.localPreloadingTrackId = null;
    this.localIsCrossfading = false;
    this.recordDiagnostic('crossfade-cancel');
  }

  // ========================================================================
  // State
  // ========================================================================

  getCurrentTime(): number {
    return 0; // Time comes via timeUpdate events; synchronous getter not useful for native
  }

  getDuration(): number {
    return this.lastKnownDuration;
  }

  getLoadedTrackId(): string | null {
    return this.loadedTrackId;
  }

  /** Check if we've exceeded the consecutive load failure threshold */
  hasExceededFailureThreshold(): boolean {
    return this.consecutiveLoadFailures > 3;
  }

  async resolveTrackUrl(trackId: string): Promise<{ url: string; isOffline: boolean }> {
    const nativeUri = await getOfflineTrackNativeUri(trackId);
    if (nativeUri) {
      return { url: nativeUri, isOffline: true };
    }
    // Check prefetch cache
    const prefetched = prefetchService.getUrl(trackId);
    if (prefetched) return prefetched;
    if (useConnectivityStore.getState().offlineModeActive) {
      const err = new Error('Track unavailable while offline');
      (err as Error & { code?: string }).code = 'offline-unavailable';
      throw err;
    }
    return { url: tracksApi.getStreamUrl(trackId), isOffline: false };
  }

  // ========================================================================
  // Events
  // ========================================================================

  on(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => { this.handlers.delete(handler); };
  }

  private emit(event: EngineEvent): void {
    this.recordDiagnostic(`event:${event.type}`);
    this.handlers.forEach(h => h(event));
  }

  private recordDiagnostic(event: string, details?: Record<string, unknown>): void {
    this.diagnostics.push({ ts: Date.now(), event, details });
    if (this.diagnostics.length > 200) {
      this.diagnostics.splice(0, this.diagnostics.length - 200);
    }
    (window as unknown as { __familiarNativeAudioDiagnostics?: EngineDiagnostic[] }).__familiarNativeAudioDiagnostics = [...this.diagnostics];
  }

  // ========================================================================
  // Media Session / Now Playing
  // ========================================================================

  updateNowPlaying(metadata: {
    title: string;
    artist: string;
    album: string;
    artworkUrl?: string;
  }): void {
    try {
      FamiliarAudio.setNowPlayingInfo({
        title: metadata.title,
        artist: metadata.artist,
        album: metadata.album,
        artworkUrl: metadata.artworkUrl,
      });
    } catch (e) {
      log.warn('Failed to set native now playing info', e);
    }
  }

  // ========================================================================
  // Pending Track Sync (lock screen next/previous)
  // ========================================================================

  syncPendingTracks(info: {
    next: { url: string; trackId: string; title: string; artist: string; album: string; artworkUrl?: string } | null;
    previous: { url: string; trackId: string; title: string; artist: string; album: string; artworkUrl?: string } | null;
  }): void {
    FamiliarAudio.setPendingTrackInfo({
      nextUrl: info.next?.url,
      nextTrackId: info.next?.trackId,
      nextTitle: info.next?.title,
      nextArtist: info.next?.artist,
      nextAlbum: info.next?.album,
      nextArtworkUrl: info.next?.artworkUrl,
      prevUrl: info.previous?.url,
      prevTrackId: info.previous?.trackId,
      prevTitle: info.previous?.title,
      prevArtist: info.previous?.artist,
      prevAlbum: info.previous?.album,
      prevArtworkUrl: info.previous?.artworkUrl,
    }).catch(e => log.warn('Failed to sync pending tracks', e));
  }

  // ========================================================================
  // Plugin Event Listeners
  // ========================================================================

  private setupPluginListeners(): void {
    // ended
    FamiliarAudio.addListener('ended', () => {
      this.emit({ type: 'ended' });
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    // timeUpdate — always forward currentTime; coerce bad duration to last-known or 0
    FamiliarAudio.addListener('timeUpdate', (data) => {
      const currentTime = data.currentTime ?? 0;
      const duration = (Number.isFinite(data.duration) && data.duration > 0)
        ? data.duration
        : this.lastKnownDuration;
      if (Number.isFinite(data.duration) && data.duration > 0) {
        this.lastKnownDuration = data.duration;
      }
      this.emit({ type: 'timeUpdate', currentTime, duration });
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    // error
    FamiliarAudio.addListener('error', (data) => {
      const code = data.category === 'network'
        ? 'network-unreachable'
        : data.category === 'decode'
          ? 'media-decode'
          : data.category === 'state'
            ? 'state'
            : data.category === 'resource'
              ? 'resource'
              : undefined;
      this.emit({ type: 'error', message: data.message, code });
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    // Remote commands (lock screen / Control Center)
    FamiliarAudio.addListener('remotePlay', () => {
      this.emit({ type: 'remotePlay' });
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    FamiliarAudio.addListener('remotePause', () => {
      this.emit({ type: 'remotePause' });
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    FamiliarAudio.addListener('remoteNext', (data) => {
      if (data?.loadedTrackId) {
        this.loadedTrackId = data.loadedTrackId;
      }
      this.emit({ type: 'remoteNext' });
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    FamiliarAudio.addListener('remotePrevious', (data) => {
      if (data?.loadedTrackId) {
        this.loadedTrackId = data.loadedTrackId;
      }
      this.emit({
        type: 'remotePrevious',
        nativeAction: data?.nativeAction === 'restart' ? 'restart' : undefined,
      });
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    FamiliarAudio.addListener('remoteSeek', (data) => {
      this.emit({ type: 'remoteSeek', time: data.time });
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    // Audio analysis (native FFT data for visualizers)
    FamiliarAudio.addListener('audioAnalysis', (data) => {
      const freq: number[] = data.frequencyData;
      const time: number[] = data.timeDomainData;
      // Lazily allocate buffers, then reuse via element-wise copy
      if (!this.analysisFreqBuffer || this.analysisFreqBuffer.length !== freq.length) {
        this.analysisFreqBuffer = new Uint8Array(freq.length);
      }
      if (!this.analysisTimeBuffer || this.analysisTimeBuffer.length !== time.length) {
        this.analysisTimeBuffer = new Uint8Array(time.length);
      }
      for (let i = 0; i < freq.length; i++) this.analysisFreqBuffer[i] = freq[i];
      for (let i = 0; i < time.length; i++) this.analysisTimeBuffer[i] = time[i];
      setNativeAnalysisBuffers(this.analysisFreqBuffer, this.analysisTimeBuffer);
    }).then(h => this.listenerCleanups.push(() => h.remove()));
  }
}
