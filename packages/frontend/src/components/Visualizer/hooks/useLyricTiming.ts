/**
 * Hook to get current lyric timing information.
 *
 * Provides the current and next lyric lines based on playback time,
 * along with progress through the current line.
 *
 * @example
 * ```tsx
 * function LyricVisualizer({ lyrics, currentTime }: VisualizerProps) {
 *   const { currentLine, nextLine, progress, words } = useLyricTiming(lyrics, currentTime);
 *
 *   return (
 *     <div>
 *       <p style={{ opacity: 1 - progress }}>{currentLine?.text}</p>
 *       <p style={{ opacity: progress }}>{nextLine?.text}</p>
 *     </div>
 *   );
 * }
 * ```
 */
import { useMemo } from 'react';
import type { LyricLine } from '../../../api';

export interface LyricTimingData {
  /** Current lyric line being sung, null if none */
  currentLine: LyricLine | null;
  /** Index of current line in lyrics array */
  currentIndex: number;
  /** Next lyric line coming up, null if none */
  nextLine: LyricLine | null;
  /** Progress through current line (0-1), 0 if no current line */
  progress: number;
  /** Time until next line starts in seconds, Infinity if no next line */
  timeToNext: number;
  /** Individual words from current line for per-word animations */
  words: string[];
  /** Whether lyrics are available */
  hasLyrics: boolean;
}

/**
 * Get current lyric timing information.
 *
 * @param lyrics - Array of time-synced lyric lines, null if unavailable
 * @param currentTime - Current playback time in seconds
 * @returns Lyric timing data
 */
export function useLyricTiming(
  lyrics: LyricLine[] | null,
  currentTime: number
): LyricTimingData {
  return useMemo(() => {
    if (!lyrics || lyrics.length === 0) {
      return {
        currentLine: null,
        currentIndex: -1,
        nextLine: null,
        progress: 0,
        timeToNext: Infinity,
        words: [],
        hasLyrics: false,
      };
    }

    // Find current line (last line that started before currentTime)
    let currentIndex = -1;
    for (let i = lyrics.length - 1; i >= 0; i--) {
      if (lyrics[i].time <= currentTime) {
        currentIndex = i;
        break;
      }
    }

    const currentLine = currentIndex >= 0 ? lyrics[currentIndex] : null;
    const nextLine = currentIndex < lyrics.length - 1 ? lyrics[currentIndex + 1] : null;

    // Calculate progress through current line
    let progress = 0;
    if (currentLine && nextLine) {
      const lineDuration = nextLine.time - currentLine.time;
      if (lineDuration > 0) {
        progress = Math.min(1, (currentTime - currentLine.time) / lineDuration);
      }
    } else if (currentLine) {
      // Last line - estimate 5 seconds duration
      const estimatedDuration = 5;
      progress = Math.min(1, (currentTime - currentLine.time) / estimatedDuration);
    }

    // Time until next line
    const timeToNext = nextLine ? nextLine.time - currentTime : Infinity;

    // Split current line into words
    const words = currentLine?.text.split(/\s+/).filter(Boolean) ?? [];

    return {
      currentLine,
      currentIndex,
      nextLine,
      progress,
      timeToNext,
      words,
      hasLyrics: true,
    };
  }, [lyrics, currentTime]);
}

/**
 * Get all upcoming lyrics within a time window.
 *
 * @param lyrics - Array of time-synced lyric lines
 * @param currentTime - Current playback time in seconds
 * @param windowSeconds - How far ahead to look (default 10 seconds)
 * @returns Array of upcoming lyric lines
 */
export function getUpcomingLyrics(
  lyrics: LyricLine[] | null,
  currentTime: number,
  windowSeconds: number = 10
): LyricLine[] {
  if (!lyrics) return [];

  return lyrics.filter(
    (line) =>
      line.time >= currentTime &&
      line.time <= currentTime + windowSeconds
  );
}

/**
 * Get word timing for per-word animations.
 * Estimates word timing by evenly distributing words across line duration.
 *
 * @param line - Current lyric line
 * @param nextLineStart - Start time of next line (for duration)
 * @param currentTime - Current playback time
 * @returns Array of { word, progress } objects
 */
export function getWordTiming(
  line: LyricLine | null,
  nextLineStart: number | null,
  currentTime: number
): Array<{ word: string; progress: number; isActive: boolean }> {
  if (!line) return [];

  const words = line.text.split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];

  // Estimate line duration
  const lineDuration = nextLineStart
    ? nextLineStart - line.time
    : 5; // Default 5 seconds for last line

  const wordDuration = lineDuration / words.length;
  const elapsed = currentTime - line.time;

  return words.map((word, i) => {
    const wordStart = i * wordDuration;
    const wordEnd = (i + 1) * wordDuration;
    const isActive = elapsed >= wordStart && elapsed < wordEnd;
    const progress = Math.max(0, Math.min(1, (elapsed - wordStart) / wordDuration));

    return { word, progress, isActive };
  });
}
