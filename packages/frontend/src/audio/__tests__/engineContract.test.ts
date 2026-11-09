/// The engine contract, minus the engine that is gone.
//
// This used to run the same suite against `CapacitorEngine` and then assert a further eleven
// Capacitor-specific behaviours — a test in the *shared* package importing
// `../../../../../ios/src/CapacitorEngine`, five directories up and into another workspace package.
// That reach is why deleting `packages/ios` did not show up in a grep for "packages/ios": the path
// was relative. The Capacitor app is retired (ADR-0001 point 6) and its assertions went with it.
//
// What stays is the part that was never about Capacitor: a contract any `AudioEngine` must satisfy,
// run against a fake. The next engine to exist is what it is for.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AudioEngine, AudioEngineCapabilities, EngineEvent } from '../types';

class WebLikeAdapter implements AudioEngine {
  readonly capabilities: AudioEngineCapabilities = { crossfade: true, visualizer: false, effects: 'none' };
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
