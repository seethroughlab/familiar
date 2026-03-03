/**
 * Visualizer Hooks
 *
 * Utility hooks for building visualizers with access to audio, artwork,
 * beat timing, and lyric information.
 */

// Re-export audio analyser from main hooks
export { useAudioAnalyser, getAudioData, type AudioAnalysisData } from '../../../hooks/useAudioAnalyser';

// Artwork color extraction
export { useArtworkPalette, DEFAULT_PALETTE } from './useArtworkPalette';

// BPM synchronization
export {
  useBeatSync,
  getBeatPhase,
  getBeatSine,
  DEFAULT_BPM,
  type BeatSyncData,
} from './useBeatSync';

// Lyric timing
export {
  useLyricTiming,
  getUpcomingLyrics,
  getWordTiming,
  type LyricTimingData,
} from './useLyricTiming';
