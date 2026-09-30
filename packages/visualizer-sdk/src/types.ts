/** What a visualizer is handed. The plugin's own copy — the host lends nothing (ADR-0087 point 2). */

/**
 * The track's audio features as the host sends them: `TrackAnalysis` scalars, keyed by name.
 * Almost all are numbers (energy, valence, danceability, tempo…); a few are strings (key, mode).
 * Read a numeric one through `feature()`, which returns the default for anything else.
 */
export type TrackFeatures = Record<string, number | string | boolean | null | undefined>;

/** A lyric line as the host sends it — `time` in seconds, `text` as written. */
export interface LyricLine {
  time: number;
  text: string;
}

export interface VisualizerProps {
  currentTime: number;
  duration: number;
  isPlaying: boolean;
  track: { id: string; title?: string | null; artist?: string | null } | null;
  features: TrackFeatures | null;
  artworkUrl: string | null;
  lyrics: LyricLine[] | null;
}

/** A numeric feature, or `fallback` when the host sent none or sent something that is not a number. */
export function feature(features: TrackFeatures | null | undefined, name: string, fallback: number): number {
  const value = features?.[name];
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}
