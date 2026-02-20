/**
 * Tests for crossfade execution, completion, and cancellation.
 * Tests both desktop (Web Audio gain ramps) and mobile (direct volume animation) paths.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { executeCrossfade, completeCrossfade, cancelCrossfade } from '../crossfade';
import * as audioGraph from '../audioGraph';
import type { Track } from '../../../types';

// Mock platform module - default to desktop (Web Audio)
vi.mock('../platform', () => ({
  useDirectPlayback: false,
  useWebAudio: true,
  MOBILE_TRANSITION_OVERLAP: 0.3,
  log: {
    info: vi.fn(),
    debug: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

// We'll import the mocked module to toggle modes
import * as platform from '../platform';

vi.mock('../../playerStore', () => ({
  usePlayerStore: Object.assign(vi.fn(), {
    getState: () => ({ currentTrack: { id: 'track-1', title: 'Test' } }),
  }),
}));

vi.mock('../../../services/offlineService', () => ({
  revokeOfflineTrackUrl: vi.fn(),
}));

vi.mock('../../../api', () => ({
  tracksApi: {
    getStreamUrl: (id: string) => `/api/v1/tracks/${id}/stream`,
  },
}));

vi.mock('../../../services/audioEffects', () => ({
  initEffectsChain: vi.fn(() => ({
    input: { connect: vi.fn() },
    output: { connect: vi.fn() },
  })),
}));

vi.mock('../../../stores/toastStore', () => ({
  showError: vi.fn(),
}));

function createMockGainNode() {
  return {
    gain: {
      value: 1,
      setValueAtTime: vi.fn(),
      linearRampToValueAtTime: vi.fn(),
      setTargetAtTime: vi.fn(),
      cancelScheduledValues: vi.fn(),
    },
    connect: vi.fn(),
    disconnect: vi.fn(),
  } as unknown as GainNode;
}

function createMockAudioElement(): HTMLAudioElement {
  const el = new Audio() as unknown as HTMLAudioElement;
  return el;
}

const nextTrack: Track = {
  id: 'next-track-1',
  title: 'Next Track',
  artist: 'Artist',
  file_path: '/music/next.mp3',
} as Track;

describe('crossfade - Desktop (Web Audio)', () => {
  let currentGain: GainNode;
  let nextGain: GainNode;
  let currentElement: HTMLAudioElement;
  let nextElement: HTMLAudioElement;
  let setCrossfadeStateFn: ReturnType<typeof vi.fn>;
  let setNextTrackPreloadedFn: ReturnType<typeof vi.fn>;
  let advanceToNextTrackFn: ReturnType<typeof vi.fn>;
  let onCompleteFn: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();

    // Set desktop mode
    Object.defineProperty(platform, 'useDirectPlayback', { value: false, writable: true });
    Object.defineProperty(platform, 'useWebAudio', { value: true, writable: true });

    currentGain = createMockGainNode();
    nextGain = createMockGainNode();
    currentElement = createMockAudioElement();
    nextElement = createMockAudioElement();

    vi.spyOn(audioGraph, 'getCurrentElement').mockReturnValue(currentElement);
    vi.spyOn(audioGraph, 'getNextElement').mockReturnValue(nextElement);
    vi.spyOn(audioGraph, 'getCurrentGain').mockReturnValue(currentGain);
    vi.spyOn(audioGraph, 'getNextGain').mockReturnValue(nextGain);
    vi.spyOn(audioGraph, 'getGlobalAudioContext').mockReturnValue({
      currentTime: 10,
    } as unknown as AudioContext);
    vi.spyOn(audioGraph, 'getGlobalMasterGain').mockReturnValue(createMockGainNode());
    vi.spyOn(audioGraph, 'getCrossfadeContext').mockReturnValue(null);
    vi.spyOn(audioGraph, 'setCrossfadeContext').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getCurrentOfflineUrl').mockReturnValue(null);
    vi.spyOn(audioGraph, 'setCurrentOfflineUrl').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getNextOfflineUrl').mockReturnValue(null);
    vi.spyOn(audioGraph, 'setNextOfflineUrl').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getCurrentMasterVolume').mockReturnValue(1);
    vi.spyOn(audioGraph, 'toggleCurrentElement').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'setLoadedTrackId').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'setPreloadingTrackId').mockImplementation(() => {});

    vi.spyOn(audioGraph, 'cleanupElement').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'setElementVolume').mockImplementation(() => {});

    setCrossfadeStateFn = vi.fn();
    setNextTrackPreloadedFn = vi.fn();
    advanceToNextTrackFn = vi.fn();
    onCompleteFn = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('executeCrossfade schedules gain ramps with correct timing', () => {
    executeCrossfade(3, nextTrack, advanceToNextTrackFn, setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);

    // cancelScheduledValues should be called first
    expect(currentGain.gain.cancelScheduledValues).toHaveBeenCalledWith(10);
    expect(nextGain.gain.cancelScheduledValues).toHaveBeenCalledWith(10);

    // Current gain ramps from 1 to 0
    expect(currentGain.gain.setValueAtTime).toHaveBeenCalledWith(1, 10);
    expect(currentGain.gain.linearRampToValueAtTime).toHaveBeenCalledWith(0, 13); // 10 + 3

    // Next gain ramps from 0 to 1
    expect(nextGain.gain.setValueAtTime).toHaveBeenCalledWith(0, 10);
    expect(nextGain.gain.linearRampToValueAtTime).toHaveBeenCalledWith(1, 13);

    // Next element should start playing
    expect(nextElement.play).toHaveBeenCalled();

    // Track should advance
    expect(advanceToNextTrackFn).toHaveBeenCalledWith(nextTrack);
  });

  it('executeCrossfade with duration=0 does instant gain swap', () => {
    executeCrossfade(0, nextTrack, advanceToNextTrackFn, setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);

    // Instant swap: current=0, next=1
    expect(currentGain.gain.setValueAtTime).toHaveBeenCalledWith(0, 10);
    expect(nextGain.gain.setValueAtTime).toHaveBeenCalledWith(1, 10);

    // No ramps should be scheduled
    expect(currentGain.gain.linearRampToValueAtTime).not.toHaveBeenCalled();
    expect(nextGain.gain.linearRampToValueAtTime).not.toHaveBeenCalled();

    expect(nextElement.play).toHaveBeenCalled();
  });

  it('completeCrossfade cleans up old element, swaps A/B, resets state', () => {
    vi.spyOn(audioGraph, 'getCrossfadeContext').mockReturnValue({
      isActive: true,
      startTime: 10,
      duration: 3,
      timeoutId: null,
    });

    completeCrossfade(setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);

    // Old element should be cleaned up
    expect(audioGraph.cleanupElement).toHaveBeenCalledWith(currentElement, null);

    // A/B should toggle
    expect(audioGraph.toggleCurrentElement).toHaveBeenCalled();

    // State should reset
    expect(setCrossfadeStateFn).toHaveBeenCalledWith('idle');
    expect(setNextTrackPreloadedFn).toHaveBeenCalledWith(false);
    expect(onCompleteFn).toHaveBeenCalled();
  });

  it('completeCrossfade clears crossfade context timeout', () => {
    const timeoutId = setTimeout(() => {}, 10000);
    vi.spyOn(audioGraph, 'getCrossfadeContext').mockReturnValue({
      isActive: true,
      startTime: 10,
      duration: 3,
      timeoutId,
    });
    const clearTimeoutSpy = vi.spyOn(globalThis, 'clearTimeout');

    completeCrossfade(setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);

    expect(clearTimeoutSpy).toHaveBeenCalledWith(timeoutId);
    expect(audioGraph.setCrossfadeContext).toHaveBeenCalledWith(null);
  });

  it('cancelCrossfade restores gains and cleans up next element', () => {
    vi.spyOn(audioGraph, 'getCrossfadeContext').mockReturnValue({
      isActive: true,
      startTime: 10,
      duration: 3,
      timeoutId: null,
    });

    cancelCrossfade(setCrossfadeStateFn, setNextTrackPreloadedFn);

    // Gains should be restored
    expect(currentGain.gain.cancelScheduledValues).toHaveBeenCalledWith(10);
    expect(nextGain.gain.cancelScheduledValues).toHaveBeenCalledWith(10);
    expect(currentGain.gain.setValueAtTime).toHaveBeenCalledWith(1, 10);
    expect(nextGain.gain.setValueAtTime).toHaveBeenCalledWith(0, 10);

    // Next element should be cleaned up
    expect(audioGraph.cleanupElement).toHaveBeenCalledWith(nextElement, null);

    expect(setCrossfadeStateFn).toHaveBeenCalledWith('idle');
  });

  it('cancelCrossfade with no active context is a no-op', () => {
    vi.spyOn(audioGraph, 'getCrossfadeContext').mockReturnValue(null);

    cancelCrossfade(setCrossfadeStateFn, setNextTrackPreloadedFn);

    expect(currentGain.gain.cancelScheduledValues).not.toHaveBeenCalled();
    expect(audioGraph.cleanupElement).not.toHaveBeenCalled();
    expect(setCrossfadeStateFn).not.toHaveBeenCalled();
  });

  it('executeCrossfade sets crossfade context with timeout', () => {
    const setCrossfadeContextSpy = vi.spyOn(audioGraph, 'setCrossfadeContext');

    executeCrossfade(3, nextTrack, advanceToNextTrackFn, setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);

    expect(setCrossfadeContextSpy).toHaveBeenCalled();
    const ctx = setCrossfadeContextSpy.mock.calls[0][0]!;
    expect(ctx.isActive).toBe(true);
    expect(ctx.startTime).toBe(10);
    expect(ctx.duration).toBe(3);
    expect(ctx.timeoutId).toBeDefined();
  });

  it('executeCrossfade sets loadedTrackId to next track', () => {
    executeCrossfade(3, nextTrack, advanceToNextTrackFn, setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);

    expect(audioGraph.setLoadedTrackId).toHaveBeenCalledWith('next-track-1');
  });
});

describe('crossfade - Mobile (Direct Playback)', () => {
  let currentElement: HTMLAudioElement;
  let nextElement: HTMLAudioElement;
  let setCrossfadeStateFn: ReturnType<typeof vi.fn>;
  let setNextTrackPreloadedFn: ReturnType<typeof vi.fn>;
  let advanceToNextTrackFn: ReturnType<typeof vi.fn>;
  let onCompleteFn: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();

    // Set mobile mode
    Object.defineProperty(platform, 'useDirectPlayback', { value: true, writable: true });
    Object.defineProperty(platform, 'useWebAudio', { value: false, writable: true });

    currentElement = createMockAudioElement();
    nextElement = createMockAudioElement();

    vi.spyOn(audioGraph, 'getCurrentElement').mockReturnValue(currentElement);
    vi.spyOn(audioGraph, 'getNextElement').mockReturnValue(nextElement);
    vi.spyOn(audioGraph, 'getCurrentGain').mockReturnValue(null);
    vi.spyOn(audioGraph, 'getNextGain').mockReturnValue(null);
    vi.spyOn(audioGraph, 'getCrossfadeContext').mockReturnValue(null);
    vi.spyOn(audioGraph, 'setCrossfadeContext').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getCurrentOfflineUrl').mockReturnValue(null);
    vi.spyOn(audioGraph, 'setCurrentOfflineUrl').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getNextOfflineUrl').mockReturnValue(null);
    vi.spyOn(audioGraph, 'setNextOfflineUrl').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getCurrentMasterVolume').mockReturnValue(0.8);
    vi.spyOn(audioGraph, 'toggleCurrentElement').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'setLoadedTrackId').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'setPreloadingTrackId').mockImplementation(() => {});

    vi.spyOn(audioGraph, 'cleanupElement').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'setElementVolume').mockImplementation(() => {});

    setCrossfadeStateFn = vi.fn();
    setNextTrackPreloadedFn = vi.fn();
    advanceToNextTrackFn = vi.fn();
    onCompleteFn = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('executeCrossfade with short duration does instant overlap (mobile)', () => {
    executeCrossfade(0.2, nextTrack, advanceToNextTrackFn, setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);

    // Next element should play at master volume immediately
    expect(nextElement.volume).toBe(0.8);
    expect(nextElement.play).toHaveBeenCalled();

    // Should set crossfade context with timeout
    const setCrossfadeContextSpy = vi.mocked(audioGraph.setCrossfadeContext);
    expect(setCrossfadeContextSpy).toHaveBeenCalled();
    const ctx = setCrossfadeContextSpy.mock.calls[0][0]!;
    expect(ctx.isActive).toBe(true);
    expect(ctx.timeoutId).toBeDefined();
  });

  it('executeCrossfade with long duration uses rAF volume animation (mobile)', () => {
    const rafSpy = vi.spyOn(globalThis, 'requestAnimationFrame').mockReturnValue(42);

    executeCrossfade(5, nextTrack, advanceToNextTrackFn, setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);

    // Next element should start at volume 0
    expect(nextElement.volume).toBe(0);
    expect(nextElement.play).toHaveBeenCalled();

    // rAF should be called for animation
    expect(rafSpy).toHaveBeenCalled();

    // Context should have animationFrameId
    const setCrossfadeContextSpy = vi.mocked(audioGraph.setCrossfadeContext);
    const ctx = setCrossfadeContextSpy.mock.calls[0][0]!;
    expect(ctx.animationFrameId).toBe(42);
    expect(ctx.timeoutId).toBeNull();
  });

  it('completeCrossfade resets element volumes (mobile)', () => {
    vi.spyOn(audioGraph, 'getCrossfadeContext').mockReturnValue({
      isActive: true,
      startTime: 100,
      duration: 5,
      timeoutId: null,
    });

    completeCrossfade(setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);

    // After A/B swap, new current gets master volume, new next gets 0
    expect(audioGraph.setElementVolume).toHaveBeenCalled();
    expect(setCrossfadeStateFn).toHaveBeenCalledWith('idle');
    expect(onCompleteFn).toHaveBeenCalled();
  });

  it('cancelCrossfade cancels rAF and restores volumes (mobile)', () => {
    const cancelRafSpy = vi.spyOn(globalThis, 'cancelAnimationFrame');
    vi.spyOn(audioGraph, 'getCrossfadeContext').mockReturnValue({
      isActive: true,
      startTime: 100,
      duration: 5,
      timeoutId: null,
      animationFrameId: 42,
    });

    cancelCrossfade(setCrossfadeStateFn, setNextTrackPreloadedFn);

    expect(cancelRafSpy).toHaveBeenCalledWith(42);
    expect(audioGraph.setElementVolume).toHaveBeenCalledWith(currentElement, 0.8);
    expect(audioGraph.setElementVolume).toHaveBeenCalledWith(nextElement, 0);
    expect(audioGraph.cleanupElement).toHaveBeenCalledWith(nextElement, null);
  });
});
