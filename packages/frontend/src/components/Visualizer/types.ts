/**
 * Visualizer types and registry.
 *
 * This module defines the public API for visualizers, enabling community
 * contributions with full access to track metadata, audio analysis, and
 * real-time audio data.
 */
import type { ComponentType } from 'react';
import type { Track, TrackFeatures } from '../../types';
import type { LyricLine } from '../../api';

/**
 * Metadata about a visualizer for the picker UI.
 */
export interface VisualizerMetadata {
  id: string;
  name: string;
  description: string;
  usesMetadata: boolean; // Whether it needs track/artwork data
  /** Optional: author name for community visualizers */
  author?: string;
  /** Optional: preview image URL */
  previewUrl?: string;
}

/**
 * Real-time audio analysis data from Web Audio API.
 * Access via useAudioAnalyser() hook or getAudioData() for useFrame.
 */
export interface AudioData {
  /** Raw frequency bin data (0-255 per bin) */
  frequencyData: Uint8Array;
  /** Raw waveform data (0-255, centered at 128) */
  timeDomainData: Uint8Array;
  /** Bass frequencies (20-200Hz), normalized 0-1 */
  bass: number;
  /** Mid frequencies (200Hz-2kHz), normalized 0-1 */
  mid: number;
  /** Treble frequencies (2kHz-20kHz), normalized 0-1 */
  treble: number;
  /** Overall audio intensity, 0-255 */
  averageFrequency: number;
}

/**
 * Audio technical specifications.
 */
export interface AudioSpecs {
  /** Duration in seconds */
  durationSeconds: number;
  /** Audio format (mp3, flac, m4a, etc.) */
  format: string;
}

/**
 * Props passed to all visualizer components.
 *
 * Use the provided hooks for enhanced functionality:
 * - useAudioAnalyser() - Real-time audio data (bass, mid, treble, frequency bins)
 * - useArtworkPalette(artworkUrl) - Extract dominant colors from artwork
 * - useBeatSync(bpm) - Sync animations to detected BPM
 * - useLyricTiming(lyrics, currentTime) - Get current/next lyric lines
 */
export interface VisualizerProps {
  // === Playback State ===
  /** Current playback position in seconds */
  currentTime: number;
  /** Track duration in seconds */
  duration: number;
  /** Whether audio is currently playing */
  isPlaying: boolean;

  // === Track Metadata ===
  /** Full track object with all metadata, null if nothing playing */
  track: Track | null;

  // === Audio Analysis Features ===
  /** Analyzed audio features (BPM, key, energy, etc.), null if not analyzed */
  features: TrackFeatures | null;

  // === Media ===
  /** Album artwork URL, null if unavailable */
  artworkUrl: string | null;
  /** Time-synced lyrics, null if unavailable */
  lyrics: LyricLine[] | null;
}

/**
 * Extended props available to visualizers that opt-in to real-time audio.
 * Most visualizers should use the useAudioAnalyser() hook instead.
 */
export interface VisualizerPropsWithAudio extends VisualizerProps {
  /** Real-time audio analysis data, requires useAudioAnalyser() hook */
  audioData: AudioData | null;
}

/**
 * A registered visualizer with metadata and component.
 */
export interface RegisteredVisualizer {
  metadata: VisualizerMetadata;
  component: ComponentType<VisualizerProps>;
}

/**
 * Visualizer registry - maps id to visualizer info.
 */
export const visualizerRegistry: Map<string, RegisteredVisualizer> = new Map();

/**
 * Register a visualizer in the registry.
 */
export function registerVisualizer(
  metadata: VisualizerMetadata,
  component: ComponentType<VisualizerProps>
): void {
  visualizerRegistry.set(metadata.id, { metadata, component });
}

/**
 * Get all registered visualizers.
 */
export function getVisualizers(): RegisteredVisualizer[] {
  return Array.from(visualizerRegistry.values());
}

/**
 * Get a specific visualizer by ID.
 */
export function getVisualizer(id: string): RegisteredVisualizer | undefined {
  return visualizerRegistry.get(id);
}

/**
 * Default visualizer ID.
 */
export const DEFAULT_VISUALIZER_ID = 'cosmic-orb';
