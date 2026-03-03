/**
 * Hook to extract color palette from album artwork.
 *
 * Automatically extracts dominant colors from the provided artwork URL
 * with caching for performance.
 *
 * @example
 * ```tsx
 * function MyVisualizer({ artworkUrl }: VisualizerProps) {
 *   const palette = useArtworkPalette(artworkUrl);
 *   // palette = ['#ff0000', '#00ff00', '#0000ff', '#ffff00', '#ff00ff']
 * }
 * ```
 */
import { useState, useEffect } from 'react';
import { extractPalette } from '../../../utils/colorExtraction';

/** Default palette when artwork is unavailable */
const DEFAULT_PALETTE = ['#a855f7', '#06b6d4', '#22c55e', '#f59e0b', '#ec4899'];

/**
 * Extract dominant colors from album artwork.
 *
 * @param artworkUrl - URL of the album artwork, null if unavailable
 * @param numColors - Number of colors to extract (default 5)
 * @returns Array of hex color strings, or default palette if unavailable
 */
export function useArtworkPalette(
  artworkUrl: string | null,
  numColors: number = 5
): string[] {
  const [palette, setPalette] = useState<string[]>(DEFAULT_PALETTE);

  useEffect(() => {
    if (!artworkUrl) {
      setPalette(DEFAULT_PALETTE);
      return;
    }

    let cancelled = false;

    extractPalette(artworkUrl, numColors)
      .then((colors) => {
        if (!cancelled) {
          setPalette(colors);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPalette(DEFAULT_PALETTE);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [artworkUrl, numColors]);

  return palette;
}

export { DEFAULT_PALETTE };
