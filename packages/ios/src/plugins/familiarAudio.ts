import { registerPlugin } from '@capacitor/core';
import type { PluginListenerHandle } from '@capacitor/core';

export interface FamiliarAudioPlugin {
  // Playback
  load(options: { url: string; trackId: string }): Promise<void>;
  loadLocal(options: { path: string; trackId: string }): Promise<void>;
  play(): Promise<void>;
  pause(): Promise<void>;
  resume(): Promise<void>;
  seek(options: { time: number }): Promise<void>;
  stop(): Promise<void>;
  setVolume(options: { volume: number }): Promise<void>;
  getCurrentTime(): Promise<{ currentTime: number }>;
  getDuration(): Promise<{ duration: number }>;
  getIsPlaying(): Promise<{ isPlaying: boolean }>;

  // Now Playing
  setNowPlayingInfo(options: {
    title: string;
    artist: string;
    album: string;
    artworkUrl?: string;
    albumArtist?: string;
    trackNumber?: number;
    discNumber?: number;
    year?: number;
    isFavorite?: boolean;
  }): Promise<void>;

  // Updates only the lock-screen favorite state without resetting full metadata
  setFavoriteState(options: { trackId: string; isFavorite: boolean }): Promise<void>;

  // Crossfade
  preloadNext(options: { url: string; trackId: string }): Promise<{ success: boolean; state?: 'idle' | 'preloading' | 'ready' | 'failed'; reason?: string }>;
  preloadNextLocal(options: { path: string; trackId: string }): Promise<{ success: boolean; state?: 'idle' | 'preloading' | 'ready' | 'failed'; reason?: string }>;
  isNextReady(): Promise<{ ready: boolean }>;
  getPreloadingTrackId(): Promise<{ trackId: string | null }>;
  isCrossfading(): Promise<{ crossfading: boolean }>;
  executeCrossfade(options: { duration: number }): Promise<{ success: boolean; reason?: string }>;
  cancelCrossfade(): Promise<void>;
  setNextNormalizationVolume(options: { volume: number }): Promise<void>;

  // Pending track info for lock screen next/previous
  setPendingTrackInfo(options: {
    nextUrl?: string;
    nextTrackId?: string;
    nextTitle?: string;
    nextArtist?: string;
    nextAlbum?: string;
    nextArtworkUrl?: string;
    prevUrl?: string;
    prevTrackId?: string;
    prevTitle?: string;
    prevArtist?: string;
    prevAlbum?: string;
    prevArtworkUrl?: string;
  }): Promise<void>;

  // Events
  addListener(
    event: 'ended',
    handler: () => void,
  ): Promise<PluginListenerHandle>;
  addListener(
    event: 'timeUpdate',
    handler: (data: { currentTime: number; duration: number }) => void,
  ): Promise<PluginListenerHandle>;
  addListener(
    event: 'error',
    handler: (data: { message: string; category?: 'network' | 'decode' | 'state' | 'resource' }) => void,
  ): Promise<PluginListenerHandle>;
  addListener(
    event: 'remotePlay',
    handler: () => void,
  ): Promise<PluginListenerHandle>;
  addListener(
    event: 'remotePause',
    handler: () => void,
  ): Promise<PluginListenerHandle>;
  addListener(
    event: 'remoteNext',
    handler: (data: { loadedTrackId?: string }) => void,
  ): Promise<PluginListenerHandle>;
  addListener(
    event: 'remotePrevious',
    handler: (data: { nativeAction?: string; loadedTrackId?: string }) => void,
  ): Promise<PluginListenerHandle>;
  addListener(
    event: 'remoteSeek',
    handler: (data: { time: number }) => void,
  ): Promise<PluginListenerHandle>;
  addListener(
    event: 'favoriteToggled',
    handler: (data: { trackId: string }) => void,
  ): Promise<PluginListenerHandle>;
  addListener(
    event: 'nativeAutoAdvanced',
    handler: (data: { loadedTrackId?: string }) => void,
  ): Promise<PluginListenerHandle>;
}

export const FamiliarAudio = registerPlugin<FamiliarAudioPlugin>('FamiliarAudio');
