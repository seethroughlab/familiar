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

// Mock audioGraph — provide controllable getCurrentElement and getCrossfadeContext
const mockGetCurrentElement = vi.fn<() => HTMLAudioElement | null>(() => null)
const mockGetCrossfadeContext = vi.fn<() => { isActive: boolean; startTime: number; duration: number; timeoutId: ReturnType<typeof setTimeout> | null } | null>(() => null)
vi.mock('../audio/audioGraph', () => ({
  getCurrentElement: () => mockGetCurrentElement(),
  getCrossfadeContext: () => mockGetCrossfadeContext(),
}))

// Mock crossfade module
const mockCancelCrossfade = vi.fn()
vi.mock('../audio/crossfade', () => ({
  cancelCrossfade: () => mockCancelCrossfade(),
}))

// Mock eventHandlers — return a fixed effective crossfade duration
vi.mock('../audio/eventHandlers', () => ({
  getEffectiveCrossfadeDuration: () => 5,
}))

// Mock platform
vi.mock('../audio/platform', () => ({
  useDirectPlayback: false,
  MOBILE_TRANSITION_OVERLAP: 0.3,
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
    it('should set audio element currentTime and store currentTime', () => {
      const mockEl = { currentTime: 0, duration: 180 } as HTMLAudioElement
      mockGetCurrentElement.mockReturnValue(mockEl)

      const { result } = renderHook(() => useAudioControls())

      act(() => {
        result.current.seek(30)
      })

      expect(mockEl.currentTime).toBe(30)
      expect(usePlayerStore.getState().currentTime).toBe(30)
    })

    it('should not touch element for non-finite values', () => {
      const mockEl = { currentTime: 10, duration: 180 } as HTMLAudioElement
      mockGetCurrentElement.mockReturnValue(mockEl)

      const { result } = renderHook(() => useAudioControls())

      act(() => {
        result.current.seek(Infinity)
      })

      expect(mockEl.currentTime).toBe(10) // unchanged
    })

    it('should cancel crossfade when seeking far from end', () => {
      const mockEl = { currentTime: 0, duration: 180 } as HTMLAudioElement
      mockGetCurrentElement.mockReturnValue(mockEl)
      mockGetCrossfadeContext.mockReturnValue({ isActive: true, startTime: 0, duration: 5, timeoutId: null })

      const { result } = renderHook(() => useAudioControls())

      // Seek to 30s — far from end (180 - 30 = 150 > effectiveCrossfade(5) + 1)
      act(() => {
        result.current.seek(30)
      })

      expect(mockCancelCrossfade).toHaveBeenCalled()
    })

    it('should NOT cancel crossfade when seeking near end', () => {
      const mockEl = { currentTime: 0, duration: 180 } as HTMLAudioElement
      mockGetCurrentElement.mockReturnValue(mockEl)
      mockGetCrossfadeContext.mockReturnValue({ isActive: true, startTime: 0, duration: 5, timeoutId: null })

      const { result } = renderHook(() => useAudioControls())

      // Seek to 176s — near end (180 - 176 = 4, which is NOT > effectiveCrossfade(5) + 1)
      act(() => {
        result.current.seek(176)
      })

      expect(mockCancelCrossfade).not.toHaveBeenCalled()
    })

    it('should do nothing when no audio element', () => {
      mockGetCurrentElement.mockReturnValue(null)

      const { result } = renderHook(() => useAudioControls())

      act(() => {
        result.current.seek(30)
      })

      // Store should not be updated since we returned early
      expect(usePlayerStore.getState().currentTime).toBe(0)
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
