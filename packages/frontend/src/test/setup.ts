/**
 * Vitest setup file.
 * Runs before each test file.
 */
import { vi } from 'vitest'
import '@testing-library/jest-dom'

// Mock localStorage
const localStorageMock = {
  getItem: vi.fn(() => null),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
  length: 0,
  key: vi.fn(() => null),
}
Object.defineProperty(window, 'localStorage', { value: localStorageMock })

// Mock Audio API with real event handling
class AudioMock {
  src = ''
  volume = 1
  currentTime = 0
  duration = 0
  paused = true
  muted = false
  loop = false
  readyState = 0
  crossOrigin: string | null = null
  preload = ''
  error: MediaError | null = null
  style = { display: '' }

  private _listeners: Map<string, Set<EventListener>> = new Map()

  play = vi.fn(() => {
    this.paused = false
    // Fire 'playing' asynchronously like a real element
    Promise.resolve().then(() => this.emit('playing'))
    return Promise.resolve()
  })
  pause = vi.fn(() => {
    this.paused = true
  })
  load = vi.fn()
  setAttribute = vi.fn()
  getAttribute = vi.fn((_name: string) => null)

  addEventListener(event: string, handler: EventListener) {
    if (!this._listeners.has(event)) {
      this._listeners.set(event, new Set())
    }
    this._listeners.get(event)!.add(handler)
  }

  removeEventListener(event: string, handler: EventListener) {
    this._listeners.get(event)?.delete(handler)
  }

  /** Trigger an event on this mock element (for use in tests) */
  emit(event: string) {
    const handlers = this._listeners.get(event)
    if (handlers) {
      const evt = { target: this, type: event } as unknown as Event
      handlers.forEach(h => h(evt))
    }
  }
}
Object.defineProperty(window, 'Audio', { value: AudioMock, writable: true })

// Mock matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock IntersectionObserver
class IntersectionObserverMock {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}
Object.defineProperty(window, 'IntersectionObserver', {
  value: IntersectionObserverMock,
})

// Mock ResizeObserver
class ResizeObserverMock {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}
Object.defineProperty(window, 'ResizeObserver', {
  value: ResizeObserverMock,
})

// Mock Web Audio API for useAudioEngine tests
class AudioContextMock {
  state = 'running'
  currentTime = 0
  destination = {}

  createGain = vi.fn(() => ({
    gain: {
      value: 1,
      setValueAtTime: vi.fn(),
      linearRampToValueAtTime: vi.fn(),
      setTargetAtTime: vi.fn(),
      cancelScheduledValues: vi.fn(),
    },
    connect: vi.fn(),
    disconnect: vi.fn(),
  }))

  createAnalyser = vi.fn(() => ({
    fftSize: 256,
    smoothingTimeConstant: 0.8,
    connect: vi.fn(),
    disconnect: vi.fn(),
    getByteFrequencyData: vi.fn(),
    getByteTimeDomainData: vi.fn(),
  }))

  createMediaElementSource = vi.fn(() => ({
    connect: vi.fn(),
    disconnect: vi.fn(),
  }))

  resume = vi.fn(() => Promise.resolve())
  suspend = vi.fn(() => Promise.resolve())
  close = vi.fn(() => Promise.resolve())
}

Object.defineProperty(window, 'AudioContext', {
  value: AudioContextMock,
  writable: true,
})

Object.defineProperty(window, 'webkitAudioContext', {
  value: AudioContextMock,
  writable: true,
})

// Mock MediaSession API
Object.defineProperty(navigator, 'mediaSession', {
  value: {
    metadata: null,
    playbackState: 'none',
    setActionHandler: vi.fn(),
    setPositionState: vi.fn(),
  },
  writable: true,
})

// Mock MediaMetadata
class MediaMetadataMock {
  title = ''
  artist = ''
  album = ''
  artwork: { src: string; sizes: string; type: string }[] = []

  constructor(init?: {
    title?: string
    artist?: string
    album?: string
    artwork?: { src: string; sizes: string; type: string }[]
  }) {
    if (init) {
      this.title = init.title || ''
      this.artist = init.artist || ''
      this.album = init.album || ''
      this.artwork = init.artwork || []
    }
  }
}

Object.defineProperty(window, 'MediaMetadata', {
  value: MediaMetadataMock,
  writable: true,
})

// Mock indexedDB. Nothing in the app uses it since ADR-0071 removed the Dexie store; this
// stays so a stray access in jsdom fails predictably rather than throwing on an undefined global.
const indexedDBMock = {
  open: vi.fn(() => {
    const request = {
      onerror: null as ((event: Event) => void) | null,
      onsuccess: null as ((event: Event) => void) | null,
      result: {
        close: vi.fn(),
      },
    }
    setTimeout(() => {
      if (request.onsuccess) {
        request.onsuccess({} as Event)
      }
    }, 0)
    return request
  }),
  deleteDatabase: vi.fn(() => ({
    onerror: null,
    onsuccess: null,
  })),
}

Object.defineProperty(window, 'indexedDB', {
  value: indexedDBMock,
  writable: true,
})
