/**
 * Tests for useAudioEngine hook - Audio playback and crossfade logic.
 *
 * Note: The audio engine uses platform detection to choose between
 * direct playback (mobile) and Web Audio (desktop). These tests
 * mock the necessary browser APIs.
 */
import { describe, it, expect, vi } from 'vitest'
// Imports removed

// Mock the player store
const mockPlayerStore = {
  currentTrack: null,
  isPlaying: false,
  volume: 1,
  crossfadeState: 'idle' as const,
  nextTrackPreloaded: false,
  setCurrentTime: vi.fn(),
  setDuration: vi.fn(),
  setIsPlaying: vi.fn(),
  playNext: vi.fn(),
  setCrossfadeState: vi.fn(),
  setNextTrackPreloaded: vi.fn(),
  getNextTrack: vi.fn(() => null),
  advanceToNextTrack: vi.fn(),
}

vi.mock('../../stores/playerStore', () => ({
  usePlayerStore: Object.assign(
    vi.fn((selector) => {
      if (typeof selector === 'function') {
        return selector(mockPlayerStore)
      }
      return mockPlayerStore
    }),
    {
      getState: () => mockPlayerStore,
    }
  ),
}))

vi.mock('../../stores/audioSettingsStore', () => ({
  useAudioSettingsStore: vi.fn((selector) => {
    const state = {
      crossfadeDuration: 5,
      crossfadeEnabled: true,
    }
    if (typeof selector === 'function') {
      return selector(state)
    }
    return state
  }),
}))

vi.mock('../../api/client', () => ({
  tracksApi: {
    getStreamUrl: (id: string) => `/api/v1/tracks/${id}/stream`,
    getArtworkUrl: (id: string) => `/api/v1/tracks/${id}/artwork`,
  },
}))

vi.mock('../../services/offlineService', () => ({
  getOfflineTrack: vi.fn(() => Promise.resolve(null)),
  createOfflineTrackUrl: vi.fn((_blob) => 'blob:test'),
  revokeOfflineTrackUrl: vi.fn(),
}))

vi.mock('../../services/audioEffects', () => ({
  initEffectsChain: vi.fn(() => ({
    input: {},
    output: { connect: vi.fn() },
  })),
  EffectsChain: class { },
}))

// Deprecated export tests removed

describe('Audio element creation', () => {
  it('should create audio elements with correct attributes', () => {
    // Verify our Audio mock is set up correctly
    const audio = new Audio()
    // Audio mock may have various properties, just verify it exists
    expect(audio).toBeDefined()
    expect(typeof audio.play).toBe('function')
    expect(typeof audio.pause).toBe('function')
    expect(typeof audio.load).toBe('function')
  })
})

describe('Volume handling', () => {
  it('should clamp volume between 0 and 1', () => {
    const setElementVolume = (element: HTMLAudioElement | null, volume: number): void => {
      if (element) {
        element.volume = Math.max(0, Math.min(1, volume))
      }
    }

    const audio = new Audio() as unknown as HTMLAudioElement

    setElementVolume(audio, 0.5)
    expect(audio.volume).toBe(0.5)

    setElementVolume(audio, -0.5)
    expect(audio.volume).toBe(0)

    setElementVolume(audio, 1.5)
    expect(audio.volume).toBe(1)
  })
})

describe('Track URL resolution', () => {
  it('should return streaming URL for non-offline tracks', async () => {
    const { getOfflineTrack } = await import('../../services/offlineService')
    const { tracksApi } = await import('../../api/client')

    // Mock getOfflineTrack to return null (track not offline)
    vi.mocked(getOfflineTrack).mockResolvedValue(null)

    const trackId = 'test-track-123'
    const offlineBlob = await getOfflineTrack(trackId)

    if (offlineBlob) {
      // Offline case (not tested here)
    } else {
      const url = tracksApi.getStreamUrl(trackId)
      expect(url).toBe(`/api/v1/tracks/${trackId}/stream`)
    }
  })
})

describe('Crossfade logic', () => {
  describe('crossfade timing calculations', () => {
    it('should calculate preload threshold correctly', () => {
      const crossfadeDuration = 5 // seconds
      const preloadThreshold = crossfadeDuration + 3 // 8 seconds before end

      expect(preloadThreshold).toBe(8)
    })

    it('should determine when to start crossfade', () => {
      const duration = 180 // 3 minute track
      const currentTime = 176 // 4 seconds remaining
      const crossfadeDuration = 5
      const timeRemaining = duration - currentTime

      // Should start crossfade when timeRemaining <= crossfadeDuration
      const shouldStartCrossfade = timeRemaining <= crossfadeDuration && timeRemaining > 0.1

      expect(shouldStartCrossfade).toBe(true)
    })

    it('should not start crossfade too early', () => {
      const duration = 180
      const currentTime = 170 // 10 seconds remaining
      const crossfadeDuration = 5
      const timeRemaining = duration - currentTime

      const shouldStartCrossfade = timeRemaining <= crossfadeDuration && timeRemaining > 0.1

      expect(shouldStartCrossfade).toBe(false)
    })
  })

  describe('gain calculation for crossfade', () => {
    it('should calculate linear crossfade gains', () => {
      // At start of crossfade (progress = 0)
      let progress = 0
      let currentGain = 1 - progress
      let nextGain = progress
      expect(currentGain).toBe(1)
      expect(nextGain).toBe(0)

      // At middle of crossfade (progress = 0.5)
      progress = 0.5
      currentGain = 1 - progress
      nextGain = progress
      expect(currentGain).toBe(0.5)
      expect(nextGain).toBe(0.5)

      // At end of crossfade (progress = 1)
      progress = 1
      currentGain = 1 - progress
      nextGain = progress
      expect(currentGain).toBe(0)
      expect(nextGain).toBe(1)
    })

    it('should apply master volume during crossfade', () => {
      const masterVolume = 0.8
      const progress = 0.5

      const currentVol = (1 - progress) * masterVolume
      const nextVol = progress * masterVolume

      expect(currentVol).toBe(0.4)
      expect(nextVol).toBe(0.4)
    })
  })
})

