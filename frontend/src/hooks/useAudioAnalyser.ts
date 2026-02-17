import { useState, useEffect, useRef, useCallback } from 'react';
import { getAudioAnalyser, getAudioContext } from './audio/audioGraph';

export interface AudioAnalysisData {
  frequencyData: Uint8Array;
  timeDomainData: Uint8Array;
  averageFrequency: number;
  bass: number;
  mid: number;
  treble: number;
}

// Shared ref for audio data that can be read inside useFrame
const sharedAudioDataRef: { current: AudioAnalysisData | null } = { current: null };

// Get current audio data synchronously (for use in useFrame)
export function getAudioData(): AudioAnalysisData | null {
  return sharedAudioDataRef.current;
}

export function useAudioAnalyser(enabled: boolean = true): AudioAnalysisData | null {
  const [data, setData] = useState<AudioAnalysisData | null>(null);
  const animationFrameRef = useRef<number | undefined>(undefined);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const frequencyDataRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const timeDomainDataRef = useRef<any>(null);

  const analyse = useCallback(() => {
    const analyser = getAudioAnalyser();
    const context = getAudioContext();

    if (!analyser || !context || context.state !== 'running') {
      animationFrameRef.current = requestAnimationFrame(analyse);
      return;
    }

    // Initialize data arrays if needed
    if (!frequencyDataRef.current) {
      frequencyDataRef.current = new Uint8Array(analyser.frequencyBinCount);
    }
    if (!timeDomainDataRef.current) {
      timeDomainDataRef.current = new Uint8Array(analyser.frequencyBinCount);
    }

    // Get frequency and time domain data
    analyser.getByteFrequencyData(frequencyDataRef.current);
    analyser.getByteTimeDomainData(timeDomainDataRef.current);

    const freqData = frequencyDataRef.current;
    const binCount = freqData.length;

    // Calculate average frequency (overall volume/intensity)
    let sum = 0;
    for (let i = 0; i < binCount; i++) {
      sum += freqData[i];
    }
    const averageFrequency = sum / binCount;

    // Split into bass, mid, treble ranges
    // Bass: 0-10% of frequency bins (roughly 20-200Hz)
    // Mid: 10-50% (roughly 200Hz-2kHz)
    // Treble: 50-100% (roughly 2kHz-20kHz)
    const bassEnd = Math.floor(binCount * 0.1);
    const midEnd = Math.floor(binCount * 0.5);

    let bassSum = 0;
    for (let i = 0; i < bassEnd; i++) {
      bassSum += freqData[i];
    }
    const bass = bassSum / bassEnd;

    let midSum = 0;
    for (let i = bassEnd; i < midEnd; i++) {
      midSum += freqData[i];
    }
    const mid = midSum / (midEnd - bassEnd);

    let trebleSum = 0;
    for (let i = midEnd; i < binCount; i++) {
      trebleSum += freqData[i];
    }
    const treble = trebleSum / (binCount - midEnd);

    const newData: AudioAnalysisData = {
      frequencyData: new Uint8Array(freqData),
      timeDomainData: new Uint8Array(timeDomainDataRef.current),
      averageFrequency,
      bass: bass / 255,
      mid: mid / 255,
      treble: treble / 255,
    };

    // Update shared ref for useFrame access
    sharedAudioDataRef.current = newData;

    setData(newData);

    animationFrameRef.current = requestAnimationFrame(analyse);
  }, []);

  useEffect(() => {
    if (enabled) {
      animationFrameRef.current = requestAnimationFrame(analyse);
    }

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, [enabled, analyse]);

  return data;
}
