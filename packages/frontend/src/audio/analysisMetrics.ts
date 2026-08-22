export interface FrequencyBands {
  averageFrequency: number;
  bass: number;
  mid: number;
  treble: number;
}

export interface AnalysisFrameSummary extends FrequencyBands {
  binCount: number;
  averageBinLevel: number;
  variance: number;
  strongestBinIndex: number;
  strongestBinValue: number;
  rms: number;
  peak: number;
}

export interface RadialBarLayout {
  angle: number;
  directionX: number;
  directionY: number;
  thickness: number;
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

export function computeFrequencyBands(freqData: ArrayLike<number>): FrequencyBands {
  const binCount = freqData.length;
  if (binCount === 0) {
    return {
      averageFrequency: 0,
      bass: 0,
      mid: 0,
      treble: 0,
    };
  }

  let sum = 0;
  for (let i = 0; i < binCount; i++) {
    sum += freqData[i];
  }

  const bassEnd = Math.max(1, Math.floor(binCount * 0.1));
  const midEnd = Math.max(bassEnd + 1, Math.floor(binCount * 0.5));

  let bassSum = 0;
  for (let i = 0; i < bassEnd; i++) {
    bassSum += freqData[i];
  }

  let midSum = 0;
  for (let i = bassEnd; i < midEnd; i++) {
    midSum += freqData[i];
  }

  let trebleSum = 0;
  for (let i = midEnd; i < binCount; i++) {
    trebleSum += freqData[i];
  }

  return {
    averageFrequency: sum / binCount,
    bass: clamp01(bassSum / bassEnd / 255),
    mid: clamp01(midSum / Math.max(1, midEnd - bassEnd) / 255),
    treble: clamp01(trebleSum / Math.max(1, binCount - midEnd) / 255),
  };
}

export function summarizeAnalysisFrame(
  frequencyData: ArrayLike<number>,
  timeDomainData?: ArrayLike<number>,
): AnalysisFrameSummary {
  const binCount = frequencyData.length;
  const bands = computeFrequencyBands(frequencyData);

  let varianceSum = 0;
  let strongestBinIndex = 0;
  let strongestBinValue = 0;

  for (let i = 0; i < binCount; i++) {
    const normalized = frequencyData[i] / 255;
    const delta = normalized - bands.averageFrequency / 255;
    varianceSum += delta * delta;
    if (normalized > strongestBinValue) {
      strongestBinValue = normalized;
      strongestBinIndex = i;
    }
  }

  let rms = 0;
  let peak = 0;
  if (timeDomainData && timeDomainData.length > 0) {
    let sumSquares = 0;
    for (let i = 0; i < timeDomainData.length; i++) {
      const centered = (timeDomainData[i] - 128) / 127;
      const abs = Math.abs(centered);
      if (abs > peak) peak = abs;
      sumSquares += centered * centered;
    }
    rms = Math.sqrt(sumSquares / timeDomainData.length);
  }

  return {
    ...bands,
    binCount,
    averageBinLevel: bands.averageFrequency / 255,
    variance: binCount > 0 ? varianceSum / binCount : 0,
    strongestBinIndex,
    strongestBinValue,
    rms: clamp01(rms),
    peak: clamp01(peak),
  };
}

export function sampleVisualizerBinValue(
  frequencyData: ArrayLike<number>,
  index: number,
  totalBars: number,
  options?: {
    usableBinsRatio?: number;
    lowFrequencyEmphasis?: number;
    minWindowSize?: number;
  },
): number {
  if (!frequencyData.length || totalBars <= 0) return 0;

  const usableBinsRatio = options?.usableBinsRatio ?? 0.8;
  const lowFrequencyEmphasis = options?.lowFrequencyEmphasis ?? 0.18;
  const minWindowSize = options?.minWindowSize ?? 2;
  const usableBins = Math.max(1, Math.floor(frequencyData.length * usableBinsRatio));

  const startNorm = Math.pow(index / totalBars, 2.2);
  const endNorm = Math.pow((index + 1) / totalBars, 2.2);
  const start = Math.min(usableBins - 1, Math.floor(startNorm * usableBins));
  const end = Math.min(
    usableBins,
    Math.max(start + minWindowSize, Math.ceil(endNorm * usableBins)),
  );

  let sum = 0;
  let weightSum = 0;
  for (let i = start; i < end; i++) {
    const binNorm = usableBins <= 1 ? 0 : i / (usableBins - 1);
    const lowWeight = 1 + lowFrequencyEmphasis * (1 - binNorm);
    sum += (frequencyData[i] / 255) * lowWeight;
    weightSum += lowWeight;
  }

  return weightSum > 0 ? clamp01(sum / weightSum) : 0;
}

export function getInterleavedSpectrumIndex(index: number, totalBars: number): number {
  if (totalBars <= 1) return 0;
  const clampedIndex = Math.max(0, Math.min(totalBars - 1, index));
  const pairIndex = Math.floor(clampedIndex / 2);
  return clampedIndex % 2 === 0
    ? pairIndex
    : totalBars - 1 - pairIndex;
}

export function getRadialBarLayout(
  index: number,
  totalBars: number,
  options?: {
    startAngle?: number;
    baseThickness?: number;
    thicknessTaper?: number;
  },
): RadialBarLayout {
  const startAngle = options?.startAngle ?? -Math.PI / 2;
  const baseThickness = options?.baseThickness ?? 0.08;
  const thicknessTaper = options?.thicknessTaper ?? 0.18;
  const normalizedIndex = totalBars <= 1 ? 0 : index / (totalBars - 1);
  const angle = startAngle + (index / Math.max(1, totalBars)) * Math.PI * 2;
  const taper = 1 - normalizedIndex * thicknessTaper;

  return {
    angle,
    directionX: Math.cos(angle),
    directionY: Math.sin(angle),
    thickness: Math.max(0.02, baseThickness * taper),
  };
}

export function getRadialBarLength(
  magnitude: number,
  options?: {
    minLength?: number;
    maxExtraLength?: number;
    responseCurve?: number;
  },
): number {
  const minLength = options?.minLength ?? 0.45;
  const maxExtraLength = options?.maxExtraLength ?? 3.8;
  const responseCurve = options?.responseCurve ?? 1.28;
  const curved = Math.pow(clamp01(magnitude), responseCurve);
  return minLength + curved * maxExtraLength;
}
