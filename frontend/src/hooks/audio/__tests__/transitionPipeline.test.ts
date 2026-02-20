/**
 * Tests for the full transition pipeline: preload -> crossfade -> complete -> A/B swap.
 * Also tests double-advance prevention and crossfade cancellation.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  executeCrossfade,
  completeCrossfade,
  cancelCrossfade,
  preloadNextTrack,
} from '../crossfade';
import * as audioGraph from '../audioGraph';
import type { Track } from '../../../types';

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

vi.mock('../../../stores/playerStore', () => ({
  usePlayerStore: Object.assign(vi.fn(), {
    getState: () => ({ currentTrack: { id: 'current-1', title: 'Current' } }),
  }),
}));

vi.mock('../../../services/offlineService', () => ({
  getOfflineTrack: vi.fn(() => Promise.resolve(null)),
  createOfflineTrackUrl: vi.fn(),
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

const nextTrack: Track = {
  id: 'next-1',
  title: 'Next Track',
  artist: 'Artist',
  file_path: '/music/next.mp3',
} as Track;

describe('Transition Pipeline', () => {
  let elementA: HTMLAudioElement;
  let elementB: HTMLAudioElement;
  let gainA: GainNode;
  let gainB: GainNode;
  let currentIsA: boolean;
  let setCrossfadeStateFn: ReturnType<typeof vi.fn>;
  let setNextTrackPreloadedFn: ReturnType<typeof vi.fn>;
  let advanceToNextTrackFn: ReturnType<typeof vi.fn>;
  let onCompleteFn: ReturnType<typeof vi.fn>;

  // Track the stored crossfade context
  let storedCrossfadeContext: audioGraph.CrossfadeContext | null;

  beforeEach(() => {
    vi.useFakeTimers();

    elementA = new Audio() as unknown as HTMLAudioElement;
    elementB = new Audio() as unknown as HTMLAudioElement;
    gainA = createMockGainNode();
    gainB = createMockGainNode();
    currentIsA = true;
    storedCrossfadeContext = null;

    vi.spyOn(audioGraph, 'getCurrentElement').mockImplementation(() =>
      currentIsA ? elementA : elementB
    );
    vi.spyOn(audioGraph, 'getNextElement').mockImplementation(() =>
      currentIsA ? elementB : elementA
    );
    vi.spyOn(audioGraph, 'getCurrentGain').mockImplementation(() =>
      currentIsA ? gainA : gainB
    );
    vi.spyOn(audioGraph, 'getNextGain').mockImplementation(() =>
      currentIsA ? gainB : gainA
    );
    vi.spyOn(audioGraph, 'getGlobalAudioContext').mockReturnValue({
      currentTime: 0,
    } as unknown as AudioContext);
    vi.spyOn(audioGraph, 'getGlobalMasterGain').mockReturnValue(createMockGainNode());
    vi.spyOn(audioGraph, 'getCrossfadeContext').mockImplementation(() => storedCrossfadeContext);
    vi.spyOn(audioGraph, 'setCrossfadeContext').mockImplementation((ctx) => {
      storedCrossfadeContext = ctx;
    });
    vi.spyOn(audioGraph, 'getCurrentOfflineUrl').mockReturnValue(null);
    vi.spyOn(audioGraph, 'setCurrentOfflineUrl').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getNextOfflineUrl').mockReturnValue(null);
    vi.spyOn(audioGraph, 'setNextOfflineUrl').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getCurrentMasterVolume').mockReturnValue(1);
    vi.spyOn(audioGraph, 'toggleCurrentElement').mockImplementation(() => {
      currentIsA = !currentIsA;
    });
    vi.spyOn(audioGraph, 'setLoadedTrackId').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getPreloadingTrackId').mockReturnValue(null);
    vi.spyOn(audioGraph, 'setPreloadingTrackId').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'cleanupElement').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'setElementVolume').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getTrackUrl').mockResolvedValue({
      url: '/api/v1/tracks/next-1/stream',
      isOffline: false,
    });
    vi.spyOn(audioGraph, 'getCurrentElementIsA').mockImplementation(() => currentIsA);

    setCrossfadeStateFn = vi.fn();
    setNextTrackPreloadedFn = vi.fn();
    advanceToNextTrackFn = vi.fn();
    onCompleteFn = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('full pipeline: preload -> crossfade -> timer -> complete -> A/B swapped', async () => {
    // Step 1: Preload
    const preloadPromise = preloadNextTrack('next-1');
    // Flush the await getTrackUrl() microtask
    await vi.advanceTimersByTimeAsync(0);
    (elementB as unknown as { emit: (e: string) => void }).emit('canplay');
    const preloaded = await preloadPromise;
    expect(preloaded).toBe(true);

    // Step 2: Execute crossfade (A -> B)
    expect(currentIsA).toBe(true);
    executeCrossfade(3, nextTrack, advanceToNextTrackFn, setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);

    // Gain ramps should target gainA (current) and gainB (next)
    expect(gainA.gain.linearRampToValueAtTime).toHaveBeenCalledWith(0, 3);
    expect(gainB.gain.linearRampToValueAtTime).toHaveBeenCalledWith(1, 3);

    // advanceToNextTrack should be called
    expect(advanceToNextTrackFn).toHaveBeenCalledWith(nextTrack);

    // Step 3: Timer fires -> completeCrossfade
    expect(storedCrossfadeContext).not.toBeNull();
    vi.advanceTimersByTime(3000);

    // After complete, A/B should be swapped (B is now current)
    expect(currentIsA).toBe(false);
    expect(setCrossfadeStateFn).toHaveBeenCalledWith('idle');
    expect(onCompleteFn).toHaveBeenCalled();
  });

  it('double-advance: queueTransition flag blocks ended->playNext', () => {
    // This test validates the pattern used in the animation loop:
    // queueTransition is set true before executeCrossfade, preventing handleEnded from calling playNext

    audioGraph.setQueueTransition(true);
    expect(audioGraph.getQueueTransition()).toBe(true);

    // Simulate: crossfade starts, then ended fires on old element
    // The hook's handleEnded checks queueTransition - we verify it's set
    // (The actual handleEnded logic lives in the hook's useEffect, tested via integration)

    audioGraph.setQueueTransition(false);
    expect(audioGraph.getQueueTransition()).toBe(false);
  });

  it('crossfade cancellation leaves clean state for subsequent operations', () => {
    // Start a crossfade
    executeCrossfade(3, nextTrack, advanceToNextTrackFn, setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);
    expect(storedCrossfadeContext?.isActive).toBe(true);

    // Cancel it
    cancelCrossfade(setCrossfadeStateFn, setNextTrackPreloadedFn);

    // Context should be null
    expect(storedCrossfadeContext).toBeNull();

    // Gains should be restored
    expect(gainA.gain.setValueAtTime).toHaveBeenLastCalledWith(1, 0);
    expect(gainB.gain.setValueAtTime).toHaveBeenLastCalledWith(0, 0);

    // State should be idle
    expect(setCrossfadeStateFn).toHaveBeenLastCalledWith('idle');

    // Next element should be cleaned up
    expect(audioGraph.cleanupElement).toHaveBeenCalledWith(elementB, null);
  });

  it('two consecutive crossfades alternate elements correctly (A->B->A)', async () => {
    // First crossfade: A -> B
    expect(currentIsA).toBe(true);

    executeCrossfade(1, nextTrack, advanceToNextTrackFn, setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);
    vi.advanceTimersByTime(1000);

    // After completion, B is current
    expect(currentIsA).toBe(false);

    // Second crossfade: B -> A
    const secondTrack = { ...nextTrack, id: 'next-2' } as Track;
    vi.spyOn(audioGraph, 'getTrackUrl').mockResolvedValue({
      url: '/api/v1/tracks/next-2/stream',
      isOffline: false,
    });

    executeCrossfade(1, secondTrack, advanceToNextTrackFn, setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);

    // Now gainB is current (should ramp down), gainA is next (should ramp up)
    // The last call to linearRampToValueAtTime on gainB should be 0
    // and on gainA should be 1
    const gainBRampCalls = vi.mocked(gainB.gain.linearRampToValueAtTime).mock.calls;
    const gainARampCalls = vi.mocked(gainA.gain.linearRampToValueAtTime).mock.calls;

    // gainB was next in first crossfade (ramped to 1), now current (should ramp to 0)
    expect(gainBRampCalls[gainBRampCalls.length - 1][0]).toBe(0);
    // gainA was current in first crossfade (ramped to 0), now next (should ramp to 1)
    expect(gainARampCalls[gainARampCalls.length - 1][0]).toBe(1);

    vi.advanceTimersByTime(1000);

    // After second completion, A is current again
    expect(currentIsA).toBe(true);
  });

  it('completeCrossfade is idempotent: second call is a no-op', () => {
    // Start a crossfade A -> B
    executeCrossfade(2, nextTrack, advanceToNextTrackFn, setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);
    expect(storedCrossfadeContext?.isActive).toBe(true);
    expect(currentIsA).toBe(true);

    // Complete the crossfade (swaps to B)
    vi.advanceTimersByTime(2000);
    expect(currentIsA).toBe(false);
    expect(storedCrossfadeContext).toBeNull();
    expect(onCompleteFn).toHaveBeenCalledTimes(1);

    // Reset mocks to track second call
    vi.mocked(audioGraph.cleanupElement).mockClear();
    vi.mocked(audioGraph.toggleCurrentElement).mockClear();
    setCrossfadeStateFn.mockClear();
    onCompleteFn.mockClear();

    // Second call should be a no-op (context is null)
    completeCrossfade(setCrossfadeStateFn, setNextTrackPreloadedFn, onCompleteFn);

    // Nothing should have changed
    expect(currentIsA).toBe(false); // NOT toggled back to true
    expect(audioGraph.cleanupElement).not.toHaveBeenCalled();
    expect(audioGraph.toggleCurrentElement).not.toHaveBeenCalled();
    expect(setCrossfadeStateFn).not.toHaveBeenCalled();
    expect(onCompleteFn).not.toHaveBeenCalled();
  });
});
