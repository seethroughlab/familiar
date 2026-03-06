/**
 * Tests for playerStore - Zustand store for audio player state.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { usePlayerStore } from '../playerStore'
import type { Track } from '../../types'

// Mock the persistence functions
vi.mock('../persistence', () => ({
  debouncedSavePlayerState: vi.fn(),
  loadPlayerState: vi.fn(() => Promise.resolve(null)),
  fetchTracksBatched: vi.fn(() => Promise.resolve([])),
  migrateOldPlayerState: vi.fn(() => Promise.resolve()),
}))

// Mock engineInstance so playerStore's playPrevious can call seek()
const mockSeek = vi.fn()
vi.mock('../audio/engineInstance', () => ({
  getEngine: () => ({ seek: mockSeek }),
}))

// Helper to create mock tracks
const createMockTrack = (id: string, title = 'Test Track'): Track => ({
  id,
  title,
  artist: 'Test Artist',
  album: 'Test Album',
  album_artist: null,
  album_type: 'album',
  track_number: 1,
  disc_number: 1,
  year: 2024,
  genre: 'Test',
  duration_seconds: 180,
  format: 'mp3',
  file_path: `/music/${id}.mp3`,
  analysis_version: 1,
})

describe('playerStore', () => {
  beforeEach(() => {
    // Reset store to initial state before each test
    usePlayerStore.setState({
      currentTrack: null,
      isPlaying: false,
      currentTime: 0,
      duration: 0,
      volume: 1,
      shuffle: false,
      repeat: 'off',
      queue: [],
      queueIndex: -1,
      history: [],
      shuffleOrder: [],
      shuffleIndex: -1,
      crossfadeState: 'idle',
      nextTrackPreloaded: false,
      isHydrated: true,
    })
    mockSeek.mockClear()
  })

  describe('volume control', () => {
    it('should set volume within bounds', () => {
      const { setVolume } = usePlayerStore.getState()

      setVolume(0.5)
      expect(usePlayerStore.getState().volume).toBe(0.5)
    })

    it('should clamp volume at minimum 0', () => {
      const { setVolume } = usePlayerStore.getState()

      setVolume(-0.5)
      expect(usePlayerStore.getState().volume).toBe(0)
    })

    it('should clamp volume at maximum 1', () => {
      const { setVolume } = usePlayerStore.getState()

      setVolume(1.5)
      expect(usePlayerStore.getState().volume).toBe(1)
    })
  })

  describe('toggleRepeat', () => {
    it('should cycle off -> all -> one -> off', () => {
      const { toggleRepeat } = usePlayerStore.getState()

      expect(usePlayerStore.getState().repeat).toBe('off')

      toggleRepeat()
      expect(usePlayerStore.getState().repeat).toBe('all')

      toggleRepeat()
      expect(usePlayerStore.getState().repeat).toBe('one')

      toggleRepeat()
      expect(usePlayerStore.getState().repeat).toBe('off')
    })
  })

  describe('toggleShuffle', () => {
    it('should enable shuffle and generate shuffle order', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')
      const track3 = createMockTrack('3')

      // Set up a queue with 3 tracks
      const { setQueue, toggleShuffle } = usePlayerStore.getState()
      setQueue([track1, track2, track3], 0)

      // Enable shuffle
      toggleShuffle()

      const state = usePlayerStore.getState()
      expect(state.shuffle).toBe(true)
      expect(state.shuffleOrder).toHaveLength(3)
      expect(state.shuffleIndex).toBe(0)
      // Current track should be first in shuffle order
      expect(state.shuffleOrder[0]).toBe(0)
    })

    it('should disable shuffle and clear shuffle state', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')

      const { setQueue, toggleShuffle } = usePlayerStore.getState()
      setQueue([track1, track2], 0)

      // Enable then disable shuffle
      toggleShuffle()
      toggleShuffle()

      const state = usePlayerStore.getState()
      expect(state.shuffle).toBe(false)
      expect(state.shuffleOrder).toEqual([])
      expect(state.shuffleIndex).toBe(-1)
    })

    it('should enable shuffle even with empty queue', () => {
      const { toggleShuffle } = usePlayerStore.getState()

      // Toggle shuffle with no queue
      toggleShuffle()

      const state = usePlayerStore.getState()
      expect(state.shuffle).toBe(true)
      expect(state.shuffleOrder).toEqual([])
      expect(state.shuffleIndex).toBe(-1)
    })

    it('should enable shuffle with single track in queue', () => {
      const track1 = createMockTrack('1')
      const { setQueue, toggleShuffle } = usePlayerStore.getState()
      setQueue([track1], 0)

      toggleShuffle()

      const state = usePlayerStore.getState()
      expect(state.shuffle).toBe(true)
      expect(state.shuffleOrder).toEqual([])
      expect(state.shuffleIndex).toBe(-1)
    })

    it('should include all tracks in shuffle order', () => {
      const tracks = Array.from({ length: 10 }, (_, i) =>
        createMockTrack(`${i}`, `Track ${i}`)
      )

      const { setQueue, toggleShuffle } = usePlayerStore.getState()
      setQueue(tracks, 0)
      toggleShuffle()

      const { shuffleOrder } = usePlayerStore.getState()

      // Should contain all indices
      const sortedOrder = [...shuffleOrder].sort((a, b) => a - b)
      expect(sortedOrder).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    })
  })

  describe('setQueue', () => {
    it('should set queue and start playing first track', () => {
      const track1 = createMockTrack('1', 'First')
      const track2 = createMockTrack('2', 'Second')

      const { setQueue } = usePlayerStore.getState()
      setQueue([track1, track2], 0)

      const state = usePlayerStore.getState()
      expect(state.queue).toHaveLength(2)
      expect(state.queueIndex).toBe(0)
      expect(state.currentTrack?.id).toBe('1')
      expect(state.isPlaying).toBe(true)
    })

    it('should start at specified index', () => {
      const track1 = createMockTrack('1', 'First')
      const track2 = createMockTrack('2', 'Second')
      const track3 = createMockTrack('3', 'Third')

      const { setQueue } = usePlayerStore.getState()
      setQueue([track1, track2, track3], 1)

      const state = usePlayerStore.getState()
      expect(state.queueIndex).toBe(1)
      expect(state.currentTrack?.id).toBe('2')
    })

    it('should generate shuffle order when shuffle is enabled', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')
      const track3 = createMockTrack('3')

      // Enable shuffle first
      usePlayerStore.setState({ shuffle: true })

      const { setQueue } = usePlayerStore.getState()
      setQueue([track1, track2, track3], 0)

      const state = usePlayerStore.getState()
      expect(state.shuffleOrder).toHaveLength(3)
      expect(state.shuffleIndex).toBe(0)
    })
  })

  describe('addToQueue', () => {
    it('should add track to end of queue', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')

      const { setQueue, addToQueue } = usePlayerStore.getState()
      setQueue([track1], 0)
      addToQueue(track2)

      const state = usePlayerStore.getState()
      expect(state.queue).toHaveLength(2)
      expect(state.queue[1].track.id).toBe('2')
    })

    it('should update shuffle order when shuffle is on', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')
      const track3 = createMockTrack('3')

      // Need at least 2 tracks for shuffle order to be generated
      const { setQueue, toggleShuffle, addToQueue } = usePlayerStore.getState()
      setQueue([track1, track2], 0)
      toggleShuffle()

      // Verify shuffle is on and order exists
      expect(usePlayerStore.getState().shuffle).toBe(true)
      expect(usePlayerStore.getState().shuffleOrder).toHaveLength(2)

      // Add a third track
      addToQueue(track3)

      const { shuffleOrder } = usePlayerStore.getState()
      expect(shuffleOrder).toHaveLength(3)
      expect(shuffleOrder).toContain(2) // New track index should be in order
    })
  })

  describe('clearQueue', () => {
    it('should clear queue and reset index', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')

      const { setQueue, clearQueue } = usePlayerStore.getState()
      setQueue([track1, track2], 0)
      clearQueue()

      const state = usePlayerStore.getState()
      expect(state.queue).toEqual([])
      expect(state.queueIndex).toBe(-1)
    })

    it('should clear lazy state when in lazy mode', () => {
      const mockTrack = createMockTrack('a')
      usePlayerStore.setState({
        lazyQueueIds: ['a', 'b', 'c', 'd', 'e'],
        lazyQueueIndex: 2,
        queue: [{ track: mockTrack, queueId: 'q1' }],
        queueIndex: 0,
        queueSource: { type: 'library' },
      })

      usePlayerStore.getState().clearQueue()

      const state = usePlayerStore.getState()
      expect(state.queue).toEqual([])
      expect(state.queueIndex).toBe(-1)
      expect(state.lazyQueueIds).toBeNull()
      expect(state.lazyQueueIndex).toBe(-1)
      expect(state.queueSource).toBeNull()
    })
  })

  describe('playNext', () => {
    it('should advance to next track in sequential mode', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')
      const track3 = createMockTrack('3')

      const { setQueue, playNext } = usePlayerStore.getState()
      setQueue([track1, track2, track3], 0)
      playNext()

      const state = usePlayerStore.getState()
      expect(state.queueIndex).toBe(1)
      expect(state.currentTrack?.id).toBe('2')
    })

    it('should stop playing at end of queue without repeat', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')

      const { setQueue, playNext } = usePlayerStore.getState()
      setQueue([track1, track2], 1) // Start at last track
      playNext()

      const state = usePlayerStore.getState()
      expect(state.isPlaying).toBe(false)
    })

    it('should wrap to start with repeat all', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')

      const { setQueue, toggleRepeat, playNext } = usePlayerStore.getState()
      setQueue([track1, track2], 1)
      toggleRepeat() // Set to 'all'
      playNext()

      const state = usePlayerStore.getState()
      expect(state.queueIndex).toBe(0)
      expect(state.currentTrack?.id).toBe('1')
      expect(state.isPlaying).toBe(true)
    })

    it('should add current track to history', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')

      const { setQueue, playNext } = usePlayerStore.getState()
      setQueue([track1, track2], 0)
      playNext()

      const state = usePlayerStore.getState()
      expect(state.history).toHaveLength(1)
      expect(state.history[0].id).toBe('1')
    })

    it('should follow shuffle order when shuffle is on', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')
      const track3 = createMockTrack('3')

      const { setQueue, toggleShuffle, playNext } = usePlayerStore.getState()
      setQueue([track1, track2, track3], 0)
      toggleShuffle()

      // Get shuffle order before advancing
      const { shuffleOrder } = usePlayerStore.getState()
      playNext()

      const state = usePlayerStore.getState()
      // Should be at the track in shuffleOrder[1]
      expect(state.queueIndex).toBe(shuffleOrder[1])
      expect(state.shuffleIndex).toBe(1)
    })
  })

  describe('playPrevious', () => {
    it('should restart track if more than 3 seconds in', () => {
      const track1 = createMockTrack('1')

      const { setQueue } = usePlayerStore.getState()
      setQueue([track1], 0)

      // Simulate being 5 seconds into the track
      usePlayerStore.setState({ currentTime: 5 })

      const { playPrevious } = usePlayerStore.getState()
      playPrevious()

      const state = usePlayerStore.getState()
      expect(state.currentTime).toBe(0)
      expect(state.currentTrack?.id).toBe('1') // Same track
    })

    it('should go to previous track from history', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')

      const { setQueue, playNext, playPrevious } = usePlayerStore.getState()
      setQueue([track1, track2], 0)
      playNext() // Now on track2, track1 in history

      // Set current time to 0 so we go to previous track
      usePlayerStore.setState({ currentTime: 0 })
      playPrevious()

      const state = usePlayerStore.getState()
      expect(state.currentTrack?.id).toBe('1')
      expect(state.history).toHaveLength(0)
    })

    it('back in shuffle with > 3 seconds restarts current track', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')
      const track3 = createMockTrack('3')

      const { setQueue } = usePlayerStore.getState()
      setQueue([track1, track2, track3], 0)

      // Manually set shuffle state: order [0, 2, 1], currently at shuffleIndex=1 (track3)
      usePlayerStore.setState({
        shuffle: true,
        shuffleOrder: [0, 2, 1],
        shuffleIndex: 1,
        queueIndex: 2,
        currentTrack: track3,
        currentTime: 30, // well past 3 seconds — should restart, not navigate
      })

      usePlayerStore.getState().playPrevious()

      const state = usePlayerStore.getState()
      // Should restart current track, NOT navigate to previous shuffle position
      expect(state.currentTrack?.id).toBe('3') // still track3
      expect(state.shuffleIndex).toBe(1) // unchanged
      expect(state.currentTime).toBe(0) // restarted
      expect(mockSeek).toHaveBeenCalledWith(0)
    })

    it('back in shuffle with <= 3 seconds navigates to previous shuffle order track', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')
      const track3 = createMockTrack('3')

      const { setQueue } = usePlayerStore.getState()
      setQueue([track1, track2, track3], 0)

      // Manually set shuffle state: order [0, 2, 1], currently at shuffleIndex=1 (track3)
      usePlayerStore.setState({
        shuffle: true,
        shuffleOrder: [0, 2, 1],
        shuffleIndex: 1,
        queueIndex: 2,
        currentTrack: track3,
        currentTime: 1, // under 3 seconds — should navigate back
      })

      usePlayerStore.getState().playPrevious()

      const state = usePlayerStore.getState()
      expect(state.currentTrack?.id).toBe('1') // shuffleOrder[0] = queue[0] = track1
      expect(state.shuffleIndex).toBe(0)
      expect(state.queueIndex).toBe(0)
      expect(state.currentTime).toBe(0)
      expect(state.isPlaying).toBe(true)
    })

    it('back then forward in shuffle replays the same next track', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')
      const track3 = createMockTrack('3')

      const { setQueue } = usePlayerStore.getState()
      setQueue([track1, track2, track3], 0)

      // shuffleOrder [0, 2, 1]: start at index 1 (track3)
      usePlayerStore.setState({
        shuffle: true,
        shuffleOrder: [0, 2, 1],
        shuffleIndex: 1,
        queueIndex: 2,
        currentTrack: track3,
        currentTime: 0,
      })

      // Go back: should land on shuffleIndex=0 (track1)
      usePlayerStore.getState().playPrevious()
      expect(usePlayerStore.getState().currentTrack?.id).toBe('1')
      expect(usePlayerStore.getState().shuffleIndex).toBe(0)

      // Go forward: should advance shuffleIndex to 1 → track3 again
      usePlayerStore.getState().playNext()
      const state = usePlayerStore.getState()
      expect(state.currentTrack?.id).toBe('3') // back to shuffleOrder[1] = queue[2] = track3
      expect(state.shuffleIndex).toBe(1)
    })
  })

  describe('playTrack', () => {
    it('should set current track and start playing', () => {
      const track = createMockTrack('1')

      const { playTrack } = usePlayerStore.getState()
      playTrack(track)

      const state = usePlayerStore.getState()
      expect(state.currentTrack?.id).toBe('1')
      expect(state.isPlaying).toBe(true)
      expect(state.currentTime).toBe(0)
    })

    it('should add previous track to history', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')

      const { playTrack } = usePlayerStore.getState()
      playTrack(track1)
      playTrack(track2)

      const state = usePlayerStore.getState()
      expect(state.history).toHaveLength(1)
      expect(state.history[0].id).toBe('1')
    })
  })

  describe('getNextTrack', () => {
    it('should return next track in sequential mode', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')

      const { setQueue, getNextTrack } = usePlayerStore.getState()
      setQueue([track1, track2], 0)

      const next = getNextTrack()
      expect(next?.id).toBe('2')
    })

    it('should return null at end without repeat', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')

      const { setQueue, getNextTrack } = usePlayerStore.getState()
      setQueue([track1, track2], 1)

      const next = getNextTrack()
      expect(next).toBeNull()
    })

    it('should return first track at end with repeat all', () => {
      const track1 = createMockTrack('1')
      const track2 = createMockTrack('2')

      const { setQueue, toggleRepeat, getNextTrack } = usePlayerStore.getState()
      setQueue([track1, track2], 1)
      toggleRepeat() // 'all'

      const next = getNextTrack()
      expect(next?.id).toBe('1')
    })
  })

  describe('resetForProfileSwitch', () => {
    it('should reset all player state', () => {
      const track = createMockTrack('1')

      const { setQueue, toggleShuffle, resetForProfileSwitch } = usePlayerStore.getState()
      setQueue([track], 0)
      toggleShuffle()

      resetForProfileSwitch()

      const state = usePlayerStore.getState()
      expect(state.currentTrack).toBeNull()
      expect(state.isPlaying).toBe(false)
      expect(state.queue).toEqual([])
      expect(state.shuffle).toBe(false)
      expect(state.repeat).toBe('off')
      expect(state.history).toEqual([])
      expect(state.shuffleOrder).toEqual([])
      expect(state.isHydrated).toBe(false)
    })
  })

  describe('history management', () => {
    it('should limit history to 50 tracks', () => {
      const { playTrack } = usePlayerStore.getState()

      // Play 60 tracks
      for (let i = 0; i < 60; i++) {
        playTrack(createMockTrack(`${i}`))
      }

      const state = usePlayerStore.getState()
      expect(state.history).toHaveLength(50)
      // Should have the most recent 50, not the first 50
      expect(state.history[0].id).toBe('9')
      expect(state.history[49].id).toBe('58')
    })
  })

  describe('reorderQueue', () => {
    it('should move track from one position to another', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2'), createMockTrack('3')]
      const { setQueue, reorderQueue } = usePlayerStore.getState()
      setQueue(tracks, 0)

      reorderQueue(0, 2)

      const state = usePlayerStore.getState()
      expect(state.queue[0].track.id).toBe('2')
      expect(state.queue[1].track.id).toBe('3')
      expect(state.queue[2].track.id).toBe('1')
    })

    it('should update queueIndex to keep current track selected', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2'), createMockTrack('3')]
      const { setQueue, reorderQueue } = usePlayerStore.getState()
      setQueue(tracks, 0) // playing track '1'

      // Move track '1' from index 0 to index 2
      reorderQueue(0, 2)

      const state = usePlayerStore.getState()
      // queueIndex should point to where track '1' is now
      expect(state.queueIndex).toBe(2)
      expect(state.currentTrack?.id).toBe('1')
    })

    it('should ignore out-of-bounds indices', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2')]
      const { setQueue, reorderQueue } = usePlayerStore.getState()
      setQueue(tracks, 0)

      reorderQueue(-1, 0)
      expect(usePlayerStore.getState().queue[0].track.id).toBe('1') // unchanged

      reorderQueue(0, 5)
      expect(usePlayerStore.getState().queue[0].track.id).toBe('1') // unchanged
    })
  })

  describe('jumpToQueueIndex', () => {
    it('should jump to specified queue index', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2'), createMockTrack('3')]
      const { setQueue, jumpToQueueIndex } = usePlayerStore.getState()
      setQueue(tracks, 0)

      jumpToQueueIndex(2)

      const state = usePlayerStore.getState()
      expect(state.queueIndex).toBe(2)
      expect(state.currentTrack?.id).toBe('3')
      expect(state.isPlaying).toBe(true)
      expect(state.currentTime).toBe(0)
    })

    it('should add current track to history', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2')]
      const { setQueue, jumpToQueueIndex } = usePlayerStore.getState()
      setQueue(tracks, 0)

      jumpToQueueIndex(1)

      const state = usePlayerStore.getState()
      expect(state.history).toHaveLength(1)
      expect(state.history[0].id).toBe('1')
    })

    it('should ignore out-of-bounds index', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2')]
      const { setQueue, jumpToQueueIndex } = usePlayerStore.getState()
      setQueue(tracks, 0)

      jumpToQueueIndex(5)

      expect(usePlayerStore.getState().queueIndex).toBe(0) // unchanged
    })

    it('should ignore negative index', () => {
      const tracks = [createMockTrack('1')]
      const { setQueue, jumpToQueueIndex } = usePlayerStore.getState()
      setQueue(tracks, 0)

      jumpToQueueIndex(-1)

      expect(usePlayerStore.getState().queueIndex).toBe(0) // unchanged
    })
  })

  describe('addToQueue (with insertIndex)', () => {
    it('should insert track at specific position', () => {
      const tracks = [createMockTrack('1'), createMockTrack('3')]
      const { setQueue, addToQueue } = usePlayerStore.getState()
      setQueue(tracks, 0)

      addToQueue(createMockTrack('2'), 1)

      const state = usePlayerStore.getState()
      expect(state.queue).toHaveLength(3)
      expect(state.queue[1].track.id).toBe('2')
    })

    it('should adjust queueIndex when inserting before current track', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2')]
      const { setQueue, addToQueue } = usePlayerStore.getState()
      setQueue(tracks, 1) // playing track '2' at index 1

      addToQueue(createMockTrack('0'), 0) // insert before current

      const state = usePlayerStore.getState()
      expect(state.queueIndex).toBe(2) // shifted from 1 to 2
    })

    it('should not adjust queueIndex when inserting after current track', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2')]
      const { setQueue, addToQueue } = usePlayerStore.getState()
      setQueue(tracks, 0) // playing track '1' at index 0

      addToQueue(createMockTrack('3'), 2) // insert after current

      expect(usePlayerStore.getState().queueIndex).toBe(0) // unchanged
    })
  })

  describe('removeFromQueue', () => {
    it('should remove track by queueId', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2'), createMockTrack('3')]
      const { setQueue, removeFromQueue } = usePlayerStore.getState()
      setQueue(tracks, 0)

      const queueId = usePlayerStore.getState().queue[1].queueId
      removeFromQueue(queueId)

      const state = usePlayerStore.getState()
      expect(state.queue).toHaveLength(2)
      expect(state.queue.find((q) => q.track.id === '2')).toBeUndefined()
    })

    it('should not remove anything for unknown queueId', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2')]
      const { setQueue, removeFromQueue } = usePlayerStore.getState()
      setQueue(tracks, 0)

      removeFromQueue('nonexistent-id')

      expect(usePlayerStore.getState().queue).toHaveLength(2)
    })
  })

  describe('setQueue with source', () => {
    it('should track queue source', () => {
      const tracks = [createMockTrack('1')]
      const { setQueue } = usePlayerStore.getState()

      setQueue(tracks, 0, { type: 'playlist', id: 'playlist-123' })

      expect(usePlayerStore.getState().queueSource).toEqual({
        type: 'playlist',
        id: 'playlist-123',
      })
    })

    it('should clear queue source when none provided', () => {
      const tracks = [createMockTrack('1')]
      const { setQueue } = usePlayerStore.getState()

      // First set with source
      setQueue(tracks, 0, { type: 'album', id: 'album-1' })
      // Then set without
      setQueue(tracks, 0)

      expect(usePlayerStore.getState().queueSource).toBeNull()
    })

    it('should exit lazy mode when setting regular queue', () => {
      // Simulate lazy mode
      usePlayerStore.setState({
        lazyQueueIds: ['a', 'b', 'c'],
        lazyQueueIndex: 1,
      })

      const { setQueue } = usePlayerStore.getState()
      setQueue([createMockTrack('1')], 0)

      const state = usePlayerStore.getState()
      expect(state.lazyQueueIds).toBeNull()
      expect(state.lazyQueueIndex).toBe(-1)
    })
  })

  describe('playNext with empty queue', () => {
    it('should stop playing when queue is empty', () => {
      usePlayerStore.setState({ isPlaying: true })
      usePlayerStore.getState().playNext()

      expect(usePlayerStore.getState().isPlaying).toBe(false)
    })
  })

  describe('playNext reshuffle on repeat all', () => {
    it('should reshuffle when reaching end of shuffle order with repeat all', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2'), createMockTrack('3')]
      const { setQueue, toggleShuffle, toggleRepeat } = usePlayerStore.getState()
      setQueue(tracks, 0)
      toggleShuffle()
      toggleRepeat() // 'all'

      const { shuffleOrder } = usePlayerStore.getState()
      // Advance through all shuffle positions
      for (let i = 0; i < shuffleOrder.length; i++) {
        usePlayerStore.getState().playNext()
      }

      // Should still be playing (repeat all reshuffles)
      const state = usePlayerStore.getState()
      expect(state.isPlaying).toBe(true)
      expect(state.shuffleIndex).toBe(0) // Reset to beginning of new shuffle
    })
  })

  describe('crossfade', () => {
    it('should manage crossfade state', () => {
      const { setCrossfadeState } = usePlayerStore.getState()

      setCrossfadeState('preloading')
      expect(usePlayerStore.getState().crossfadeState).toBe('preloading')

      setCrossfadeState('crossfading')
      expect(usePlayerStore.getState().crossfadeState).toBe('crossfading')

      setCrossfadeState('idle')
      expect(usePlayerStore.getState().crossfadeState).toBe('idle')
    })

    it('should manage next track preloaded state', () => {
      const { setNextTrackPreloaded } = usePlayerStore.getState()

      setNextTrackPreloaded(true)
      expect(usePlayerStore.getState().nextTrackPreloaded).toBe(true)

      setNextTrackPreloaded(false)
      expect(usePlayerStore.getState().nextTrackPreloaded).toBe(false)
    })
  })

  describe('advanceToNextTrack', () => {
    it('should advance to specified track and reset crossfade', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2'), createMockTrack('3')]
      const { setQueue, advanceToNextTrack } = usePlayerStore.getState()
      setQueue(tracks, 0)

      advanceToNextTrack(tracks[1])

      const state = usePlayerStore.getState()
      expect(state.currentTrack?.id).toBe('2')
      expect(state.queueIndex).toBe(1)
      expect(state.currentTime).toBe(0)
      expect(state.crossfadeState).toBe('idle')
      expect(state.nextTrackPreloaded).toBe(false)
    })

    it('should add previous track to history', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2')]
      const { setQueue, advanceToNextTrack } = usePlayerStore.getState()
      setQueue(tracks, 0)

      advanceToNextTrack(tracks[1])

      expect(usePlayerStore.getState().history).toHaveLength(1)
      expect(usePlayerStore.getState().history[0].id).toBe('1')
    })
  })

  describe('audio loading', () => {
    it('should track loading state', () => {
      const { setIsLoadingAudio } = usePlayerStore.getState()

      setIsLoadingAudio(true)
      expect(usePlayerStore.getState().isLoadingAudio).toBe(true)

      setIsLoadingAudio(false)
      expect(usePlayerStore.getState().isLoadingAudio).toBe(false)
    })
  })

  describe('exitLazyMode', () => {
    it('should clear lazy reservoir but keep queue intact', () => {
      const mockTrack = createMockTrack('a');
      usePlayerStore.setState({
        lazyQueueIds: ['a', 'b', 'c'],
        lazyQueueIndex: 1,
        queue: [{ track: mockTrack, queueId: 'q1' }],
        queueSource: { type: 'library' },
      })

      usePlayerStore.getState().exitLazyMode()

      const state = usePlayerStore.getState()
      expect(state.lazyQueueIds).toBeNull()
      expect(state.lazyQueueIndex).toBe(-1)
      expect(state.queueSource).toBeNull()
      // Queue should remain intact
      expect(state.queue).toHaveLength(1)
    })
  })

  describe('playPrevious audio element', () => {
    it('should call engine.seek(0) when restarting current track', () => {
      const track1 = createMockTrack('1')
      const { setQueue } = usePlayerStore.getState()
      setQueue([track1], 0)

      usePlayerStore.setState({ currentTime: 5 })
      usePlayerStore.getState().playPrevious()

      expect(mockSeek).toHaveBeenCalledWith(0)
      expect(usePlayerStore.getState().currentTime).toBe(0)
    })
  })

  describe('advanceToNextTrack with shuffle', () => {
    it('should clamp shuffleIndex at boundary', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2'), createMockTrack('3')]
      const { setQueue } = usePlayerStore.getState()
      setQueue(tracks, 0)

      // Manually set up shuffle state at the last position
      usePlayerStore.setState({
        shuffle: true,
        shuffleOrder: [0, 2, 1],
        shuffleIndex: 2,
      })

      usePlayerStore.getState().advanceToNextTrack(tracks[1])

      const state = usePlayerStore.getState()
      expect(state.shuffleIndex).toBeLessThanOrEqual(state.shuffleOrder.length)
    })

    it('should increment shuffleIndex normally', () => {
      const tracks = [createMockTrack('1'), createMockTrack('2'), createMockTrack('3')]
      const { setQueue } = usePlayerStore.getState()
      setQueue(tracks, 0)

      usePlayerStore.setState({
        shuffle: true,
        shuffleOrder: [0, 2, 1],
        shuffleIndex: 0,
      })

      usePlayerStore.getState().advanceToNextTrack(tracks[2])

      const state = usePlayerStore.getState()
      expect(state.shuffleIndex).toBe(1)
    })
  })
})
