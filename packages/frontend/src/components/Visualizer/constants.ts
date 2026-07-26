/** Default visualizer shown on first load. */
export const DEFAULT_VISUALIZER_ID = 'reactive-terrain';

/** Well-known visualizer IDs to avoid magic strings. */
export const VISUALIZER_IDS = {
  REACTIVE_TERRAIN: 'reactive-terrain',
  BEAT_TILES: 'beat-tiles',
  LYRICS: 'lyrics',
  MUSIC_VIDEO: 'music-video',
} as const;

/** localStorage key for persisted visualizer preference. */
export const VISUALIZER_STORAGE_KEY = 'familiar-visualizer';
