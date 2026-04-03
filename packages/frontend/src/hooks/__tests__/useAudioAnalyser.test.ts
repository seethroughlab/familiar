/* @vitest-environment jsdom */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../player/audio/engineInstance', () => ({
  getAudioAnalyser: () => null,
  getAudioContext: () => null,
}));

import { getAudioAnalysisDiagnosticsSnapshot, setVisualizerDebugEnabled } from '../../player/audio/analysisDiagnostics';
import { clearNativeAnalysisBuffers, setNativeAnalysisBuffers } from '../../player/audio/nativeAnalysisBuffers';
import { getAudioData, useAudioAnalyser } from '../useAudioAnalyser';

describe('useAudioAnalyser native buffer integration', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    clearNativeAnalysisBuffers();
    setVisualizerDebugEnabled(true);
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      return window.setTimeout(() => callback(performance.now()), 16);
    });
    vi.stubGlobal('cancelAnimationFrame', (id: number) => window.clearTimeout(id));
  });

  afterEach(() => {
    clearNativeAnalysisBuffers();
    setVisualizerDebugEnabled(false);
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('consumes native buffers and updates debug diagnostics', () => {
    const frequency = new Uint8Array(128).fill(12);
    for (let i = 0; i < 8; i++) frequency[i] = 220;

    const time = new Uint8Array(128).fill(128);
    for (let i = 0; i < time.length; i++) {
      time[i] = Math.round(128 + Math.sin((i / time.length) * Math.PI * 2) * 90);
    }

    renderHook(() => useAudioAnalyser(true));

    act(() => {
      setNativeAnalysisBuffers(frequency, time);
      vi.advanceTimersByTime(40);
    });

    const audioData = getAudioData();
    expect(audioData).not.toBeNull();
    expect(audioData?.frequencyData[0]).toBe(220);
    expect(audioData?.bass ?? 0).toBeGreaterThan(audioData?.treble ?? 0);

    const diagnostics = getAudioAnalysisDiagnosticsSnapshot();
    expect(diagnostics.consumer?.source).toBe('native');
    expect(diagnostics.consumer?.binCount).toBe(128);
    expect(diagnostics.consumer?.variance ?? 0).toBeGreaterThan(0);
  });
});
