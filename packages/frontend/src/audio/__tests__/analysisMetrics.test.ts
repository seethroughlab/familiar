import { describe, expect, it } from 'vitest';
import {
  computeFrequencyBands,
  getInterleavedSpectrumIndex,
  getRadialBarLayout,
  getRadialBarLength,
  sampleVisualizerBinValue,
  summarizeAnalysisFrame,
} from '../analysisMetrics';

function makeFixture(kind: 'kick' | 'treble' | 'pad'): Uint8Array {
  const bins = new Uint8Array(128).fill(8);

  if (kind === 'kick') {
    for (let i = 0; i < 10; i++) bins[i] = 220;
    for (let i = 10; i < 24; i++) bins[i] = 120;
    for (let i = 24; i < bins.length; i++) bins[i] = Math.max(6, 40 - Math.floor(i / 6));
    return bins;
  }

  if (kind === 'treble') {
    for (let i = 0; i < 24; i++) bins[i] = 18;
    for (let i = 24; i < 60; i++) bins[i] = 55;
    for (let i = 60; i < bins.length; i++) bins[i] = 210;
    return bins;
  }

  for (let i = 0; i < bins.length; i++) {
    const distance = Math.abs(i - 38);
    bins[i] = Math.max(18, 120 - distance * 3);
  }
  return bins;
}

function makeTimeDomain(amplitude: number): Uint8Array {
  const values = new Uint8Array(128);
  for (let i = 0; i < values.length; i++) {
    const sample = Math.sin((i / values.length) * Math.PI * 2) * amplitude;
    values[i] = Math.round(sample * 127 + 128);
  }
  return values;
}

describe('analysisMetrics', () => {
  it('matches expected band dominance for fixture families', () => {
    const kick = computeFrequencyBands(makeFixture('kick'));
    const bright = computeFrequencyBands(makeFixture('treble'));
    const pad = computeFrequencyBands(makeFixture('pad'));

    expect(kick.bass).toBeGreaterThan(kick.mid);
    expect(kick.bass).toBeGreaterThan(kick.treble);

    expect(bright.treble).toBeGreaterThan(bright.bass);
    expect(bright.treble).toBeGreaterThan(bright.mid);

    expect(pad.mid).toBeGreaterThan(pad.bass);
    expect(pad.mid).toBeGreaterThan(pad.treble);
  });

  it('summarizes frame variance, strongest bin, and waveform energy', () => {
    const summary = summarizeAnalysisFrame(makeFixture('kick'), makeTimeDomain(0.75));

    expect(summary.binCount).toBe(128);
    expect(summary.variance).toBeGreaterThan(0);
    expect(summary.strongestBinIndex).toBeLessThan(12);
    expect(summary.strongestBinValue).toBeGreaterThan(0.8);
    expect(summary.rms).toBeGreaterThan(0.45);
    expect(summary.peak).toBeGreaterThan(0.7);
  });

  it('uses weighted bar sampling that still emphasizes low-frequency musical structure', () => {
    const kick = makeFixture('kick');
    const firstBar = sampleVisualizerBinValue(kick, 0, 128, {
      usableBinsRatio: 0.82,
      lowFrequencyEmphasis: 0.25,
      minWindowSize: 2,
    });
    const lastBar = sampleVisualizerBinValue(kick, 127, 128, {
      usableBinsRatio: 0.82,
      lowFrequencyEmphasis: 0.25,
      minWindowSize: 2,
    });

    expect(firstBar).toBeGreaterThan(lastBar);
    expect(lastBar).toBeGreaterThanOrEqual(0);
  });

  it('maps radial bars deterministically around a full circle with no zero-length collapse', () => {
    const first = getRadialBarLayout(0, 128);
    const quarter = getRadialBarLayout(32, 128);
    const half = getRadialBarLayout(64, 128);
    const silentLength = getRadialBarLength(0, { minLength: 0.62, maxExtraLength: 4.25 });

    expect(first.angle).toBeCloseTo(-Math.PI / 2, 5);
    expect(quarter.directionX).toBeGreaterThan(0.99);
    expect(half.directionY).toBeGreaterThan(0.99);
    expect(silentLength).toBeCloseTo(0.62, 5);
  });

  it('interleaves spectrum indices so low and high frequencies are neighbors around the ring', () => {
    expect(getInterleavedSpectrumIndex(0, 128)).toBe(0);
    expect(getInterleavedSpectrumIndex(1, 128)).toBe(127);
    expect(getInterleavedSpectrumIndex(2, 128)).toBe(1);
    expect(getInterleavedSpectrumIndex(3, 128)).toBe(126);
  });

  it('gives bass-heavy fixtures stronger radial lengths than treble-heavy fixtures in bass-emphasis zones', () => {
    const kick = makeFixture('kick');
    const bright = makeFixture('treble');

    const kickMagnitude = sampleVisualizerBinValue(kick, getInterleavedSpectrumIndex(0, 128), 128, {
      usableBinsRatio: 0.84,
      lowFrequencyEmphasis: 0.24,
      minWindowSize: 2,
    });
    const brightMagnitude = sampleVisualizerBinValue(bright, getInterleavedSpectrumIndex(0, 128), 128, {
      usableBinsRatio: 0.84,
      lowFrequencyEmphasis: 0.24,
      minWindowSize: 2,
    });

    const kickLength = getRadialBarLength(kickMagnitude, {
      minLength: 0.62,
      maxExtraLength: 4.25,
      responseCurve: 1.15,
    });
    const brightLength = getRadialBarLength(brightMagnitude, {
      minLength: 0.62,
      maxExtraLength: 4.25,
      responseCurve: 1.15,
    });

    expect(kickLength).toBeGreaterThan(brightLength);
  });
});
