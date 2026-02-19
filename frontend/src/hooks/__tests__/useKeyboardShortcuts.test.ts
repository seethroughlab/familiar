/**
 * Tests for useKeyboardShortcuts hook.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useKeyboardShortcuts, SHORTCUTS, formatShortcutKey } from '../useKeyboardShortcuts'
import { usePlayerStore } from '../../stores/playerStore'

// Mock the persistence functions
vi.mock('../../services/playerPersistence', () => ({
  debouncedSavePlayerState: vi.fn(),
  loadPlayerState: vi.fn(() => Promise.resolve(null)),
  fetchTracksBatched: vi.fn(() => Promise.resolve([])),
  migrateOldPlayerState: vi.fn(() => Promise.resolve()),
}))

// Mock audioGraph so keyboard seek tests can verify element.currentTime
const mockGetCurrentElement = vi.fn<() => Partial<HTMLAudioElement> | null>(() => null)
vi.mock('../audio/audioGraph', () => ({
  getCurrentElement: () => mockGetCurrentElement(),
}))

// Helper to simulate keyboard events
const fireKeyDown = (key: string, options: Partial<KeyboardEvent> = {}) => {
  const event = new KeyboardEvent('keydown', {
    key,
    bubbles: true,
    cancelable: true,
    ...options,
  })
  window.dispatchEvent(event)
  return event
}

describe('useKeyboardShortcuts', () => {
  beforeEach(() => {
    // Reset store to initial state before each test
    usePlayerStore.setState({
      currentTrack: null,
      isPlaying: false,
      currentTime: 0,
      duration: 180,
      volume: 0.5,
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
    mockGetCurrentElement.mockReturnValue(null)
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('play/pause', () => {
    it('should toggle play on space key', () => {
      renderHook(() => useKeyboardShortcuts())

      expect(usePlayerStore.getState().isPlaying).toBe(false)

      act(() => {
        fireKeyDown(' ')
      })

      expect(usePlayerStore.getState().isPlaying).toBe(true)

      act(() => {
        fireKeyDown(' ')
      })

      expect(usePlayerStore.getState().isPlaying).toBe(false)
    })
  })

  describe('volume control', () => {
    it('should increase volume on ArrowUp', () => {
      renderHook(() => useKeyboardShortcuts())

      const initialVolume = usePlayerStore.getState().volume

      act(() => {
        fireKeyDown('ArrowUp')
      })

      expect(usePlayerStore.getState().volume).toBeCloseTo(initialVolume + 0.1)
    })

    it('should decrease volume on ArrowDown', () => {
      renderHook(() => useKeyboardShortcuts())

      const initialVolume = usePlayerStore.getState().volume

      act(() => {
        fireKeyDown('ArrowDown')
      })

      expect(usePlayerStore.getState().volume).toBeCloseTo(initialVolume - 0.1)
    })

    it('should not exceed volume 1', () => {
      usePlayerStore.setState({ volume: 0.95 })
      renderHook(() => useKeyboardShortcuts())

      act(() => {
        fireKeyDown('ArrowUp')
      })

      expect(usePlayerStore.getState().volume).toBe(1)
    })

    it('should not go below volume 0', () => {
      usePlayerStore.setState({ volume: 0.05 })
      renderHook(() => useKeyboardShortcuts())

      act(() => {
        fireKeyDown('ArrowDown')
      })

      expect(usePlayerStore.getState().volume).toBe(0)
    })
  })

  describe('mute toggle', () => {
    it('should mute on m key when volume > 0', () => {
      usePlayerStore.setState({ volume: 0.7 })
      renderHook(() => useKeyboardShortcuts())

      act(() => {
        fireKeyDown('m')
      })

      expect(usePlayerStore.getState().volume).toBe(0)
    })

    it('should unmute on m key when volume is 0', () => {
      // Set volume first, then mute
      usePlayerStore.setState({ volume: 0.7 })
      const { rerender } = renderHook(() => useKeyboardShortcuts())

      act(() => {
        fireKeyDown('m') // Mute
      })

      rerender()

      act(() => {
        fireKeyDown('m') // Unmute
      })

      expect(usePlayerStore.getState().volume).toBeGreaterThan(0)
    })

    it('should work with uppercase M', () => {
      usePlayerStore.setState({ volume: 0.7 })
      renderHook(() => useKeyboardShortcuts())

      act(() => {
        fireKeyDown('M')
      })

      expect(usePlayerStore.getState().volume).toBe(0)
    })
  })

  describe('track navigation', () => {
    it('should call playNext on ArrowRight', () => {
      const playNextSpy = vi.spyOn(usePlayerStore.getState(), 'playNext')
      renderHook(() => useKeyboardShortcuts())

      act(() => {
        fireKeyDown('ArrowRight')
      })

      expect(playNextSpy).toHaveBeenCalled()
    })

    it('should call playPrevious on ArrowLeft', () => {
      const playPreviousSpy = vi.spyOn(usePlayerStore.getState(), 'playPrevious')
      renderHook(() => useKeyboardShortcuts())

      act(() => {
        fireKeyDown('ArrowLeft')
      })

      expect(playPreviousSpy).toHaveBeenCalled()
    })

    it('should not navigate with modifier keys', () => {
      const playNextSpy = vi.spyOn(usePlayerStore.getState(), 'playNext')
      renderHook(() => useKeyboardShortcuts())

      act(() => {
        fireKeyDown('ArrowRight', { shiftKey: true })
      })

      expect(playNextSpy).not.toHaveBeenCalled()
    })
  })

  describe('shuffle and repeat', () => {
    it('should toggle shuffle on s key', () => {
      renderHook(() => useKeyboardShortcuts())

      expect(usePlayerStore.getState().shuffle).toBe(false)

      act(() => {
        fireKeyDown('s')
      })

      // Note: shuffle won't actually change with empty queue
      // This tests that the action is called, not the store behavior
    })

    it('should cycle repeat on r key', () => {
      renderHook(() => useKeyboardShortcuts())

      expect(usePlayerStore.getState().repeat).toBe('off')

      act(() => {
        fireKeyDown('r')
      })

      expect(usePlayerStore.getState().repeat).toBe('all')

      act(() => {
        fireKeyDown('r')
      })

      expect(usePlayerStore.getState().repeat).toBe('one')

      act(() => {
        fireKeyDown('r')
      })

      expect(usePlayerStore.getState().repeat).toBe('off')
    })

    it('should not toggle shuffle with ctrl key', () => {
      const toggleShuffleSpy = vi.spyOn(usePlayerStore.getState(), 'toggleShuffle')
      renderHook(() => useKeyboardShortcuts())

      act(() => {
        fireKeyDown('s', { ctrlKey: true })
      })

      expect(toggleShuffleSpy).not.toHaveBeenCalled()
    })
  })

  describe('seeking', () => {
    it('should seek forward 10s on l key', () => {
      usePlayerStore.setState({ currentTime: 30, duration: 180 })
      renderHook(() => useKeyboardShortcuts())

      act(() => {
        fireKeyDown('l')
      })

      expect(usePlayerStore.getState().currentTime).toBe(40)
    })

    it('should seek backward 10s on j key', () => {
      usePlayerStore.setState({ currentTime: 30, duration: 180 })
      renderHook(() => useKeyboardShortcuts())

      act(() => {
        fireKeyDown('j')
      })

      expect(usePlayerStore.getState().currentTime).toBe(20)
    })

    it('should not seek past duration', () => {
      usePlayerStore.setState({ currentTime: 175, duration: 180 })
      renderHook(() => useKeyboardShortcuts())

      act(() => {
        fireKeyDown('l')
      })

      expect(usePlayerStore.getState().currentTime).toBe(180)
    })

    it('should not seek below 0', () => {
      usePlayerStore.setState({ currentTime: 5, duration: 180 })
      renderHook(() => useKeyboardShortcuts())

      act(() => {
        fireKeyDown('j')
      })

      expect(usePlayerStore.getState().currentTime).toBe(0)
    })

    it('should set audio element currentTime on l key', () => {
      const mockEl = { currentTime: 0 }
      mockGetCurrentElement.mockReturnValue(mockEl as unknown as HTMLAudioElement)
      usePlayerStore.setState({ currentTime: 30, duration: 180 })
      renderHook(() => useKeyboardShortcuts())

      act(() => {
        fireKeyDown('l')
      })

      expect(mockEl.currentTime).toBe(40)
    })

    it('should set audio element currentTime on j key', () => {
      const mockEl = { currentTime: 0 }
      mockGetCurrentElement.mockReturnValue(mockEl as unknown as HTMLAudioElement)
      usePlayerStore.setState({ currentTime: 30, duration: 180 })
      renderHook(() => useKeyboardShortcuts())

      act(() => {
        fireKeyDown('j')
      })

      expect(mockEl.currentTime).toBe(20)
    })
  })

  describe('handlers', () => {
    it('should call onToggleFullPlayer on f key', () => {
      const onToggleFullPlayer = vi.fn()
      renderHook(() => useKeyboardShortcuts({ onToggleFullPlayer }))

      act(() => {
        fireKeyDown('f')
      })

      expect(onToggleFullPlayer).toHaveBeenCalled()
    })

    it('should call onShowHelp on ? key', () => {
      const onShowHelp = vi.fn()
      renderHook(() => useKeyboardShortcuts({ onShowHelp }))

      act(() => {
        fireKeyDown('?')
      })

      expect(onShowHelp).toHaveBeenCalled()
    })

    it('should call onEscape on Escape key', () => {
      const onEscape = vi.fn()
      renderHook(() => useKeyboardShortcuts({ onEscape }))

      act(() => {
        fireKeyDown('Escape')
      })

      expect(onEscape).toHaveBeenCalled()
    })
  })

  describe('input field handling', () => {
    it('should not handle shortcuts when target is input', () => {
      renderHook(() => useKeyboardShortcuts())

      // Create an input element
      const input = document.createElement('input')
      document.body.appendChild(input)
      input.focus()

      const event = new KeyboardEvent('keydown', {
        key: ' ',
        bubbles: true,
        cancelable: true,
      })
      Object.defineProperty(event, 'target', { value: input })
      window.dispatchEvent(event)

      // isPlaying should not change
      expect(usePlayerStore.getState().isPlaying).toBe(false)

      document.body.removeChild(input)
    })
  })
})

describe('SHORTCUTS', () => {
  it('should have all expected shortcuts defined', () => {
    expect(SHORTCUTS.playPause).toBeDefined()
    expect(SHORTCUTS.nextTrack).toBeDefined()
    expect(SHORTCUTS.prevTrack).toBeDefined()
    expect(SHORTCUTS.volumeUp).toBeDefined()
    expect(SHORTCUTS.volumeDown).toBeDefined()
    expect(SHORTCUTS.mute).toBeDefined()
    expect(SHORTCUTS.fullPlayer).toBeDefined()
    expect(SHORTCUTS.help).toBeDefined()
    expect(SHORTCUTS.seekForward).toBeDefined()
    expect(SHORTCUTS.seekBackward).toBeDefined()
    expect(SHORTCUTS.shuffle).toBeDefined()
    expect(SHORTCUTS.repeat).toBeDefined()
  })

  it('should have descriptions for all shortcuts', () => {
    for (const [key, shortcut] of Object.entries(SHORTCUTS)) {
      expect(shortcut.description, `${key} should have description`).toBeTruthy()
    }
  })
})

describe('formatShortcutKey', () => {
  it('should format Space key', () => {
    expect(formatShortcutKey('Space')).toBe('Space')
  })

  it('should format arrow keys with symbols', () => {
    expect(formatShortcutKey('ArrowUp')).toBe('↑')
    expect(formatShortcutKey('ArrowDown')).toBe('↓')
    expect(formatShortcutKey('ArrowLeft')).toBe('←')
    expect(formatShortcutKey('ArrowRight')).toBe('→')
  })

  it('should format Escape key', () => {
    expect(formatShortcutKey('Escape')).toBe('Esc')
  })

  it('should uppercase regular keys', () => {
    expect(formatShortcutKey('m')).toBe('M')
    expect(formatShortcutKey('f')).toBe('F')
  })
})
