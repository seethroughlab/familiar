/** Default visualizer shown on first load. */
export const DEFAULT_VISUALIZER_ID = 'reactive-terrain';

/**
 * Well-known visualizer IDs to avoid magic strings.
 *
 * All five built-ins, and it must stay that way: a plugin claiming one of these ids is refused, so
 * a missing entry here is a reserved id nothing in this file records. `lyric-storm` was absent from
 * this list for as long as it has existed.
 */
export const VISUALIZER_IDS = {
  REACTIVE_TERRAIN: 'reactive-terrain',
  BEAT_TILES: 'beat-tiles',
  LYRICS: 'lyrics',
  MUSIC_VIDEO: 'music-video',
  LYRIC_STORM: 'lyric-storm',
} as const;

/** localStorage key for persisted visualizer preference. */
export const VISUALIZER_STORAGE_KEY = 'familiar-visualizer';
