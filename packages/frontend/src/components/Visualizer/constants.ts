/** Default visualizer shown on first load. */
export const DEFAULT_VISUALIZER_ID = 'cosmic-orb';

/** Well-known visualizer IDs to avoid magic strings. */
export const VISUALIZER_IDS = {
  COSMIC_ORB: 'cosmic-orb',
  FREQUENCY_BARS: 'frequency-bars',
  ALBUM_KALEIDOSCOPE: 'album-kaleidoscope',
  LYRICS: 'lyrics',
  RAIN_WINDOW: 'rain-window',
  MUSIC_VIDEO: 'music-video',
} as const;

/** localStorage key for persisted visualizer preference. */
export const VISUALIZER_STORAGE_KEY = 'familiar-visualizer';
