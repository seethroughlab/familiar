/**
 * Tests for volume normalization gain calculations.
 * These test the pure computation extracted from useAudioEngine's normalization logic.
 */
import { describe, it, expect } from 'vitest';

// Extract the pure computation function for testing.
// This mirrors computeNormalizationGain from useAudioEngine.ts
function computeNormalizationGain(
  opts: {
    normalizationEnabled: boolean;
    normalizationTargetLufs: number;
    normalizationPreamp: number;
    normalizationPreventClipping: boolean;
    useAlbumGain: boolean;
  },
  track: { loudness_lufs?: number; track_peak?: number } | null,
  albumData?: { avgLufs: number; albumPeak: number | null } | null,
): number {
  if (!opts.normalizationEnabled) return 1;
  if (!track?.loudness_lufs) return 1;

  const useAlbum = albumData && opts.useAlbumGain;
  const lufs = useAlbum ? albumData.avgLufs : track.loudness_lufs;
  let gainDb = opts.normalizationTargetLufs - lufs + opts.normalizationPreamp;

  if (opts.normalizationPreventClipping) {
    const peak = useAlbum ? albumData.albumPeak : track.track_peak;
    if (peak) {
      const maxGainDb = -20 * Math.log10(peak + 1e-10);
      gainDb = Math.min(gainDb, maxGainDb);
    }
  }

  return Math.pow(10, gainDb / 20);
}

const defaultOpts = {
  normalizationEnabled: true,
  normalizationTargetLufs: -14,
  normalizationPreamp: 0,
  normalizationPreventClipping: false,
  useAlbumGain: false,
};

describe('Normalization gain calculations', () => {
  it('returns gain of 1 when normalization is disabled', () => {
    const result = computeNormalizationGain(
      { ...defaultOpts, normalizationEnabled: false },
      { loudness_lufs: -20, track_peak: 0.9 },
    );
    expect(result).toBe(1);
  });

  it('returns gain of 1 when track has no LUFS data', () => {
    const result = computeNormalizationGain(
      defaultOpts,
      { loudness_lufs: undefined },
    );
    expect(result).toBe(1);
  });

  it('returns gain of 1 when track is null', () => {
    const result = computeNormalizationGain(defaultOpts, null);
    expect(result).toBe(1);
  });

  it('computes correct gain from LUFS difference (quiet track gets boosted)', () => {
    // Track at -20 LUFS, target -14 LUFS -> need +6dB
    const result = computeNormalizationGain(
      defaultOpts,
      { loudness_lufs: -20 },
    );
    const expectedGainDb = -14 - (-20); // +6 dB
    const expectedLinear = Math.pow(10, expectedGainDb / 20);
    expect(result).toBeCloseTo(expectedLinear, 6);
    expect(result).toBeGreaterThan(1); // boost
  });

  it('computes correct gain from LUFS difference (loud track gets attenuated)', () => {
    // Track at -8 LUFS, target -14 LUFS -> need -6dB
    const result = computeNormalizationGain(
      defaultOpts,
      { loudness_lufs: -8 },
    );
    const expectedGainDb = -14 - (-8); // -6 dB
    const expectedLinear = Math.pow(10, expectedGainDb / 20);
    expect(result).toBeCloseTo(expectedLinear, 6);
    expect(result).toBeLessThan(1); // attenuate
  });

  it('returns gain of 1 when track matches target (no adjustment needed)', () => {
    const result = computeNormalizationGain(
      defaultOpts,
      { loudness_lufs: -14 },
    );
    expect(result).toBeCloseTo(1, 6);
  });

  it('applies preamp to gain calculation', () => {
    // Track at -14 LUFS (matches target), preamp +3dB
    const result = computeNormalizationGain(
      { ...defaultOpts, normalizationPreamp: 3 },
      { loudness_lufs: -14 },
    );
    const expectedLinear = Math.pow(10, 3 / 20);
    expect(result).toBeCloseTo(expectedLinear, 6);
  });

  it('clipping prevention caps gain based on peak', () => {
    // Track at -20 LUFS with peak near 1.0 (0dBFS)
    // Needs +6dB but peak is already at maximum
    const result = computeNormalizationGain(
      { ...defaultOpts, normalizationPreventClipping: true },
      { loudness_lufs: -20, track_peak: 0.9 },
    );

    const desiredGainDb = -14 - (-20); // +6 dB
    const maxGainDb = -20 * Math.log10(0.9 + 1e-10); // ~0.92 dB
    const expectedGainDb = Math.min(desiredGainDb, maxGainDb);
    const expectedLinear = Math.pow(10, expectedGainDb / 20);

    expect(result).toBeCloseTo(expectedLinear, 6);
    // The gain should be capped well below +6dB
    expect(result).toBeLessThan(Math.pow(10, 6 / 20));
  });

  it('clipping prevention allows gain when peak is low', () => {
    // Track at -20 LUFS with low peak (0.1 = -20dBFS)
    // Needs +6dB, peak allows up to +20dB
    const result = computeNormalizationGain(
      { ...defaultOpts, normalizationPreventClipping: true },
      { loudness_lufs: -20, track_peak: 0.1 },
    );

    const desiredGainDb = -14 - (-20); // +6 dB
    const expectedLinear = Math.pow(10, desiredGainDb / 20);
    expect(result).toBeCloseTo(expectedLinear, 6);
  });

  it('album mode uses album average LUFS', () => {
    const result = computeNormalizationGain(
      { ...defaultOpts, useAlbumGain: true },
      { loudness_lufs: -20 }, // track LUFS
      { avgLufs: -16, albumPeak: null }, // album LUFS
    );

    // Should use -16 (album) not -20 (track)
    const expectedGainDb = -14 - (-16); // +2 dB
    const expectedLinear = Math.pow(10, expectedGainDb / 20);
    expect(result).toBeCloseTo(expectedLinear, 6);
  });

  it('album mode uses album peak for clipping prevention', () => {
    const result = computeNormalizationGain(
      { ...defaultOpts, useAlbumGain: true, normalizationPreventClipping: true },
      { loudness_lufs: -20, track_peak: 0.5 },
      { avgLufs: -22, albumPeak: 0.95 },
    );

    const desiredGainDb = -14 - (-22); // +8 dB
    const maxGainDb = -20 * Math.log10(0.95 + 1e-10); // ~0.45 dB
    const expectedGainDb = Math.min(desiredGainDb, maxGainDb);
    const expectedLinear = Math.pow(10, expectedGainDb / 20);

    expect(result).toBeCloseTo(expectedLinear, 6);
  });

  it('falls back to track LUFS when album data is not provided', () => {
    const result = computeNormalizationGain(
      { ...defaultOpts, useAlbumGain: true },
      { loudness_lufs: -20 },
      null, // no album data
    );

    // Should fall back to track LUFS
    const expectedGainDb = -14 - (-20); // +6 dB
    const expectedLinear = Math.pow(10, expectedGainDb / 20);
    expect(result).toBeCloseTo(expectedLinear, 6);
  });
});
