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
  }): Promise<void>;
  setReverb(options: {
    preset: string;
    wetDryMix: number;
    enabled: boolean;
  }): Promise<void>;
  setDelay(options: {
    time: number;
    feedback: number;
    wetDryMix: number;
    enabled: boolean;
  }): Promise<void>;
  setDistortion(options: {
    preset: string;
    wetDryMix: number;
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
    handler: () => void,
  ): Promise<PluginListenerHandle>;
  addListener(
    event: 'remotePrevious',
    handler: () => void,
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
