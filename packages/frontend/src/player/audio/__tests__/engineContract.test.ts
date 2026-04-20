import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AudioEngine, EngineEvent } from '../types';
import { CapacitorEngine } from '../../../../../ios/src/CapacitorEngine';
import type { FamiliarAudioPlugin } from '../../../../../ios/src/plugins/familiarAudio';

vi.hoisted(() => {
  const g = globalThis as unknown as { window?: Record<string, unknown> };
  if (!g.window) {
    g.window = {};
  }
  g.window.Capacitor = {
    isNativePlatform: () => true,
  };
});

const familiarAudioMock = vi.hoisted(() => {
  const listeners = new Map<string, Set<(data?: unknown) => void>>();
  type CrossfadeResult = Awaited<ReturnType<FamiliarAudioPlugin['executeCrossfade']>>;
  return {
  load: vi.fn(async () => {}),
  loadLocal: vi.fn(async () => {}),
  play: vi.fn(async () => {}),
  pause: vi.fn(async () => {}),
  seek: vi.fn(async () => {}),
  stop: vi.fn(async () => {}),
  setVolume: vi.fn(async () => {}),
  getDuration: vi.fn(async () => ({ duration: 180 })),
  preloadNext: vi.fn(async () => ({ success: true, state: 'ready' })),
  preloadNextLocal: vi.fn(async () => ({ success: true, state: 'ready' })),
  isNextReady: vi.fn(async () => ({ ready: true })),
  getPreloadingTrackId: vi.fn(async () => ({ trackId: null })),
  isCrossfading: vi.fn(async () => ({ crossfading: false })),
  executeCrossfade: vi.fn(async (): Promise<CrossfadeResult> => ({ success: true })),
  cancelCrossfade: vi.fn(async () => {}),
  setNextNormalizationVolume: vi.fn(async () => {}),
  setNowPlayingInfo: vi.fn(async () => {}),
  setPendingTrackInfo: vi.fn(async () => {}),
  addListener: vi.fn(async (event: string, handler: (data?: unknown) => void) => {
    if (!listeners.has(event)) listeners.set(event, new Set());
    listeners.get(event)!.add(handler);
    return {
      remove: vi.fn(() => {
        listeners.get(event)?.delete(handler);
      }),
    };
  }),
  __emit(event: string, data?: unknown) {
    listeners.get(event)?.forEach((handler) => handler(data));
  },
  __resetListeners() {
    listeners.clear();
  },
};
});

vi.mock('../../../../../ios/src/plugins/familiarAudio', () => ({
  FamiliarAudio: familiarAudioMock,
}));

vi.mock('@familiar/frontend/src/services/offlineService', () => ({
  getOfflineTrackNativeUri: vi.fn(async () => null),
}));

vi.mock('@familiar/frontend/src/api', () => ({
  tracksApi: {
    getStreamUrl: (id: string) => `/api/v1/tracks/${id}/stream`,
  },
}));

class WebLikeAdapter implements AudioEngine {
  readonly capabilities = { crossfade: true };
  private loadedTrackId: string | null = null;
  private handlers = new Set<(event: EngineEvent) => void>();
  initialize(): boolean { return true; }
  dispose(): void { this.handlers.clear(); }
  async load(trackId: string): Promise<void> { this.loadedTrackId = trackId; }
  async play(): Promise<void> {}
  pause(): void {}
  seek(): void {}
  stop(): void { this.loadedTrackId = null; }
  setVolume(): void {}
  setNormalizationGain(): void {}
  getCurrentTime(): number { return 0; }
  getDuration(): number { return 180; }
  getLoadedTrackId(): string | null { return this.loadedTrackId; }
  on(handler: (event: EngineEvent) => void): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }
  updateNowPlaying(): void {}
  async preloadNext(trackId: string): Promise<boolean> { return !!trackId; }
  isNextReady(): boolean { return true; }
  executeCrossfade(_duration: number, onComplete: () => void): void {
    onComplete();
  }
}

function runContractSuite(name: string, factory: () => AudioEngine) {
  describe(name, () => {
    let engine: AudioEngine;

    beforeEach(() => {
      engine = factory();
    });

    it('initializes and loads track', async () => {
      expect(engine.initialize()).toBe(true);
      await engine.load('t1', '/tmp/t1.mp3');
      expect(engine.getLoadedTrackId()).toBe('t1');
    });

    it('exposes crossfade behavior consistently', async () => {
      await engine.load('t1', '/tmp/t1.mp3');
      const preloaded = await engine.preloadNext?.('t2', '/tmp/t2.mp3');
      expect(preloaded).toBe(true);

      const completed = await new Promise<boolean>((resolve) => {
        engine.executeCrossfade?.(2, () => resolve(true));
      });
      expect(completed).toBe(true);
    });

    it('publishes and unsubscribes engine events', () => {
      const handler = vi.fn();
      const unsubscribe = engine.on(handler);
      unsubscribe();
      expect(handler).not.toHaveBeenCalled();
    });
  });
}

