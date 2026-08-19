/**
 * Tests for queueStore — queue state + cross-cutting actions.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { createMockTrack, mockConnectivityState } from './testHelpers';

// Mocks must be at top level
vi.mock('../persistence', () => ({
  debouncedSavePlayerState: vi.fn(),
  loadPlayerState: vi.fn(() => Promise.resolve(null)),
  fetchTracksBatched: vi.fn(() => Promise.resolve([])),
  migrateOldPlayerState: vi.fn(() => Promise.resolve()),
}));

const mockSeek = vi.fn();
vi.mock('../audio/engineInstance', () => ({
  getEngine: () => ({ seek: mockSeek, cancelCrossfade: vi.fn() }),
}));

vi.mock('../../stores/connectivityStore', () => ({
  useConnectivityStore: Object.assign(
    (selector: (state: typeof mockConnectivityState) => unknown) => selector(mockConnectivityState),
    { getState: () => mockConnectivityState }
  ),
}));

// Import stores after mocks
import { useQueueStore } from '../queueStore';
import { usePlaybackStore } from '../playbackStore';

function resetStores() {
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
  useQueueStore.setState({
    queue: [],
    queueIndex: -1,
    history: [],
    shuffleOrder: [],
    shuffleIndex: -1,
    lazyQueueIds: null,
    lazyQueueIndex: -1,
    queueSource: null,
    isQueueHydrating: false,
  });
  mockConnectivityState.offlineModeActive = false;
  mockConnectivityState.offlineTrackIds = new Set<string>();
  mockSeek.mockClear();
}

describe('queueStore', () => {
  beforeEach(resetStores);

  describe('setQueue', () => {
    it('should set queue and start playing first track', () => {
      const track1 = createMockTrack('1', 'First');
      const track2 = createMockTrack('2', 'Second');

      useQueueStore.getState().setQueue([track1, track2], 0);

      expect(useQueueStore.getState().queue).toHaveLength(2);
      expect(useQueueStore.getState().queueIndex).toBe(0);
      expect(usePlaybackStore.getState().currentTrack?.id).toBe('1');
      expect(usePlaybackStore.getState().isPlaying).toBe(true);
    });

    it('should start at specified index', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2'), createMockTrack('3')];
      useQueueStore.getState().setQueue(tracks, 1);

      expect(useQueueStore.getState().queueIndex).toBe(1);
      expect(usePlaybackStore.getState().currentTrack?.id).toBe('2');
    });

    it('should generate shuffle order when shuffle is enabled', () => {
      usePlaybackStore.setState({ shuffle: true });
      const tracks = [createMockTrack('1'), createMockTrack('2'), createMockTrack('3')];
      useQueueStore.getState().setQueue(tracks, 0);

      expect(useQueueStore.getState().shuffleOrder).toHaveLength(3);
      expect(useQueueStore.getState().shuffleIndex).toBe(0);
    });

    it('should resolve queue start by track id', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2'), createMockTrack('3')];
      useQueueStore.getState().setQueueByTrackId(tracks, '2');

      expect(useQueueStore.getState().queueIndex).toBe(1);
      expect(usePlaybackStore.getState().currentTrack?.id).toBe('2');
    });

    it('should ignore queue updates when track id is missing', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2')];
      useQueueStore.getState().setQueueByTrackId(tracks, 'missing-track-id');

      expect(useQueueStore.getState().queueIndex).toBe(-1);
      expect(usePlaybackStore.getState().currentTrack).toBeNull();
    });



    it('should track queue source', () => {
      useQueueStore.getState().setQueue([createMockTrack('1')], 0, { type: 'playlist', id: 'playlist-123' });
      expect(useQueueStore.getState().queueSource).toEqual({ type: 'playlist', id: 'playlist-123' });
    });

    it('should clear queue source when none provided', () => {
      useQueueStore.getState().setQueue([createMockTrack('1')], 0, { type: 'album', id: 'album-1' });
      useQueueStore.getState().setQueue([createMockTrack('1')], 0);
      expect(useQueueStore.getState().queueSource).toBeNull();
    });

    it('should exit lazy mode when setting regular queue', () => {
      useQueueStore.setState({ lazyQueueIds: ['a', 'b', 'c'], lazyQueueIndex: 1 });
      useQueueStore.getState().setQueue([createMockTrack('1')], 0);

      expect(useQueueStore.getState().lazyQueueIds).toBeNull();
      expect(useQueueStore.getState().lazyQueueIndex).toBe(-1);
    });
  });

  describe('addToQueue', () => {
    it('should add track to end of queue', () => {
      useQueueStore.getState().setQueue([createMockTrack('1')], 0);
      useQueueStore.getState().addToQueue(createMockTrack('2'));

      expect(useQueueStore.getState().queue).toHaveLength(2);
      expect(useQueueStore.getState().queue[1].track.id).toBe('2');
    });

    it('should update shuffle order when shuffle is on', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 0);
      useQueueStore.getState().toggleShuffle();

      expect(usePlaybackStore.getState().shuffle).toBe(true);
      expect(useQueueStore.getState().shuffleOrder).toHaveLength(2);

      useQueueStore.getState().addToQueue(createMockTrack('3'));

      const { shuffleOrder } = useQueueStore.getState();
      expect(shuffleOrder).toHaveLength(3);
      expect(shuffleOrder).toContain(2);
    });


    it('allows downloaded tracks to be added while offline mode is active', () => {
      mockConnectivityState.offlineModeActive = true;
      mockConnectivityState.offlineTrackIds = new Set(['1', '2']);

      useQueueStore.getState().setQueue([createMockTrack('1')], 0);
      useQueueStore.getState().addToQueue(createMockTrack('2'));

      expect(useQueueStore.getState().queue).toHaveLength(2);
    });

    it('should insert track at specific position', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('3')], 0);
      useQueueStore.getState().addToQueue(createMockTrack('2'), 1);

      expect(useQueueStore.getState().queue).toHaveLength(3);
      expect(useQueueStore.getState().queue[1].track.id).toBe('2');
    });

    it('should adjust queueIndex when inserting before current track', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 1);
      useQueueStore.getState().addToQueue(createMockTrack('0'), 0);

      expect(useQueueStore.getState().queueIndex).toBe(2);
    });

    it('should not adjust queueIndex when inserting after current track', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 0);
      useQueueStore.getState().addToQueue(createMockTrack('3'), 2);

      expect(useQueueStore.getState().queueIndex).toBe(0);
    });
  });

  describe('removeFromQueue', () => {
    it('should remove track by queueId', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2'), createMockTrack('3')], 0);

      const queueId = useQueueStore.getState().queue[1].queueId;
      useQueueStore.getState().removeFromQueue(queueId);

      expect(useQueueStore.getState().queue).toHaveLength(2);
      expect(useQueueStore.getState().queue.find(q => q.track.id === '2')).toBeUndefined();
    });

    it('should not remove anything for unknown queueId', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 0);
      useQueueStore.getState().removeFromQueue('nonexistent-id');

      expect(useQueueStore.getState().queue).toHaveLength(2);
    });
  });

  describe('clearQueue', () => {
    it('should clear queue and reset index', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 0);
      useQueueStore.getState().clearQueue();

      expect(useQueueStore.getState().queue).toEqual([]);
      expect(useQueueStore.getState().queueIndex).toBe(-1);
    });

    it('should clear lazy state when in lazy mode', () => {
      useQueueStore.setState({
        lazyQueueIds: ['a', 'b', 'c', 'd', 'e'],
        lazyQueueIndex: 2,
        queue: [{ track: createMockTrack('a'), queueId: 'q1' }],
        queueIndex: 0,
        queueSource: { type: 'library' },
      });

      useQueueStore.getState().clearQueue();

      expect(useQueueStore.getState().queue).toEqual([]);
      expect(useQueueStore.getState().queueIndex).toBe(-1);
      expect(useQueueStore.getState().lazyQueueIds).toBeNull();
      expect(useQueueStore.getState().lazyQueueIndex).toBe(-1);
      expect(useQueueStore.getState().queueSource).toBeNull();
    });
  });

  describe('playTrack', () => {
    it('should set current track and start playing', () => {
      useQueueStore.getState().playTrack(createMockTrack('1'));

      expect(usePlaybackStore.getState().currentTrack?.id).toBe('1');
      expect(usePlaybackStore.getState().isPlaying).toBe(true);
      expect(usePlaybackStore.getState().currentTime).toBe(0);
    });

    it('should add previous track to history', () => {
      useQueueStore.getState().playTrack(createMockTrack('1'));
      useQueueStore.getState().playTrack(createMockTrack('2'));

      expect(useQueueStore.getState().history).toHaveLength(1);
      expect(useQueueStore.getState().history[0].id).toBe('1');
    });
  });

  describe('playNext', () => {
    it('should advance to next track in sequential mode', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2'), createMockTrack('3')], 0);
      useQueueStore.getState().playNext();

      expect(useQueueStore.getState().queueIndex).toBe(1);
      expect(usePlaybackStore.getState().currentTrack?.id).toBe('2');
    });

    it('should stop playing at end of queue without repeat', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 1);
      useQueueStore.getState().playNext();

      expect(usePlaybackStore.getState().isPlaying).toBe(false);
    });

    it('should wrap to start with repeat all', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 1);
      usePlaybackStore.getState().toggleRepeat(); // 'all'
      useQueueStore.getState().playNext();

      expect(useQueueStore.getState().queueIndex).toBe(0);
      expect(usePlaybackStore.getState().currentTrack?.id).toBe('1');
      expect(usePlaybackStore.getState().isPlaying).toBe(true);
    });

    it('should add current track to history', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 0);
      useQueueStore.getState().playNext();

      expect(useQueueStore.getState().history).toHaveLength(1);
      expect(useQueueStore.getState().history[0].id).toBe('1');
    });

    it('should follow shuffle order when shuffle is on', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2'), createMockTrack('3')], 0);
      useQueueStore.getState().toggleShuffle();

      const { shuffleOrder } = useQueueStore.getState();
      useQueueStore.getState().playNext();

      expect(useQueueStore.getState().queueIndex).toBe(shuffleOrder[1]);
      expect(useQueueStore.getState().shuffleIndex).toBe(1);
    });

    it('should stop playing when queue is empty', () => {
      usePlaybackStore.setState({ isPlaying: true });
      useQueueStore.getState().playNext();

      expect(usePlaybackStore.getState().isPlaying).toBe(false);
    });

    it('should reshuffle when reaching end of shuffle order with repeat all', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2'), createMockTrack('3')], 0);
      useQueueStore.getState().toggleShuffle();
      usePlaybackStore.getState().toggleRepeat(); // 'all'

      const { shuffleOrder } = useQueueStore.getState();
      for (let i = 0; i < shuffleOrder.length; i++) {
        useQueueStore.getState().playNext();
      }

      expect(usePlaybackStore.getState().isPlaying).toBe(true);
      expect(useQueueStore.getState().shuffleIndex).toBe(0);
    });
  });

  describe('playPrevious', () => {
    it('should restart track if more than 3 seconds in', () => {
      useQueueStore.getState().setQueue([createMockTrack('1')], 0);
      usePlaybackStore.setState({ currentTime: 5 });

      useQueueStore.getState().playPrevious();

      expect(usePlaybackStore.getState().currentTime).toBe(0);
      expect(usePlaybackStore.getState().currentTrack?.id).toBe('1');
    });

    it('should go to previous track from history', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 0);
      useQueueStore.getState().playNext();

      usePlaybackStore.setState({ currentTime: 0 });
      useQueueStore.getState().playPrevious();

      expect(usePlaybackStore.getState().currentTrack?.id).toBe('1');
      expect(useQueueStore.getState().history).toHaveLength(0);
    });

    it('back in shuffle with > 3 seconds restarts current track', () => {
      const track3 = createMockTrack('3');
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2'), track3], 0);

      usePlaybackStore.setState({
        shuffle: true,
        currentTrack: track3,
        currentTime: 30,
      });
      useQueueStore.setState({
        shuffleOrder: [0, 2, 1],
        shuffleIndex: 1,
        queueIndex: 2,
      });

      useQueueStore.getState().playPrevious();

      expect(usePlaybackStore.getState().currentTrack?.id).toBe('3');
      expect(useQueueStore.getState().shuffleIndex).toBe(1);
      expect(usePlaybackStore.getState().currentTime).toBe(0);
      // engine.seek(0) is called but verified via the original playerStore facade tests
    });

    it('back in shuffle with <= 3 seconds navigates to previous shuffle order track', () => {
      const track3 = createMockTrack('3');
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2'), track3], 0);

      usePlaybackStore.setState({
        shuffle: true,
        currentTrack: track3,
        currentTime: 1,
      });
      useQueueStore.setState({
        shuffleOrder: [0, 2, 1],
        shuffleIndex: 1,
        queueIndex: 2,
      });

      useQueueStore.getState().playPrevious();

      expect(usePlaybackStore.getState().currentTrack?.id).toBe('1');
      expect(useQueueStore.getState().shuffleIndex).toBe(0);
      expect(useQueueStore.getState().queueIndex).toBe(0);
    });

    it('back then forward in shuffle replays the same next track', () => {
      const track3 = createMockTrack('3');
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2'), track3], 0);

      usePlaybackStore.setState({
        shuffle: true,
        currentTrack: track3,
        currentTime: 0,
      });
      useQueueStore.setState({
        shuffleOrder: [0, 2, 1],
        shuffleIndex: 1,
        queueIndex: 2,
      });

      useQueueStore.getState().playPrevious();
      expect(usePlaybackStore.getState().currentTrack?.id).toBe('1');
      expect(useQueueStore.getState().shuffleIndex).toBe(0);

      useQueueStore.getState().playNext();
      expect(usePlaybackStore.getState().currentTrack?.id).toBe('3');
      expect(useQueueStore.getState().shuffleIndex).toBe(1);
    });
  });

  describe('toggleShuffle', () => {
    it('should enable shuffle and generate shuffle order', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2'), createMockTrack('3')], 0);
      useQueueStore.getState().toggleShuffle();

      expect(usePlaybackStore.getState().shuffle).toBe(true);
      expect(useQueueStore.getState().shuffleOrder).toHaveLength(3);
      expect(useQueueStore.getState().shuffleIndex).toBe(0);
      expect(useQueueStore.getState().shuffleOrder[0]).toBe(0);
    });

    it('should disable shuffle and clear shuffle state', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 0);
      useQueueStore.getState().toggleShuffle();
      useQueueStore.getState().toggleShuffle();

      expect(usePlaybackStore.getState().shuffle).toBe(false);
      expect(useQueueStore.getState().shuffleOrder).toEqual([]);
      expect(useQueueStore.getState().shuffleIndex).toBe(-1);
    });

    it('should enable shuffle even with empty queue', () => {
      useQueueStore.getState().toggleShuffle();

      expect(usePlaybackStore.getState().shuffle).toBe(true);
      expect(useQueueStore.getState().shuffleOrder).toEqual([]);
      expect(useQueueStore.getState().shuffleIndex).toBe(-1);
    });

    it('should enable shuffle with single track in queue', () => {
      useQueueStore.getState().setQueue([createMockTrack('1')], 0);
      useQueueStore.getState().toggleShuffle();

      expect(usePlaybackStore.getState().shuffle).toBe(true);
      expect(useQueueStore.getState().shuffleOrder).toEqual([]);
      expect(useQueueStore.getState().shuffleIndex).toBe(-1);
    });

    it('should include all tracks in shuffle order', () => {
      const tracks = Array.from({ length: 10 }, (_, i) => createMockTrack(`${i}`, `Track ${i}`));
      useQueueStore.getState().setQueue(tracks, 0);
      useQueueStore.getState().toggleShuffle();

      const sortedOrder = [...useQueueStore.getState().shuffleOrder].sort((a, b) => a - b);
      expect(sortedOrder).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
    });
  });

  describe('reorderQueue', () => {
    it('should move track from one position to another', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2'), createMockTrack('3')], 0);
      useQueueStore.getState().reorderQueue(0, 2);

      const { queue } = useQueueStore.getState();
      expect(queue[0].track.id).toBe('2');
      expect(queue[1].track.id).toBe('3');
      expect(queue[2].track.id).toBe('1');
    });

    it('should update queueIndex to keep current track selected', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2'), createMockTrack('3')], 0);
      useQueueStore.getState().reorderQueue(0, 2);

      expect(useQueueStore.getState().queueIndex).toBe(2);
      expect(usePlaybackStore.getState().currentTrack?.id).toBe('1');
    });

    it('should ignore out-of-bounds indices', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 0);

      useQueueStore.getState().reorderQueue(-1, 0);
      expect(useQueueStore.getState().queue[0].track.id).toBe('1');

      useQueueStore.getState().reorderQueue(0, 5);
      expect(useQueueStore.getState().queue[0].track.id).toBe('1');
    });
  });

  describe('jumpToQueueIndex', () => {
    it('should jump to specified queue index', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2'), createMockTrack('3')], 0);
      useQueueStore.getState().jumpToQueueIndex(2);

      expect(useQueueStore.getState().queueIndex).toBe(2);
      expect(usePlaybackStore.getState().currentTrack?.id).toBe('3');
      expect(usePlaybackStore.getState().isPlaying).toBe(true);
      expect(usePlaybackStore.getState().currentTime).toBe(0);
    });

    it('should add current track to history', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 0);
      useQueueStore.getState().jumpToQueueIndex(1);

      expect(useQueueStore.getState().history).toHaveLength(1);
      expect(useQueueStore.getState().history[0].id).toBe('1');
    });

    it('should ignore out-of-bounds index', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 0);
      useQueueStore.getState().jumpToQueueIndex(5);

      expect(useQueueStore.getState().queueIndex).toBe(0);
    });

    it('should ignore negative index', () => {
      useQueueStore.getState().setQueue([createMockTrack('1')], 0);
      useQueueStore.getState().jumpToQueueIndex(-1);

      expect(useQueueStore.getState().queueIndex).toBe(0);
    });
  });

  describe('getNextTrack', () => {
    it('should return next track in sequential mode', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 0);
      expect(useQueueStore.getState().getNextTrack()?.id).toBe('2');
    });

    it('should return null at end without repeat', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 1);
      expect(useQueueStore.getState().getNextTrack()).toBeNull();
    });

    it('should return first track at end with repeat all', () => {
      useQueueStore.getState().setQueue([createMockTrack('1'), createMockTrack('2')], 1);
      usePlaybackStore.getState().toggleRepeat(); // 'all'
      expect(useQueueStore.getState().getNextTrack()?.id).toBe('1');
    });
  });

  describe('advanceToNextTrack', () => {
    it('should advance to specified track and reset crossfade', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2'), createMockTrack('3')];
      useQueueStore.getState().setQueue(tracks, 0);
      useQueueStore.getState().advanceToNextTrack(tracks[1]);

      expect(usePlaybackStore.getState().currentTrack?.id).toBe('2');
      expect(useQueueStore.getState().queueIndex).toBe(1);
      expect(usePlaybackStore.getState().currentTime).toBe(0);
      expect(usePlaybackStore.getState().crossfadeState).toBe('idle');
      expect(usePlaybackStore.getState().nextTrackPreloaded).toBe(false);
    });

    it('should add previous track to history', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2')];
      useQueueStore.getState().setQueue(tracks, 0);
      useQueueStore.getState().advanceToNextTrack(tracks[1]);

      expect(useQueueStore.getState().history).toHaveLength(1);
      expect(useQueueStore.getState().history[0].id).toBe('1');
    });

    it('should clamp shuffleIndex at boundary', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2'), createMockTrack('3')];
      useQueueStore.getState().setQueue(tracks, 0);

      usePlaybackStore.setState({ shuffle: true });
      useQueueStore.setState({ shuffleOrder: [0, 2, 1], shuffleIndex: 2 });

      useQueueStore.getState().advanceToNextTrack(tracks[1]);

      expect(useQueueStore.getState().shuffleIndex).toBeLessThanOrEqual(
        useQueueStore.getState().shuffleOrder.length
      );
    });

    it('should increment shuffleIndex normally', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2'), createMockTrack('3')];
      useQueueStore.getState().setQueue(tracks, 0);

      usePlaybackStore.setState({ shuffle: true });
      useQueueStore.setState({ shuffleOrder: [0, 2, 1], shuffleIndex: 0 });

      useQueueStore.getState().advanceToNextTrack(tracks[2]);

      expect(useQueueStore.getState().shuffleIndex).toBe(1);
    });
  });

  describe('exitLazyMode', () => {
    it('should clear lazy reservoir but keep queue intact', () => {
      useQueueStore.setState({
        lazyQueueIds: ['a', 'b', 'c'],
        lazyQueueIndex: 1,
        queue: [{ track: createMockTrack('a'), queueId: 'q1' }],
        queueSource: { type: 'library' },
      });

      useQueueStore.getState().exitLazyMode();

      expect(useQueueStore.getState().lazyQueueIds).toBeNull();
      expect(useQueueStore.getState().lazyQueueIndex).toBe(-1);
      expect(useQueueStore.getState().queueSource).toBeNull();
      expect(useQueueStore.getState().queue).toHaveLength(1);
    });
  });

  describe('resetForProfileSwitch', () => {
    it('should reset all player state', () => {
      useQueueStore.getState().setQueue([createMockTrack('1')], 0);
      useQueueStore.getState().toggleShuffle();

      useQueueStore.getState().resetForProfileSwitch();

      expect(usePlaybackStore.getState().currentTrack).toBeNull();
      expect(usePlaybackStore.getState().isPlaying).toBe(false);
      expect(useQueueStore.getState().queue).toEqual([]);
      expect(usePlaybackStore.getState().shuffle).toBe(false);
      expect(usePlaybackStore.getState().repeat).toBe('off');
      expect(useQueueStore.getState().history).toEqual([]);
      expect(useQueueStore.getState().shuffleOrder).toEqual([]);
      expect(usePlaybackStore.getState().isHydrated).toBe(false);
    });
  });

  describe('history management', () => {
    it('should limit history to 50 tracks', () => {
      for (let i = 0; i < 60; i++) {
        useQueueStore.getState().playTrack(createMockTrack(`${i}`));
      }

      expect(useQueueStore.getState().history).toHaveLength(50);
      expect(useQueueStore.getState().history[0].id).toBe('9');
      expect(useQueueStore.getState().history[49].id).toBe('58');
    });
  });
});
