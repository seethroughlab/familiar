/**
 * Hook to synchronize animations with the detected BPM.
 *
 * Provides beat timing information for creating BPM-synced visualizations.
 * The hook tracks elapsed time and calculates the current beat position.
 *
 * @example
 * ```tsx
 * function MyVisualizer({ features, currentTime }: VisualizerProps) {
 *   const { beat, beatProgress, onBeat, bpm } = useBeatSync(features?.bpm, currentTime);
 *
 *   // Scale up on beat
 *   const scale = onBeat ? 1.2 : 1.0;
 *
 *   // Smooth pulse using beat progress (0-1)
 *   const pulse = Math.sin(beatProgress * Math.PI);
 * }
 * ```
 */
import { useState, useEffect, useRef } from 'react';

export interface BeatSyncData {
  /** Current beat number (starts at 0) */
  beat: number;
  /** Progress through current beat (0-1) */
  beatProgress: number;
  /** True when we just hit a new beat (for triggering effects) */
  onBeat: boolean;
  /** Beats per minute being used */
  bpm: number;
  /** Seconds per beat */
  beatDuration: number;
}

/** Default BPM when not detected */
const DEFAULT_BPM = 120;

/** Threshold for detecting "on beat" (fraction of beat duration) */
const ON_BEAT_THRESHOLD = 0.1;

/**
 * Synchronize with detected BPM for beat-aligned animations.
 *
 * @param bpm - Detected BPM from audio analysis, null uses default (120)
 * @param currentTime - Current playback time in seconds
 * @returns Beat timing information
 */
export function useBeatSync(
  bpm: number | null | undefined,
  currentTime: number
): BeatSyncData {
  const [beatData, setBeatData] = useState<BeatSyncData>({
    beat: 0,
    beatProgress: 0,
    onBeat: false,
    bpm: DEFAULT_BPM,
    beatDuration: 60 / DEFAULT_BPM,
  });

  const lastBeatRef = useRef(-1);

  useEffect(() => {
    const effectiveBpm = bpm && bpm > 0 ? bpm : DEFAULT_BPM;
    const beatDuration = 60 / effectiveBpm;

    // Calculate beat position from current time
    const beatPosition = currentTime / beatDuration;
    const currentBeat = Math.floor(beatPosition);
    const beatProgress = beatPosition - currentBeat;

    // Detect if we just hit a new beat
    const onBeat = currentBeat !== lastBeatRef.current && beatProgress < ON_BEAT_THRESHOLD;

    if (currentBeat !== lastBeatRef.current) {
      lastBeatRef.current = currentBeat;
    }

    setBeatData({
      beat: currentBeat,
      beatProgress,
      onBeat,
      bpm: effectiveBpm,
      beatDuration,
    });
  }, [bpm, currentTime]);

  return beatData;
}

/**
 * Get the beat phase for smooth animations.
 * Returns a value from 0-1 that cycles with each beat.
 *
 * @param currentTime - Current playback time in seconds
 * @param bpm - Beats per minute
 * @param phase - Phase offset (0-1, default 0)
 * @returns Normalized beat phase (0-1)
 */
export function getBeatPhase(
  currentTime: number,
  bpm: number = DEFAULT_BPM,
  phase: number = 0
): number {
  const beatDuration = 60 / bpm;
  const beatPosition = currentTime / beatDuration + phase;
  return beatPosition - Math.floor(beatPosition);
}

/**
 * Get a sine wave synchronized to the beat.
 * Useful for smooth pulsing effects.
 *
 * @param currentTime - Current playback time in seconds
 * @param bpm - Beats per minute
 * @param phase - Phase offset (0-1, default 0)
 * @returns Value from -1 to 1
 */
export function getBeatSine(
  currentTime: number,
  bpm: number = DEFAULT_BPM,
  phase: number = 0
): number {
  return Math.sin(getBeatPhase(currentTime, bpm, phase) * Math.PI * 2);
}

export { DEFAULT_BPM };
