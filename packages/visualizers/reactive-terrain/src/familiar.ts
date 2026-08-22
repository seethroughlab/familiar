/**
 * The host contract, implemented locally (ADR-0087 point 2).
 *
 * The host lends a plugin nothing, so a visualizer that wants audio, a track or a palette provides
 * those itself from the three events it receives. This module is that: the same shapes the
 * in-repo visualizers used to import from the host, backed by `postMessage` instead.
 *
 * It is deliberately not a library. It is ~90 lines a plugin author would write once and is here to
 * be read as the worked example of what the contract costs.
 */
import { useEffect, useState } from 'react';

export interface AudioData {
  bass: number;
  mid: number;
  treble: number;
  averageFrequency: number;
  frequencyData: Uint8Array;
  /** Decaying beat envelope, 0–1: spikes on an onset, then falls away. */
  beat: number;
  /** True only on the single frame a transient is detected. */
  onset: boolean;
}

export interface TrackInfo {
  id: string | null;
  title: string | null;
  artist: string | null;
  album: string | null;
  artworkUrl: string | null;
  duration: number;
  features: Record<string, unknown> | null;
  lyrics: unknown[] | null;
}

const EMPTY: AudioData = {
  bass: 0, mid: 0, treble: 0, averageFrequency: 0, frequencyData: new Uint8Array(64),
  beat: 0, onset: false,
};

let latest: AudioData = EMPTY;
let track: TrackInfo | null = null;
let state = { isPlaying: false, currentTime: 0 };

const trackListeners = new Set<(t: TrackInfo | null) => void>();
const stateListeners = new Set<(s: typeof state) => void>();

window.addEventListener('message', (event: MessageEvent) => {
  const message = event.data;
  if (!message || typeof message !== 'object') return;

  switch (message.type) {
    case 'familiar:audio': {
      const p = message.payload;
      latest = {
        bass: p.bass, mid: p.mid, treble: p.treble,
        averageFrequency: p.averageFrequency,
        // Defaulted rather than assumed present: a plugin built against this shim should keep
        // working on an older host that does not send them yet.
        beat: p.beat ?? 0,
        onset: p.onset ?? false,
        frequencyData: Uint8Array.from(p.frequencyData ?? []),
      };
      break;
    }
    case 'familiar:track':
      track = message.payload;
      trackListeners.forEach((l) => l(track));
      break;
    case 'familiar:state':
      state = message.payload;
      stateListeners.forEach((l) => l(state));
      break;
  }
});

/** The most recent analysis frame. Already interpolated by the host against its render loop. */
export function getAudioData(): AudioData {
  return latest;
}

/** Kept for shape-compatibility with the host hook the in-repo version used. A no-op here. */
export function useAudioAnalyser(_enabled?: boolean): AudioData {
  return latest;
}

export function useTrack(): TrackInfo | null {
  const [value, setValue] = useState(track);
  useEffect(() => {
    trackListeners.add(setValue);
    return () => { trackListeners.delete(setValue); };
  }, []);
  return value;
}

export function usePlaybackState() {
  const [value, setValue] = useState(state);
  useEffect(() => {
    stateListeners.add(setValue);
    return () => { stateListeners.delete(setValue); };
  }, []);
  return value;
}

/** Tell the host this document is listening. Must be last, after the listener is attached. */
/**
 * Report this document's frame rate to the host, once a second (ADR-0087, optional).
 *
 * **Optional in the strongest sense**: a plugin that omits it loses nothing, and the host's debug
 * panel simply shows a dash. It exists because the host *cannot* measure this — a sandboxed
 * document has an opaque origin, so nothing outside can count its frames — and it is the one rate
 * that matches what a person actually sees. The pipeline can be running at 60 while the scene
 * crawls.
 *
 * Started by `announceReady`, so a plugin using this shim gets it without doing anything.
 */
function reportFrameRate(): void {
  let frames = 0;
  let since = performance.now();
  const tick = () => {
    frames++;
    const now = performance.now();
    if (now - since >= 1000) {
      parent.postMessage(
        { type: 'familiar:stats', apiVersion: 1, payload: { fps: Math.round((frames * 1000) / (now - since)) } },
        '*'
      );
      frames = 0;
      since = now;
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

export function announceReady(): void {
  reportFrameRate();
  parent.postMessage({ type: 'familiar:ready', apiVersion: 1 }, '*');
}

/** Glow was a host setting; a plugin decides for itself now. */
export const GLOW_LEVEL = 50;
