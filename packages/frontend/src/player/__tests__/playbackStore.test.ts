/**
 * Tests for playbackStore — pure playback state (no queue interactions).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { usePlaybackStore } from '../playbackStore';

vi.mock('../persistence', () => ({
  debouncedSavePlayerState: vi.fn(),
}));

describe('playbackStore', () => {
  beforeEach(() => {
    usePlaybackStore.setState({
      currentTrack: null,
      isPlaying: false,
      currentTime: 0,
      duration: 0,
      volume: 1,
      shuffle: false,
      repeat: 'off',
      consume: false,
      crossfadeState: 'idle',
      nextTrackPreloaded: false,
      isLoadingAudio: false,
      isHydrated: true,
      _circuitBreakerTimestamps: [],
    });
  });

  describe('volume control', () => {
    it('should set volume within bounds', () => {
      usePlaybackStore.getState().setVolume(0.5);
      expect(usePlaybackStore.getState().volume).toBe(0.5);
    });

    it('should clamp volume at minimum 0', () => {
      usePlaybackStore.getState().setVolume(-0.5);
      expect(usePlaybackStore.getState().volume).toBe(0);
    });

    it('should clamp volume at maximum 1', () => {
      usePlaybackStore.getState().setVolume(1.5);
      expect(usePlaybackStore.getState().volume).toBe(1);
    });
  });

  describe('toggleRepeat', () => {
    it('should cycle off -> all -> one -> off', () => {
      const { toggleRepeat } = usePlaybackStore.getState();

      expect(usePlaybackStore.getState().repeat).toBe('off');

      toggleRepeat();
      expect(usePlaybackStore.getState().repeat).toBe('all');

      toggleRepeat();
      expect(usePlaybackStore.getState().repeat).toBe('one');

      toggleRepeat();
      expect(usePlaybackStore.getState().repeat).toBe('off');
    });
  });

  describe('toggleConsume', () => {
    it('should toggle consume mode', () => {
      expect(usePlaybackStore.getState().consume).toBe(false);
      usePlaybackStore.getState().toggleConsume();
      expect(usePlaybackStore.getState().consume).toBe(true);
      usePlaybackStore.getState().toggleConsume();
      expect(usePlaybackStore.getState().consume).toBe(false);
    });
  });

  describe('crossfade', () => {
    it('should manage crossfade state', () => {
      const { setCrossfadeState } = usePlaybackStore.getState();

      setCrossfadeState('preloading');
      expect(usePlaybackStore.getState().crossfadeState).toBe('preloading');

      setCrossfadeState('crossfading');
      expect(usePlaybackStore.getState().crossfadeState).toBe('crossfading');

      setCrossfadeState('idle');
      expect(usePlaybackStore.getState().crossfadeState).toBe('idle');
    });

    it('should manage next track preloaded state', () => {
      const { setNextTrackPreloaded } = usePlaybackStore.getState();

      setNextTrackPreloaded(true);
      expect(usePlaybackStore.getState().nextTrackPreloaded).toBe(true);

      setNextTrackPreloaded(false);
      expect(usePlaybackStore.getState().nextTrackPreloaded).toBe(false);
    });
  });

  describe('audio loading', () => {
    it('should track loading state', () => {
      const { setIsLoadingAudio } = usePlaybackStore.getState();

      setIsLoadingAudio(true);
      expect(usePlaybackStore.getState().isLoadingAudio).toBe(true);

      setIsLoadingAudio(false);
      expect(usePlaybackStore.getState().isLoadingAudio).toBe(false);
    });
  });

  describe('circuit breaker', () => {
    it('should allow advances within threshold', () => {
      const { registerFailureAdvance } = usePlaybackStore.getState();
      for (let i = 0; i < 8; i++) {
        expect(registerFailureAdvance()).toBe(true);
      }
    });

    it('should trip after exceeding threshold', () => {
      const { registerFailureAdvance } = usePlaybackStore.getState();
      for (let i = 0; i < 8; i++) {
        registerFailureAdvance();
      }
      expect(registerFailureAdvance()).toBe(false);
    });

    it('should recover after window expires', () => {
      const now = Date.now();
      // Seed with old timestamps outside the window
      usePlaybackStore.setState({
        _circuitBreakerTimestamps: Array(8).fill(now - 20000),
      });
      expect(usePlaybackStore.getState().registerFailureAdvance()).toBe(true);
    });
  });
});
