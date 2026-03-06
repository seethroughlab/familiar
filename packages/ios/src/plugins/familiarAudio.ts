import { registerPlugin } from '@capacitor/core';
import type { PluginListenerHandle } from '@capacitor/core';

export interface FamiliarAudioPlugin {
  // Playback
  load(options: { url: string; trackId: string }): Promise<void>;
  play(): Promise<void>;
  pause(): Promise<void>;
  resume(): Promise<void>;
  seek(options: { time: number }): Promise<void>;
  stop(): Promise<void>;
  setVolume(options: { volume: number }): Promise<void>;
  getCurrentTime(): Promise<{ currentTime: number }>;
  getDuration(): Promise<{ duration: number }>;
  getIsPlaying(): Promise<{ isPlaying: boolean }>;

  // Effects
  setEQ(options: {
    lowGain: number;
    midGain: number;
    highGain: number;
    lowFreq?: number;
    midFreq?: number;
    highFreq?: number;
    enabled?: boolean;
  }): Promise<void>;
  setReverb(options: {
    preset: string;
    wetDryMix: number;
    enabled: boolean;
    preDelay?: number;
  }): Promise<void>;
  setDelay(options: {
    time: number;
    feedback: number;
    wetDryMix: number;
    enabled: boolean;
    pingPong?: boolean;
  }): Promise<void>;
  setDistortion(options: {
    preset: string;
    wetDryMix: number;
    enabled: boolean;
    drive?: number;
  }): Promise<void>;
  setCompressor(options: {
    threshold: number;
    ratio: number;
    attack: number;
    release: number;
    knee: number;
    makeupGain: number;
    enabled: boolean;
  }): Promise<void>;
  setFilter(options: {
    highpassFreq: number;
    lowpassFreq: number;
    highpassQ: number;
    lowpassQ: number;
    enabled: boolean;
  }): Promise<void>;
  setMasterBypass(options: { bypassed: boolean }): Promise<void>;

  // Now Playing
  setNowPlayingInfo(options: {
    title: string;
    artist: string;
    album: string;
    artworkUrl?: string;
  }): Promise<void>;

  // Crossfade
  preloadNext(options: { url: string; trackId: string }): Promise<{ success: boolean }>;
  isNextReady(): Promise<{ ready: boolean }>;
  getPreloadingTrackId(): Promise<{ trackId: string | null }>;
  isCrossfading(): Promise<{ crossfading: boolean }>;
  executeCrossfade(options: { duration: number }): Promise<void>;
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
    handler: (data: { message: string }) => void,
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
    event: 'audioAnalysis',
    handler: (data: { frequencyData: number[]; timeDomainData: number[] }) => void,
  ): Promise<PluginListenerHandle>;
}

export const FamiliarAudio = registerPlugin<FamiliarAudioPlugin>('FamiliarAudio');
