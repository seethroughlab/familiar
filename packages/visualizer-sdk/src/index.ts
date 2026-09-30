/**
 * `@familiar/visualizer-sdk` (ADR-0125).
 *
 * A build-time dependency: a visualizer bundles what it imports from here into its own `app.js`,
 * and the host serves no shared JavaScript. Only behaviour proven by at least two first-party
 * visualizers belongs here (point 5); scene code stays with its document.
 */
export {
  API_VERSION,
  GLOW_LEVEL,
  announceReady,
  getAudioData,
  handleMessage,
  install,
  useAudioAnalyser,
  usePlaybackState,
  useTrack,
  type AudioData,
  type PlaybackState,
  type TrackInfo,
} from './familiar';
export { feature, type LyricLine, type TrackFeatures, type VisualizerProps } from './types';
export { FrameScheduler } from './FrameScheduler';
export { AudioReactiveEffects } from './AudioReactiveEffects';
export { usePalette, clearPaletteCache } from './colorExtraction';
export { useArtworkPalette } from './useArtworkPalette';
