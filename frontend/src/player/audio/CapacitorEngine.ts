import type { AudioEngine, AudioEngineCapabilities, EngineEvent } from './types';
import { FamiliarAudio } from '../../plugins/familiarAudio';
import { setNativeAnalysisBuffers, clearNativeAnalysisBuffers } from '../../hooks/useAudioAnalyser';
import { log } from './platform';

// ============================================================================
// CapacitorEngine — Native iOS/Android via FamiliarAudio Capacitor plugin
// ============================================================================

type EventHandler = (event: EngineEvent) => void;

export class CapacitorEngine implements AudioEngine {
  readonly capabilities: AudioEngineCapabilities = {
    crossfade: false,
    visualizer: true,
    effects: 'native',
  };

  // State
  private loadedTrackId: string | null = null;
  private masterVolume = 1;
  private normalizationGain = 1;
  private consecutiveLoadFailures = 0;

  // Event subscribers
  private handlers: Set<EventHandler> = new Set();

  // Plugin listener cleanup functions
  private listenerCleanups: (() => void)[] = [];

  // ========================================================================
  // Lifecycle
  // ========================================================================

  initialize(): boolean {
    this.setupPluginListeners();
    log.info('CapacitorEngine initialized (AVAudioEngine plugin)');
    return true;
  }

  dispose(): void {
    clearNativeAnalysisBuffers();
    this.listenerCleanups.forEach(cleanup => cleanup());
    this.listenerCleanups = [];
    this.handlers.clear();
  }

  // ========================================================================
  // Playback
  // ========================================================================

  async load(trackId: string, url: string): Promise<void> {
    try {
      await FamiliarAudio.load({ url, trackId });
      this.loadedTrackId = trackId;
      this.consecutiveLoadFailures = 0;
    } catch (e) {
      this.consecutiveLoadFailures++;
      log.error('Failed to load track (native)', e);

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
  // State
  // ========================================================================

  getCurrentTime(): number {
    return 0; // Time comes via timeUpdate events; synchronous getter not useful for native
  }

  getDuration(): number {
    return 0; // Duration comes via timeUpdate events
  }

  getLoadedTrackId(): string | null {
    return this.loadedTrackId;
  }

  /** Check if we've exceeded the consecutive load failure threshold */
  hasExceededFailureThreshold(): boolean {
    return this.consecutiveLoadFailures > 3;
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
  // Plugin Event Listeners
  // ========================================================================

  private setupPluginListeners(): void {
    // ended
    FamiliarAudio.addListener('ended', () => {
      this.emit({ type: 'ended' });
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    // timeUpdate
    FamiliarAudio.addListener('timeUpdate', (data) => {
      if (Number.isFinite(data.duration) && data.duration > 0) {
        this.emit({
          type: 'timeUpdate',
          currentTime: data.currentTime,
          duration: data.duration,
        });
      }
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    // error
    FamiliarAudio.addListener('error', (data) => {
      this.emit({ type: 'error', message: data.message });
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    // Remote commands (lock screen / Control Center)
    FamiliarAudio.addListener('remotePlay', () => {
      this.emit({ type: 'remotePlay' });
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    FamiliarAudio.addListener('remotePause', () => {
      this.emit({ type: 'remotePause' });
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    FamiliarAudio.addListener('remoteNext', () => {
      this.emit({ type: 'remoteNext' });
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    FamiliarAudio.addListener('remotePrevious', () => {
      this.emit({ type: 'remotePrevious' });
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    FamiliarAudio.addListener('remoteSeek', (data) => {
      this.emit({ type: 'remoteSeek', time: data.time });
    }).then(h => this.listenerCleanups.push(() => h.remove()));

    // Audio analysis (native FFT data for visualizers)
    FamiliarAudio.addListener('audioAnalysis', (data) => {
      setNativeAnalysisBuffers(
        Uint8Array.from(data.frequencyData),
        Uint8Array.from(data.timeDomainData),
      );
    }).then(h => this.listenerCleanups.push(() => h.remove()));
  }
}
