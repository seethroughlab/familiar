/**
 * Tests for useAudioControls hook — seek, togglePlayPause, crossfade cancel.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useAudioControls } from '../useAudioControls'
import { usePlayerStore } from '../playerStore'

// Mock persistence (playerStore dependency)
vi.mock('../persistence', () => ({
  debouncedSavePlayerState: vi.fn(),
  loadPlayerState: vi.fn(() => Promise.resolve(null)),
  fetchTracksBatched: vi.fn(() => Promise.resolve([])),
  migrateOldPlayerState: vi.fn(() => Promise.resolve()),
}))

// Mock engineInstance — provide controllable engine for seek/crossfade tests
const mockSeek = vi.fn()
const mockGetDuration = vi.fn(() => 180)
const mockIsCrossfading = vi.fn(() => false)
const mockCancelCrossfade = vi.fn()

vi.mock('../audio/engineInstance', () => ({
  getEngine: () => ({
    seek: mockSeek,
    getDuration: mockGetDuration,
    isCrossfading: mockIsCrossfading,
    cancelCrossfade: mockCancelCrossfade,
  }),
}))

// Mock eventHandlers — return a fixed effective crossfade duration
vi.mock('../audio/eventHandlers', () => ({
  getEffectiveCrossfadeDuration: () => 5,
}))

// Mock audioSettingsStore
vi.mock('../audioSettingsStore', () => ({
  useAudioSettingsStore: () => ({
    crossfadeEnabled: true,
    crossfadeDuration: 5,
  }),
}))

// Mock platform
vi.mock('../audio/platform', () => ({
  log: { error: vi.fn(), info: vi.fn(), debug: vi.fn(), warn: vi.fn() },
}))

describe('useAudioControls', () => {
  beforeEach(() => {
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
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('seek', () => {
    it('should call engine.seek and update store currentTime', () => {
      const { result } = renderHook(() => useAudioControls())

      act(() => {
        result.current.seek(30)
      })

      expect(mockSeek).toHaveBeenCalledWith(30)
      expect(usePlayerStore.getState().currentTime).toBe(30)
    })

    it('should not seek for non-finite values', () => {
      const { result } = renderHook(() => useAudioControls())

      act(() => {
        result.current.seek(Infinity)
      })

      expect(mockSeek).not.toHaveBeenCalled()
    })

    it('should cancel crossfade when seeking far from end', () => {
      mockIsCrossfading.mockReturnValue(true)
      mockGetDuration.mockReturnValue(180)

      const { result } = renderHook(() => useAudioControls())

      // Seek to 30s — far from end (180 - 30 = 150 > effectiveCrossfade(5) + 1)
      act(() => {
        result.current.seek(30)
      })

      expect(mockCancelCrossfade).toHaveBeenCalled()
    })

    it('should NOT cancel crossfade when seeking near end', () => {
      mockIsCrossfading.mockReturnValue(true)
      mockGetDuration.mockReturnValue(180)

      const { result } = renderHook(() => useAudioControls())

      // Seek to 176s — near end (180 - 176 = 4, which is NOT > effectiveCrossfade(5) + 1)
      act(() => {
        result.current.seek(176)
      })

      expect(mockCancelCrossfade).not.toHaveBeenCalled()
    })
  })

  describe('togglePlayPause', () => {
    it('should toggle isPlaying state', () => {
      const { result } = renderHook(() => useAudioControls())

      expect(usePlayerStore.getState().isPlaying).toBe(false)

      act(() => {
        result.current.togglePlayPause()
      })

      expect(usePlayerStore.getState().isPlaying).toBe(true)

      // Re-render to pick up new isPlaying value
      const { result: result2 } = renderHook(() => useAudioControls())

      act(() => {
        result2.current.togglePlayPause()
      })

      expect(usePlayerStore.getState().isPlaying).toBe(false)
    })
  })
})
