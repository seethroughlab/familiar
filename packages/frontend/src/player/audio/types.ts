// ============================================================================
// AudioEngine Abstraction Layer — Types & Interfaces
// ============================================================================

/**
 * Discriminated union of events emitted by any AudioEngine implementation.
 * The hook subscribes once with engine.on(), no platform branching needed.
 */
export type EngineEvent =
  | { type: 'ended' }
  | { type: 'error'; message: string; code?: 'offline-unavailable' | 'network-unreachable' | 'media-decode' | 'state' | 'resource' | 'unknown' }
  | { type: 'playing'; trackId: string }
  | { type: 'waiting' }
  | { type: 'timeUpdate'; currentTime: number; duration: number }
  | { type: 'remotePlay' }
  | { type: 'remotePause' }
  | { type: 'remoteNext' }
  | { type: 'remotePrevious'; nativeAction?: 'restart' }
  | { type: 'remoteSeek'; time: number }
  | { type: 'remoteFavoriteToggle'; trackId: string }
  | { type: 'nativeAutoAdvanced' };

/**
 * What each engine supports. The hook checks these before calling optional methods.
 */
export interface AudioEngineCapabilities {
  crossfade: boolean;
  visualizer: boolean;
  effects: 'web' | 'native' | 'none';
}

/**
 * Unified interface for audio playback engines.
 *
 * Two implementations:
 * - WebAudioEngine: Desktop browser (AudioContext + HTMLAudioElement)
 * - CapacitorEngine: Native iOS/Android (FamiliarAudio Capacitor plugin)
 */
export interface AudioEngine {
  readonly capabilities: AudioEngineCapabilities;

  // Lifecycle
  initialize(): boolean;
  dispose(): void;

  // Playback
  load(trackId: string, url: string, options?: { isOffline?: boolean; isExternal?: boolean }): Promise<void>;
  play(): Promise<void>;
  pause(): void;
  seek(time: number): void;
  stop(): void;

  // Volume & normalization (hook computes gain, engine applies it)
  setVolume(volume: number): void;
  setNormalizationGain(gain: number): void;

  // State
  getCurrentTime(): number;
  getDuration(): number;
  getLoadedTrackId(): string | null;

  // Events (returns unsubscribe function)
  on(handler: (event: EngineEvent) => void): () => void;

  // Media session / Now Playing
  updateNowPlaying(metadata: {
    title: string;
    artist: string;
    album: string;
    artworkUrl?: string;
    albumArtist?: string;
    trackNumber?: number;
    discNumber?: number;
    year?: number;
    isFavorite?: boolean;
  }): void;

  // Optional: Update the favorite state displayed on the lock screen without
  // re-sending the full metadata (iOS only)
  setFavoriteState?(trackId: string, isFavorite: boolean): void;

  // Optional: Pending track sync for lock screen (CapacitorEngine only)
  syncPendingTracks?(info: {
    next: { url: string; trackId: string; title: string; artist: string; album: string; artworkUrl?: string } | null;
    previous: { url: string; trackId: string; title: string; artist: string; album: string; artworkUrl?: string } | null;
  }): void;

  // Optional: Crossfade (WebAudioEngine only)
  preloadNext?(trackId: string, url: string, opts?: { isOffline?: boolean; isExternal?: boolean }): Promise<boolean>;
  setNextNormalizationGain?(gain: number): void;
  executeCrossfade?(duration: number, onComplete: () => void): void;
  cancelCrossfade?(): void;
  isCrossfading?(): boolean;

  // Optional: URL resolution & preload tracking (WebAudioEngine only)
  resolveTrackUrl?(trackId: string): Promise<{ url: string; isOffline: boolean }>;
  getPreloadingTrackId?(): string | null;
  isNextReady?(): boolean;

  // Optional: Media session action availability (WebAudioEngine only)
  updateMediaSessionActions?(info: { canGoNext: boolean; canGoPrevious: boolean }): void;

  // Optional: Visualizer + debug tooling (WebAudioEngine only)
  getAnalyser?(): AnalyserNode | null;
  getAudioContext?(): AudioContext | null;
  getMasterGainNode?(): GainNode | null;
}
