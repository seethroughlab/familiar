/**
 * The audio analyser, re-exported for the host page's visualizer components.
 *
 * Plugins get their helpers from `@familiar/visualizer-sdk` (ADR-0125); the copies of the beat,
 * lyric-timing, palette and effects helpers that used to sit beside this had no importer.
 */
export { useAudioAnalyser, getAudioData, type AudioAnalysisData } from '../../../hooks/useAudioAnalyser';
