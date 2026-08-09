/* @vitest-environment jsdom */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../player/audio/engineInstance', () => ({
  getAudioAnalyser: () => null,
  getAudioContext: () => null,
}));

import { getAudioAnalysisDiagnosticsSnapshot, setVisualizerDebugEnabled } from '../../player/audio/analysisDiagnostics';
import { clearNativeAnalysisBuffers, setNativeAnalysisBuffers } from '../../player/audio/nativeAnalysisBuffers';
import { getAudioData, resetOnsetDetectorForTesting, useAudioAnalyser } from '../useAudioAnalyser';

describe('useAudioAnalyser native buffer integration', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    clearNativeAnalysisBuffers();
    // The detector's state is module-level and outlives a test. Without this, an onset in one test
    // sits inside the next one's refractory window and nothing can fire.
    resetOnsetDetectorForTesting();
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

  /**
   * A host that sends an onset envelope must be believed rather than second-guessed.
   *
   * This is the whole reason the envelope exists. Frames from the native app arrive at 10 Hz
   * against a 60 Hz render loop, so differencing here compares a spectrum against itself five
   * frames in six: flux reads zero, the adaptive baseline collapses, and the detector fires on
   * buffer arrivals instead of beats. The test sends an *unchanging* spectrum — under differencing
   * that is silence, so an onset can only come from the supplied envelope.
   */
  it('fires onsets from a supplied flux envelope, not from differencing', () => {
    const frequency = new Uint8Array(128).fill(40);
    const time = new Uint8Array(128).fill(128);

    renderHook(() => useAudioAnalyser(true));

    // Quiet envelope first, so the adaptive baseline has something to sit at.
    act(() => {
      for (let i = 0; i < 6; i++) {
        setNativeAnalysisBuffers(frequency, time, new Float32Array([0.001, 0.001, 0.001, 0.001]), 0.023);
        vi.advanceTimersByTime(40);
      }
    });
    expect(getAudioData()?.beat ?? 1).toBeLessThan(0.2);

    // Then a spike — with the spectrum unchanged, so differencing would still see nothing.
    act(() => {
      setNativeAnalysisBuffers(frequency, time, new Float32Array([0.001, 0.9, 0.001, 0.001]), 0.023);
      vi.advanceTimersByTime(40);
    });

    expect(getAudioData()?.beat ?? 0).toBeGreaterThan(0.5);
  });

  /**
   * And a host that sends no envelope still gets the old behaviour, so the web app and anything
   * else writing these buffers is untouched.
   */
  it('falls back to differencing when no envelope is supplied', () => {
    const quiet = new Uint8Array(128).fill(10);
    const loud = new Uint8Array(128).fill(200);
    const time = new Uint8Array(128).fill(128);

    renderHook(() => useAudioAnalyser(true));

    act(() => {
      for (let i = 0; i < 4; i++) {
        setNativeAnalysisBuffers(quiet, time);
        vi.advanceTimersByTime(40);
      }
      setNativeAnalysisBuffers(loud, time);
      vi.advanceTimersByTime(40);
    });

    expect(getAudioData()?.beat ?? 0).toBeGreaterThan(0.5);
  });
});