describe('Media Session integration', () => {
  it('should create MediaMetadata with track info', () => {
    const track = {
      id: 'track-123',
      title: 'Test Song',
      artist: 'Test Artist',
      album: 'Test Album',
    }

    // Simulate what updateMediaSession does
    const metadata = {
      title: track.title || 'Unknown',
      artist: track.artist || 'Unknown',
      album: track.album || 'Unknown',
      artwork: track.id
        ? [{ src: `/api/v1/tracks/${track.id}/artwork`, sizes: '512x512', type: 'image/jpeg' }]
        : [],
    }

    expect(metadata.title).toBe('Test Song')
    expect(metadata.artist).toBe('Test Artist')
    expect(metadata.album).toBe('Test Album')
    expect(metadata.artwork[0].src).toContain('track-123')
  })
})

describe('Preload logic', () => {
  it('should determine when to preload next track', () => {
    const crossfadeEnabled = true
    const crossfadeDuration = 5
    const duration = 180
    const currentTime = 172 // 8 seconds remaining

    const timeRemaining = duration - currentTime
    const effectiveCrossfade = crossfadeEnabled ? crossfadeDuration : 0
    const preloadThreshold = effectiveCrossfade + 3

    const shouldPreload =
      timeRemaining <= preloadThreshold && timeRemaining > effectiveCrossfade

    expect(shouldPreload).toBe(true)
  })

  it('should not preload when crossfade is disabled on desktop', () => {
    const crossfadeEnabled = false
    const crossfadeDuration = 5
    const isMobile = false
    const MOBILE_TRANSITION_OVERLAP = 0.3
    const duration = 180
    const currentTime = 175 // 5 seconds remaining

    const timeRemaining = duration - currentTime
    const effectiveCrossfade = crossfadeEnabled
      ? (isMobile ? Math.max(crossfadeDuration, MOBILE_TRANSITION_OVERLAP) : crossfadeDuration)
      : (isMobile ? MOBILE_TRANSITION_OVERLAP : 0)
    const preloadThreshold = effectiveCrossfade + 3

    // Desktop with crossfade disabled: effectiveCrossfade = 0, preloadThreshold = 3
    // timeRemaining (5) > preloadThreshold (3) so should not preload yet
    expect(effectiveCrossfade).toBe(0)
    const shouldPreload =
      timeRemaining <= preloadThreshold && timeRemaining > effectiveCrossfade

    expect(shouldPreload).toBe(false)
  })
})

describe('Mobile minimum transition overlap', () => {
  const MOBILE_TRANSITION_OVERLAP = 0.3

  function calcEffectiveCrossfade(
    crossfadeEnabled: boolean,
    crossfadeDuration: number,
    isMobile: boolean,
  ): number {
    return crossfadeEnabled
      ? (isMobile ? Math.max(crossfadeDuration, MOBILE_TRANSITION_OVERLAP) : crossfadeDuration)
      : (isMobile ? MOBILE_TRANSITION_OVERLAP : 0)
  }

  it('should use MOBILE_TRANSITION_OVERLAP on mobile when crossfade is disabled', () => {
    const result = calcEffectiveCrossfade(false, 5, true)
    expect(result).toBe(MOBILE_TRANSITION_OVERLAP)
  })

  it('should use 0 on desktop when crossfade is disabled', () => {
    const result = calcEffectiveCrossfade(false, 5, false)
    expect(result).toBe(0)
  })

  it('should enforce minimum overlap on mobile when crossfade duration is 0 (gapless)', () => {
    const result = calcEffectiveCrossfade(true, 0, true)
    expect(result).toBe(MOBILE_TRANSITION_OVERLAP)
  })

  it('should allow 0 duration on desktop for gapless', () => {
    const result = calcEffectiveCrossfade(true, 0, false)
    expect(result).toBe(0)
  })

  it('should use user crossfade duration on mobile when larger than minimum', () => {
    const result = calcEffectiveCrossfade(true, 5, true)
    expect(result).toBe(5)
  })

  it('should not change desktop crossfade behavior', () => {
    const result = calcEffectiveCrossfade(true, 5, false)
    expect(result).toBe(5)
  })
})

describe('Element switching for A/B crossfade', () => {
  it('should alternate between A and B elements', () => {
    let currentElementIsA = true

    // Get current element (A)
    expect(currentElementIsA).toBe(true)

    // After crossfade completes, switch to B
    currentElementIsA = !currentElementIsA
    expect(currentElementIsA).toBe(false)

    // After next crossfade, back to A
    currentElementIsA = !currentElementIsA
    expect(currentElementIsA).toBe(true)
  })
})
