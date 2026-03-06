/**
 * Color extraction utility for album art.
 *
 * Extracts dominant colors from images using canvas sampling.
 */
import { createLogger } from './logger';
import { isNativeApp } from './platform';

const log = createLogger('ColorExtraction');

// Cache extracted palettes by URL
const paletteCache = new Map<string, string[]>();

/**
 * Load an image and return it as an HTMLImageElement.
 */
async function loadImage(url: string): Promise<HTMLImageElement> {
  const img = new Image();
  img.crossOrigin = 'anonymous';

  if (isNativeApp()) {
    const res = await fetch(url);
    const blob = await res.blob();
    img.src = URL.createObjectURL(blob);
  } else {
    img.src = url;
  }

  return new Promise((resolve, reject) => {
    img.onload = () => resolve(img);
    img.onerror = reject;
  });
}

/**
 * Convert RGB to HSL.
 */
function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  r /= 255;
  g /= 255;
  b /= 255;

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h = 0;
  let s = 0;
  const l = (max + min) / 2;

  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);

    switch (max) {
      case r:
        h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
        break;
      case g:
        h = ((b - r) / d + 2) / 6;
        break;
      case b:
        h = ((r - g) / d + 4) / 6;
        break;
    }
  }

  return [h, s, l];
}

/**
 * Simple color clustering using k-means-like approach.
 */
function clusterColors(
  pixels: Uint8ClampedArray,
  numColors: number
): string[] {
  // Sample every Nth pixel for performance
  const sampleRate = 10;
  const colors: Array<[number, number, number]> = [];

  for (let i = 0; i < pixels.length; i += 4 * sampleRate) {
    const r = pixels[i];
    const g = pixels[i + 1];
    const b = pixels[i + 2];
    const a = pixels[i + 3];

    // Skip transparent pixels
    if (a < 128) continue;

    // Skip very dark or very light pixels
    const [, s, l] = rgbToHsl(r, g, b);
    if (l < 0.1 || l > 0.9 || s < 0.1) continue;

    colors.push([r, g, b]);
  }

  if (colors.length === 0) {
    // Fallback colors if no good colors found
    return ['#4a00e0', '#8e2de2', '#00ffff', '#ff00ff', '#ffff00'];
  }

  // Simple bucketing by hue
  const buckets: Map<number, Array<[number, number, number]>> = new Map();

  for (const [r, g, b] of colors) {
    const [h] = rgbToHsl(r, g, b);
    const bucket = Math.floor(h * 12); // 12 hue buckets
    if (!buckets.has(bucket)) {
      buckets.set(bucket, []);
    }
    buckets.get(bucket)!.push([r, g, b]);
  }

  // Sort buckets by size and take the largest ones
  const sortedBuckets = Array.from(buckets.entries())
    .sort((a, b) => b[1].length - a[1].length)
    .slice(0, numColors);

  // Get average color from each bucket
  const result: string[] = [];
  for (const [, bucket] of sortedBuckets) {
    const avgR = Math.round(bucket.reduce((sum, c) => sum + c[0], 0) / bucket.length);
    const avgG = Math.round(bucket.reduce((sum, c) => sum + c[1], 0) / bucket.length);
    const avgB = Math.round(bucket.reduce((sum, c) => sum + c[2], 0) / bucket.length);

    result.push(`#${avgR.toString(16).padStart(2, '0')}${avgG.toString(16).padStart(2, '0')}${avgB.toString(16).padStart(2, '0')}`);
  }

  // Pad with defaults if we don't have enough colors
  const defaults = ['#4a00e0', '#8e2de2', '#00ffff', '#ff00ff', '#ffff00'];
  while (result.length < numColors) {
    result.push(defaults[result.length % defaults.length]);
  }

  return result;
}

/**
 * Extract a color palette from an image URL.
 *
 * @param url - Image URL to extract colors from
 * @param numColors - Number of colors to extract (default 5)
 * @returns Array of hex color strings
 */
export async function extractPalette(
  url: string,
  numColors: number = 5
): Promise<string[]> {
  // Check cache
  const cached = paletteCache.get(url);
  if (cached) {
    return cached;
  }

  try {
    const img = await loadImage(url);

    // Create canvas and draw image
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      throw new Error('Could not get canvas context');
    }

    // Resize for faster processing
    const size = 100;
    canvas.width = size;
    canvas.height = size;
    ctx.drawImage(img, 0, 0, size, size);

    // Get pixel data
    const imageData = ctx.getImageData(0, 0, size, size);
    const colors = clusterColors(imageData.data, numColors);

    // Cache result
    paletteCache.set(url, colors);

    return colors;
  } catch (error) {
    log.warn('Failed to extract palette:', error);
    // Return default palette on error
    return ['#4a00e0', '#8e2de2', '#00ffff', '#ff00ff', '#ffff00'];
  }
}

/**
 * Clear the palette cache.
 */
export function clearPaletteCache(): void {
  paletteCache.clear();
}

/**
 * Hook to use extracted colors with caching.
 */
export function usePalette(url: string | null): string[] | null {
  // This is a simple synchronous check - if cached, return immediately
  if (!url) return null;
  return paletteCache.get(url) || null;
}
