/**
 * Orchestration integration tests: exercise the full state machine
 * (getCrossfadeTrigger → preload → executeCrossfade → completeCrossfade → shouldHandleEnded → playNext)
 * to assure that tracks transition continuously without double-advances.
 *
 * Uses the same vi.spyOn(audioGraph, ...) pattern as transitionPipeline.test.ts.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  executeCrossfade,
  completeCrossfade,
  cancelCrossfade,
  preloadNextTrack,
} from '../crossfade';
import {
  shouldHandleEnded,
  getErrorAction,
  getCrossfadeTrigger,
  getEffectiveCrossfadeDuration,
} from '../eventHandlers';
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

vi.mock('../../../api/client', () => ({
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

const trackA: Track = { id: 'track-a', title: 'Track A', artist: 'Artist', file_path: '/music/a.mp3' } as Track;
const trackB: Track = { id: 'track-b', title: 'Track B', artist: 'Artist', file_path: '/music/b.mp3' } as Track;
const trackC: Track = { id: 'track-c', title: 'Track C', artist: 'Artist', file_path: '/music/c.mp3' } as Track;

// ---------------------------------------------------------------------------
// Shared setup
// ---------------------------------------------------------------------------

describe('Orchestration: continuous playback scenarios', () => {
  let elementA: HTMLAudioElement;
  let elementB: HTMLAudioElement;
  let gainA: GainNode;
  let gainB: GainNode;
  let currentIsA: boolean;
  let storedCrossfadeContext: audioGraph.CrossfadeContext | null;

  // Callback spies
  let setCrossfadeState: ReturnType<typeof vi.fn>;
  let setNextTrackPreloaded: ReturnType<typeof vi.fn>;
  let advanceToNextTrack: ReturnType<typeof vi.fn>;
  let onComplete: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();

    elementA = new Audio() as unknown as HTMLAudioElement;
    elementB = new Audio() as unknown as HTMLAudioElement;
    gainA = createMockGainNode();
    gainB = createMockGainNode();
    currentIsA = true;
    storedCrossfadeContext = null;

    // Wire audioGraph spies so crossfade.ts sees our mock state
    vi.spyOn(audioGraph, 'getCurrentElement').mockImplementation(() => currentIsA ? elementA : elementB);
    vi.spyOn(audioGraph, 'getNextElement').mockImplementation(() => currentIsA ? elementB : elementA);
    vi.spyOn(audioGraph, 'getCurrentGain').mockImplementation(() => currentIsA ? gainA : gainB);
    vi.spyOn(audioGraph, 'getNextGain').mockImplementation(() => currentIsA ? gainB : gainA);
    vi.spyOn(audioGraph, 'getGlobalAudioContext').mockReturnValue({ currentTime: 0 } as unknown as AudioContext);
    vi.spyOn(audioGraph, 'getGlobalMasterGain').mockReturnValue(createMockGainNode());
    vi.spyOn(audioGraph, 'getCrossfadeContext').mockImplementation(() => storedCrossfadeContext);
    vi.spyOn(audioGraph, 'setCrossfadeContext').mockImplementation((ctx) => { storedCrossfadeContext = ctx; });
    vi.spyOn(audioGraph, 'getCurrentOfflineUrl').mockReturnValue(null);
    vi.spyOn(audioGraph, 'setCurrentOfflineUrl').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getNextOfflineUrl').mockReturnValue(null);
    vi.spyOn(audioGraph, 'setNextOfflineUrl').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getCurrentMasterVolume').mockReturnValue(1);
    vi.spyOn(audioGraph, 'toggleCurrentElement').mockImplementation(() => { currentIsA = !currentIsA; });
    vi.spyOn(audioGraph, 'setLoadedTrackId').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getPreloadingTrackId').mockReturnValue(null);
    vi.spyOn(audioGraph, 'setPreloadingTrackId').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'setEarlyPreloadedTrackId').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'cleanupElement').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'setElementVolume').mockImplementation(() => {});
    vi.spyOn(audioGraph, 'getCurrentElementIsA').mockImplementation(() => currentIsA);
    vi.spyOn(audioGraph, 'getTrackUrl').mockResolvedValue({ url: '/api/v1/tracks/next/stream', isOffline: false });
    vi.spyOn(audioGraph, 'getWebAudioElementA').mockImplementation(() => elementA);
    vi.spyOn(audioGraph, 'getWebAudioElementB').mockImplementation(() => elementB);
    vi.spyOn(audioGraph, 'getDirectElementA').mockReturnValue(null);
    vi.spyOn(audioGraph, 'getDirectElementB').mockReturnValue(null);

    setCrossfadeState = vi.fn();
    setNextTrackPreloaded = vi.fn();
    advanceToNextTrack = vi.fn();
    onComplete = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // =========================================================================
  // Scenario 1: Full continuous transition A→B, queue advances
  // =========================================================================
  it('Scenario 1: full continuous transition A→B with preload, crossfade, ended guards', async () => {
    // Track A is playing at currentTime=44, duration=60
    // crossfadeEnabled=true, crossfadeDuration=4, desktop, mobileOverlap=0.3
    // effectiveCrossfade = 4

    // Step 1: At timeRemaining=16, getCrossfadeTrigger returns 'preload'
    expect(getCrossfadeTrigger(16, true, 4, false, 0.3)).toBe('preload');

    // Step 2: Preload completes
    const preloadPromise = preloadNextTrack('track-b');
    await vi.advanceTimersByTimeAsync(0);
    // Fire canplay on the jsdom Audio element
    (elementB as unknown as { emit: (e: string) => void }).emit('canplay');
    const preloaded = await preloadPromise;
    expect(preloaded).toBe(true);

    // Step 3: Time advances to timeRemaining=3.5 → crossfade triggers
    expect(getCrossfadeTrigger(3.5, true, 4, false, 0.3)).toBe('crossfade');

    // Step 4: Execute crossfade
    const effectiveDuration = getEffectiveCrossfadeDuration(true, 4, false, 0.3);
    expect(effectiveDuration).toBe(4);
    executeCrossfade(effectiveDuration, trackB, advanceToNextTrack, setCrossfadeState, setNextTrackPreloaded, onComplete);

    expect(storedCrossfadeContext?.isActive).toBe(true);
    expect(advanceToNextTrack).toHaveBeenCalledWith(trackB);

    // Step 5: ended fires on old element A during crossfade → should NOT advance
    expect(shouldHandleEnded(
      elementA, elementA, null, false, currentIsA, true, // crossfadeActive=true
    )).toBe(false);

    // Step 6: Timer fires → completeCrossfade, A/B swap
    vi.advanceTimersByTime(4000);
    expect(currentIsA).toBe(false); // B is now current
    expect(storedCrossfadeContext).toBeNull();

    // Step 7: ended on NEW current element B → should advance (crossfade done)
    // B is not elementA, so isA=false; currentElementIsA=false → match; crossfadeActive=false
    expect(shouldHandleEnded(
      elementB, elementA, null, false, false, false,
    )).toBe(true);

    // Step 8: ended on OLD element A after swap → should NOT advance
    // A matches elementA so isA=true, but currentElementIsA=false → mismatch
    expect(shouldHandleEnded(
      elementA, elementA, null, false, false, false,
    )).toBe(false);
  });

  // =========================================================================
  // Scenario 2: Error on NEXT element during crossfade → cancel, keep playing
  // =========================================================================
  it('Scenario 2: error on next element during crossfade cancels crossfade, keeps playing', () => {
    // Elements need src for getErrorAction to not return 'ignore'
    elementA.src = 'http://localhost/track-a.mp3';
    elementB.src = 'http://localhost/track-b.mp3';

    // Start crossfade A → B
    executeCrossfade(3, trackB, advanceToNextTrack, setCrossfadeState, setNextTrackPreloaded, onComplete);
    expect(storedCrossfadeContext?.isActive).toBe(true);

    // Error fires on elementB (next, not current)
    const action = getErrorAction(elementB, elementA, true, true);
    expect(action).toBe('cancel-crossfade');

    // Cancel the crossfade
    cancelCrossfade(setCrossfadeState, setNextTrackPreloaded);
    expect(storedCrossfadeContext).toBeNull();
    expect(setCrossfadeState).toHaveBeenLastCalledWith('idle');

    // Gains restored: current (A) = 1, next (B) = 0
    expect(gainA.gain.setValueAtTime).toHaveBeenLastCalledWith(1, 0);
    expect(gainB.gain.setValueAtTime).toHaveBeenLastCalledWith(0, 0);

    // A is still current, shouldHandleEnded works normally
    expect(shouldHandleEnded(elementA, elementA, null, false, true, false)).toBe(true);
  });

  // =========================================================================
  // Scenario 3: Error on CURRENT element during crossfade → cancel + stop
  // =========================================================================
  it('Scenario 3: error on current element during crossfade cancels and stops', () => {
    // Elements need src for getErrorAction to not return 'ignore'
    elementA.src = 'http://localhost/track-a.mp3';
    elementB.src = 'http://localhost/track-b.mp3';

    // Start crossfade A → B
    executeCrossfade(3, trackB, advanceToNextTrack, setCrossfadeState, setNextTrackPreloaded, onComplete);
    expect(storedCrossfadeContext?.isActive).toBe(true);

    // Error fires on elementA (current element)
    const action = getErrorAction(elementA, elementA, true, true);
    expect(action).toBe('cancel-crossfade-and-stop');

    // Cancel crossfade
    cancelCrossfade(setCrossfadeState, setNextTrackPreloaded);
    expect(storedCrossfadeContext).toBeNull();

    // Simulate setting isPlaying=false (the hook does this)
    const isPlaying = false;

    // Verify cleanup: next element cleaned up, gains restored
    expect(audioGraph.cleanupElement).toHaveBeenCalledWith(elementB, null);
    expect(gainA.gain.setValueAtTime).toHaveBeenLastCalledWith(1, 0);

    // With isPlaying=false, even current element errors are ignored
    expect(getErrorAction(elementA, elementA, false, isPlaying)).toBe('ignore');
  });

  // =========================================================================
  // Scenario 4: Double-advance prevention (queueTransition + crossfade guards)
  // =========================================================================
  it('Scenario 4: double-advance prevention through queueTransition and crossfade guards', () => {
    // Step 1: Set queueTransition=true (as animation loop does before executeCrossfade)
    // Step 2: shouldHandleEnded returns false during queueTransition
    expect(shouldHandleEnded(elementA, elementA, null, true, true, false)).toBe(false);

    // Step 3: Start crossfade
    executeCrossfade(4, trackB, advanceToNextTrack, setCrossfadeState, setNextTrackPreloaded, onComplete);

    // Step 4: Clear queueTransition (as the 1s setTimeout does), crossfade still active
    // shouldHandleEnded still false because crossfadeActive
    expect(shouldHandleEnded(elementA, elementA, null, false, true, true)).toBe(false);

    // Step 5: completeCrossfade fires, element swaps
    vi.advanceTimersByTime(4000);
    expect(currentIsA).toBe(false); // B is now current

    // Step 6: ended on OLD element A → false (wrong element: isA=true but currentIsA=false)
    expect(shouldHandleEnded(elementA, elementA, null, false, false, false)).toBe(false);

    // Step 7: ended on NEW current element B → true (only valid advance point)
    expect(shouldHandleEnded(elementB, elementA, null, false, false, false)).toBe(true);
  });

  // =========================================================================
  // Scenario 5: Crossfade disabled → ended event is the only advancement
  // =========================================================================
  it('Scenario 5: crossfade disabled means ended event is the only track advancement', () => {
    // No crossfade trigger fires (effectiveCrossfade=0 on desktop with crossfade disabled)
    expect(getCrossfadeTrigger(0.5, false, 3, false, 0.3)).toBe('none');
    expect(getCrossfadeTrigger(2, false, 3, false, 0.3)).toBe('preload');
    expect(getCrossfadeTrigger(30, false, 3, false, 0.3)).toBe('none');

    // Track plays to natural end, shouldHandleEnded on A returns true
    expect(shouldHandleEnded(elementA, elementA, null, false, true, false)).toBe(true);
  });

  // =========================================================================
  // Scenario 6: Seek backward during crossfade cancels it
  // =========================================================================
  it('Scenario 6: seeking backward during crossfade cancels the crossfade', () => {
    // Start crossfade A → B with 4s duration
    executeCrossfade(4, trackB, advanceToNextTrack, setCrossfadeState, setNextTrackPreloaded, onComplete);
    expect(storedCrossfadeContext?.isActive).toBe(true);

    // Simulate seek check: duration=60, seekTime=10 → timeRemainingAfterSeek=50
    // effectiveCrossfade=4, 50 > 4+1=5 → should cancel
    const seekTime = 10;
    const duration = 60;
    const effectiveCrossfade = getEffectiveCrossfadeDuration(true, 4, false, 0.3);
    const shouldCancel = (duration - seekTime) > effectiveCrossfade + 1;
    expect(shouldCancel).toBe(true);

    // Cancel the crossfade (as the seek handler does)
    cancelCrossfade(setCrossfadeState, setNextTrackPreloaded);
    expect(storedCrossfadeContext).toBeNull();

    // Gains restored
    expect(gainA.gain.setValueAtTime).toHaveBeenLastCalledWith(1, 0);

    // A still current and playable
    expect(shouldHandleEnded(elementA, elementA, null, false, true, false)).toBe(true);
  });

  // =========================================================================
  // Scenario 7: Consecutive transitions A→B→A
  // =========================================================================
  it('Scenario 7: consecutive transitions A→B→A alternate elements correctly', () => {
    // --- First crossfade: A → B ---
    expect(currentIsA).toBe(true);
    executeCrossfade(2, trackB, advanceToNextTrack, setCrossfadeState, setNextTrackPreloaded, onComplete);

    // Gains: A ramps to 0, B ramps to 1
    expect(gainA.gain.linearRampToValueAtTime).toHaveBeenCalledWith(0, 2);
    expect(gainB.gain.linearRampToValueAtTime).toHaveBeenCalledWith(1, 2);

    vi.advanceTimersByTime(2000);
    expect(currentIsA).toBe(false); // B is now current
    expect(storedCrossfadeContext).toBeNull();
    expect(onComplete).toHaveBeenCalledTimes(1);

    // ended on B (new current) should be handled; ended on A (old) should not
    expect(shouldHandleEnded(elementB, elementA, null, false, false, false)).toBe(true);
    expect(shouldHandleEnded(elementA, elementA, null, false, false, false)).toBe(false);

    // --- Second crossfade: B → A (track C loaded into A) ---
    // Reset gain mocks to track second crossfade clearly
    vi.mocked(gainA.gain.linearRampToValueAtTime).mockClear();
    vi.mocked(gainB.gain.linearRampToValueAtTime).mockClear();
    vi.mocked(gainA.gain.setValueAtTime).mockClear();
    vi.mocked(gainB.gain.setValueAtTime).mockClear();

    executeCrossfade(2, trackC, advanceToNextTrack, setCrossfadeState, setNextTrackPreloaded, onComplete);

    // Now B is current (ramps down), A is next (ramps up)
    expect(gainB.gain.linearRampToValueAtTime).toHaveBeenCalledWith(0, 2);
    expect(gainA.gain.linearRampToValueAtTime).toHaveBeenCalledWith(1, 2);

    vi.advanceTimersByTime(2000);
    expect(currentIsA).toBe(true); // A is current again
    expect(storedCrossfadeContext).toBeNull();
    expect(onComplete).toHaveBeenCalledTimes(2);

    // ended on A (new current) should be handled; ended on B (old) should not
    expect(shouldHandleEnded(elementA, elementA, null, false, true, false)).toBe(true);
    expect(shouldHandleEnded(elementB, elementA, null, false, true, false)).toBe(false);
  });
});