runContractSuite('Web-like Engine Contract', () => new WebLikeAdapter());
runContractSuite('Capacitor Engine Contract', () => new CapacitorEngine());

describe('Capacitor Engine Parity Behaviors', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    familiarAudioMock.__resetListeners();
  });

  it('uses loadLocal for file:// URLs', async () => {
    const engine = new CapacitorEngine();
    await engine.load('t-local', 'file:///tmp/track.mp3');
    expect(familiarAudioMock.loadLocal).toHaveBeenCalledWith({ path: 'file:///tmp/track.mp3', trackId: 't-local' });
    expect(familiarAudioMock.load).not.toHaveBeenCalled();
  });

  it('completes crossfade callback even when native rejects', async () => {
    familiarAudioMock.executeCrossfade.mockResolvedValueOnce({ success: false, reason: 'preload-not-ready' });
    const engine = new CapacitorEngine();
    let completed = false;
    await new Promise<void>((resolve) => {
      engine.executeCrossfade(2, () => {
        completed = true;
        resolve();
      });
    });
    expect(completed).toBe(true);
  });

  it('maps pending track metadata fields to plugin payload', () => {
    const engine = new CapacitorEngine();
    engine.syncPendingTracks({
      next: {
        url: 'https://example.com/next.mp3',
        trackId: 'next-1',
        title: 'Next Track',
        artist: 'Next Artist',
        album: 'Next Album',
        artworkUrl: 'https://example.com/next.jpg',
      },
      previous: {
        url: 'https://example.com/prev.mp3',
        trackId: 'prev-1',
        title: 'Prev Track',
        artist: 'Prev Artist',
        album: 'Prev Album',
        artworkUrl: 'https://example.com/prev.jpg',
      },
    });

    expect(familiarAudioMock.setPendingTrackInfo).toHaveBeenCalledWith({
      nextUrl: 'https://example.com/next.mp3',
      nextTrackId: 'next-1',
      nextTitle: 'Next Track',
      nextArtist: 'Next Artist',
      nextAlbum: 'Next Album',
      nextArtworkUrl: 'https://example.com/next.jpg',
      prevUrl: 'https://example.com/prev.mp3',
      prevTrackId: 'prev-1',
      prevTitle: 'Prev Track',
      prevArtist: 'Prev Artist',
      prevAlbum: 'Prev Album',
      prevArtworkUrl: 'https://example.com/prev.jpg',
    });
  });

  it('emits remotePrevious restart action from plugin event', () => {
    const engine = new CapacitorEngine();
    const handler = vi.fn();
    engine.initialize();
    engine.on(handler);

    familiarAudioMock.__emit('remotePrevious', { nativeAction: 'restart', loadedTrackId: 'prev-1' });

    expect(handler).toHaveBeenCalledWith({
      type: 'remotePrevious',
      nativeAction: 'restart',
    });
    expect(engine.getLoadedTrackId()).toBe('prev-1');
  });

  it('maps native error categories to EngineEvent codes', () => {
    const engine = new CapacitorEngine();
    const handler = vi.fn();
    engine.initialize();
    engine.on(handler);

    familiarAudioMock.__emit('error', { message: 'Network down', category: 'network' });
    familiarAudioMock.__emit('error', { message: 'Decode failed', category: 'decode' });
    familiarAudioMock.__emit('error', { message: 'State failed', category: 'state' });
    familiarAudioMock.__emit('error', { message: 'Resource missing', category: 'resource' });

    expect(handler).toHaveBeenCalledWith(expect.objectContaining({ type: 'error', code: 'network-unreachable' }));
    expect(handler).toHaveBeenCalledWith(expect.objectContaining({ type: 'error', code: 'media-decode' }));
    expect(handler).toHaveBeenCalledWith(expect.objectContaining({ type: 'error', code: 'state' }));
    expect(handler).toHaveBeenCalledWith(expect.objectContaining({ type: 'error', code: 'resource' }));
  });

  it('emits remote command fallback events when native load is not completed', () => {
    const engine = new CapacitorEngine();
    const handler = vi.fn();
    engine.initialize();
    engine.on(handler);

    familiarAudioMock.__emit('remoteNext', {});
    familiarAudioMock.__emit('remotePrevious', {});

    expect(handler).toHaveBeenCalledWith({ type: 'remoteNext' });
    expect(handler).toHaveBeenCalledWith({ type: 'remotePrevious', nativeAction: undefined });
  });
});
