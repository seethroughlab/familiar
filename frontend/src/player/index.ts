// Player module — public API
//
// Consolidates playerStore, audioSettingsStore, useAudioEngine, useAudioControls,
// persistence, and the audio engine into a single module boundary.

// Store & types
export { usePlayerStore } from './playerStore';
export type { QueueSourceType, QueueSource, LibraryFilters } from './playerStore';

// Audio settings
export { useAudioSettingsStore } from './audioSettingsStore';
export type { NormalizationMode } from './audioSettingsStore';

// Hooks
export { useAudioEngine } from './useAudioEngine';
export { useAudioControls } from './useAudioControls';

// Persistence
export {
  savePlayerState,
  loadPlayerState,
  loadPlayerStateForProfile,
  fetchTracksBatched,
  clearPlayerState,
  migrateOldPlayerState,
  debouncedSavePlayerState,
} from './persistence';

// Audio engine — public getters used by visualizer, effects, keyboard shortcuts, WebRTC
export {
  getEngine,
  getAudioAnalyser,
  getAudioContext,
  getAudioEffectsChain,
  areAudioEffectsAvailable,
  isVisualizerAvailable,
  getCurrentMode,
  getGlobalMasterGain,
} from './audio/engineInstance';
