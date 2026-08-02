import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import type { AudioEngine, AudioEngineCapabilities } from '../types';
import {
  registerEngineFactory,
  resetEngineFactoryForTesting,
  getDeclaredCapabilities,
  createEngine,
} from '../createEngine';
import {
  getEngine,
  getEngineCapabilities,
  areAudioEffectsAvailable,
  isVisualizerAvailable,
  getCurrentMode,
  getAudioAnalyser,
  getAudioContext,
  getGlobalMasterGain,
  getEngineOutputStream,
  resetEngineForTesting,
} from '../engineInstance';

/**
 * The rule these exist for: **asking what audio can do must not start audio.**
 *
 * Every capability helper used to begin with a `getEngine()` call, so a component deciding whether
 * to draw a visualizer button constructed a `WebAudioEngine` and an `AudioContext` without playing
 * anything. It went unnoticed in a browser, where an engine is wanted eventually anyway. It matters
 * for ADR-0016's embedded Mac surface, which reasons that a browse-only page constructs no second
 * engine — a conclusion that was false precisely because a question was enough to build one.
 */

const WEB_LIKE: AudioEngineCapabilities = { crossfade: true, visualizer: true, effects: 'web' };
const NATIVE_LIKE: AudioEngineCapabilities = { crossfade: true, visualizer: false, effects: 'native' };

function fakeEngine(capabilities: AudioEngineCapabilities = WEB_LIKE): AudioEngine {
  return {
    capabilities,
    initialize: () => true,
    dispose: () => {},
    load: async () => {},
    play: async () => {},
    pause: () => {},
    seek: () => {},
    stop: () => {},
    setVolume: () => {},
    setNormalizationGain: () => {},
    getCurrentTime: () => 0,
    getDuration: () => 0,
    getLoadedTrackId: () => null,
    on: () => () => {},
    updateNowPlaying: () => {},
  };
}

describe('engine capabilities', () => {
  let built: number;

  beforeEach(() => {
    resetEngineForTesting();
    resetEngineFactoryForTesting();
    built = 0;
  });

  afterEach(() => {
    resetEngineForTesting();
    resetEngineFactoryForTesting();
    vi.restoreAllMocks();
  });

  function register(capabilities: AudioEngineCapabilities = WEB_LIKE) {
    registerEngineFactory(() => {
      built += 1;
      return fakeEngine(capabilities);
    }, capabilities);
  }

  it('answers every capability question without constructing an engine', () => {
    register();

    expect(getEngineCapabilities()).toEqual(WEB_LIKE);
    expect(areAudioEffectsAvailable()).toBe(true);
    expect(isVisualizerAvailable()).toBe(true);
    expect(getCurrentMode()).toBe('webaudio');

    // The whole point. This was 1 before the split, from the first question asked.
    expect(built).toBe(0);
  });

  it('hands out no live audio nodes before anything has played, and builds nothing looking', () => {
    register();

    expect(getAudioAnalyser()).toBeNull();
    expect(getAudioContext()).toBeNull();
    expect(getGlobalMasterGain()).toBeNull();
    expect(getEngineOutputStream()).toBeNull();

    expect(built).toBe(0);
  });

  it('constructs exactly one engine, and only when playback asks for it', () => {
    register();
    expect(built).toBe(0);

    const first = getEngine();
    expect(built).toBe(1);
    expect(getEngine()).toBe(first);
    expect(built).toBe(1);
  });

  it('reports no capabilities when nothing is registered, rather than throwing', () => {
    // An embedded browse-only surface registers no engine. A capability question there has an
    // answer — "none" — while a request to play does not.
    expect(getEngineCapabilities()).toEqual({ crossfade: false, visualizer: false, effects: 'none' });
    expect(areAudioEffectsAvailable()).toBe(false);
    expect(isVisualizerAvailable()).toBe(false);
    expect(getAudioAnalyser()).toBeNull();

    expect(() => createEngine()).toThrow(/No audio engine registered/);
  });

  it('reads native effects as native mode', () => {
    register(NATIVE_LIKE);
    expect(getCurrentMode()).toBe('native');
    expect(areAudioEffectsAvailable()).toBe(true);
    expect(isVisualizerAvailable()).toBe(false);
    expect(built).toBe(0);
  });

  it('remembers what was declared', () => {
    expect(getDeclaredCapabilities()).toBeNull();
    register(NATIVE_LIKE);
    expect(getDeclaredCapabilities()).toEqual(NATIVE_LIKE);
  });

  /**
   * The cost of moving capabilities off the instance: two things now state them, and they can drift.
   * Reported rather than thrown — a mismatch is a developer error, and taking playback down for it
   * would be worse than the bug.
   */
  it('complains loudly if the declaration disagrees with the engine it describes', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    // Declares web effects, builds an engine that has none.
    registerEngineFactory(() => fakeEngine({ crossfade: true, visualizer: true, effects: 'none' }), WEB_LIKE);

    getEngine();

    expect(error).toHaveBeenCalledWith(
      expect.stringContaining('do not match'),
      expect.objectContaining({ declared: WEB_LIKE })
    );
  });

  it('stays quiet when the declaration is right', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    register();
    getEngine();
    expect(error).not.toHaveBeenCalled();
  });
});
