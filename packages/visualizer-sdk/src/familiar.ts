/**
 * The host bridge (ADR-0087 point 2, shared under ADR-0125).
 *
 * The host lends a plugin nothing, so a visualizer that wants audio, a track or a palette provides
 * those itself from the three events it receives. This module is that. It was copied into each
 * first-party visualizer as "~90 lines a plugin author would write once" — and at four copies the
 * lines had become a false public contract, where a fix applied to three of them left the fourth
 * reading the same event differently (ADR-0125 Context). It is one implementation now, bundled
 * into every document that imports it: the host still serves no shared JavaScript.
 *
 * **The protocol is the contract, not this file** (ADR-0125 point 3). `docs/VISUALIZER_API.md` is
 * normative; a vanilla document that handles the four events itself is a complete visualizer.
 */
import { useEffect, useState } from 'react';

import type { LyricLine, TrackFeatures } from './types';

/** The protocol version this bridge speaks. Messages carrying another are ignored, once loudly. */
export const API_VERSION = 1;

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
  features: TrackFeatures | null;
  lyrics: LyricLine[] | null;
}

export interface PlaybackState {
  isPlaying: boolean;
  currentTime: number;
}

const EMPTY: AudioData = {
  bass: 0, mid: 0, treble: 0, averageFrequency: 0, frequencyData: new Uint8Array(64),
  beat: 0, onset: false,
};

let latest: AudioData = EMPTY;
let track: TrackInfo | null = null;
let state: PlaybackState = { isPlaying: false, currentTime: 0 };
let warnedVersion: unknown = undefined;

const trackListeners = new Set<(t: TrackInfo | null) => void>();
const stateListeners = new Set<(s: PlaybackState) => void>();

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function number(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

/**
 * Handle one message from the host. Exported so the SDK's tests can drive it with recorded event
 * shapes; a document never calls it — `install()` below wires it to `window`.
 *
 * Malformed input is dropped, never thrown on: this runs inside `window`'s message listener, and a
 * throw there is invisible in a sandboxed frame. A host that sends a payload this bridge does not
 * understand gets the last good value kept, not a scene that silently stops updating.
 */
export function handleMessage(data: unknown): void {
  if (!isRecord(data) || typeof data.type !== 'string' || !data.type.startsWith('familiar:')) return;

  // Absent means 1: hosts before the field existed. Present and different means a protocol this
  // bridge does not speak; ignoring it beats misreading it, and saying so once beats silence.
  const version = data.apiVersion ?? API_VERSION;
  if (version !== API_VERSION) {
    if (warnedVersion !== version) {
      warnedVersion = version;
      console.warn(`[familiar] ignoring ${data.type}: apiVersion ${String(version)}, this document speaks ${API_VERSION}`);
    }
    return;
  }

  const p = data.payload;
  switch (data.type) {
    case 'familiar:audio': {
      if (!isRecord(p)) return;
      latest = {
        bass: number(p.bass), mid: number(p.mid), treble: number(p.treble),
        averageFrequency: number(p.averageFrequency),
        // Defaulted rather than assumed present: a plugin built against this bridge should keep
        // working on an older host that does not send them yet.
        beat: number(p.beat),
        onset: p.onset === true,
        frequencyData: Array.isArray(p.frequencyData) || p.frequencyData instanceof Uint8Array
          ? Uint8Array.from(p.frequencyData as ArrayLike<number>)
          : latest.frequencyData,
      };
      break;
    }
    case 'familiar:track':
      // `null` is a real value: the queue emptied.
      if (p !== null && !isRecord(p)) return;
      track = p as TrackInfo | null;
      trackListeners.forEach((l) => l(track));
      break;
    case 'familiar:state':
      if (!isRecord(p)) return;
      state = { isPlaying: p.isPlaying === true, currentTime: number(p.currentTime) };
      stateListeners.forEach((l) => l(state));
      break;
    case 'familiar:capture':
      // The host's probe asks for one frame of what is on screen (see `takeCaptureRequest`).
      captureRequested = true;
      break;
    default:
      // A message type this bridge does not know. Not an error: the host may add one.
      break;
  }
}

let installed = false;

/**
 * The probe (`familiar` 1.7 work): what a document can tell the host about what it is drawing.
 *
 * The host cannot see inside a sandboxed document, and a test harness renders on another engine
 * with made-up audio. Beat Tiles was tuned twice against such renders and the phone showed
 * something else both times. So a document reports a few numbers with its frame rate (`setStat`),
 * and hands back a frame on request: the host's probe mode asks with `familiar:capture`, and the
 * renderer answers `familiar:frame` after its next draw (`takeCaptureRequest`). Outside probe mode
 * nothing asks, and this costs one extra key in a once-a-second message.
 */
let captureRequested = false;
const stats: Record<string, number> = {};

/** Report a number with the frame rate, e.g. the bloom strength actually in use. */
export function setStat(name: string, value: number): void {
  if (Number.isFinite(value)) stats[name] = Math.round(value * 1000) / 1000;
}

/**
 * True once per `familiar:capture`. Call right after drawing, in the same task: a WebGL canvas
 * without `preserveDrawingBuffer` reads back blank once the frame has been presented.
 */
export function takeCaptureRequest(): boolean {
  if (!captureRequested) return false;
  captureRequested = false;
  return true;
}

/** Send a frame of `canvas` to the host, scaled to at most `maxWidth` CSS pixels wide. */
export function sendCapture(canvas: HTMLCanvasElement, maxWidth = 390): void {
  try {
    const scale = Math.min(1, maxWidth / canvas.width);
    const out = document.createElement('canvas');
    out.width = Math.max(1, Math.round(canvas.width * scale));
    out.height = Math.max(1, Math.round(canvas.height * scale));
    out.getContext('2d')?.drawImage(canvas, 0, 0, out.width, out.height);
    parent.postMessage(
      {
        type: 'familiar:frame',
        apiVersion: API_VERSION,
        payload: {
          image: out.toDataURL('image/jpeg', 0.85),
          canvasWidth: canvas.width,
          canvasHeight: canvas.height,
          devicePixelRatio: window.devicePixelRatio,
          stats: { ...stats },
        },
      },
      '*'
    );
  } catch {
    // A capture is a diagnostic. Never let it take the scene down.
  }
}

/** Attach the bridge to `window`. Idempotent; called for you by `announceReady`. */
export function install(): void {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  window.addEventListener('message', (event: MessageEvent) => handleMessage(event.data));
}

install();

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
    // Whatever arrived between the first render and this effect.
    setValue(track);
    return () => { trackListeners.delete(setValue); };
  }, []);
  return value;
}

export function usePlaybackState(): PlaybackState {
  const [value, setValue] = useState(state);
  useEffect(() => {
    stateListeners.add(setValue);
    setValue(state);
    return () => { stateListeners.delete(setValue); };
  }, []);
  return value;
}

/**
 * Report this document's frame rate to the host, once a second (ADR-0087, optional).
 *
 * **Optional in the strongest sense**: a plugin that omits it loses nothing, and the host's debug
 * panel simply shows a dash. It exists because the host *cannot* measure this — a sandboxed
 * document has an opaque origin, so nothing outside can count its frames — and it is the one rate
 * that matches what a person actually sees. The pipeline can be running at 60 while the scene
 * crawls.
 *
 * Started by `announceReady`, so a plugin using this bridge gets it without doing anything.
 */
function reportFrameRate(): void {
  let frames = 0;
  let since = performance.now();
  const tick = () => {
    frames++;
    const now = performance.now();
    if (now - since >= 1000) {
      parent.postMessage(
        {
          type: 'familiar:stats',
          apiVersion: API_VERSION,
          payload: { fps: Math.round((frames * 1000) / (now - since)), ...stats },
        },
        '*'
      );
      frames = 0;
      since = now;
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/** Tell the host this document is listening. Must be last, after the listener is attached. */
export function announceReady(): void {
  install();
  reportFrameRate();
  parent.postMessage({ type: 'familiar:ready', apiVersion: API_VERSION }, '*');
}

/** Glow was a host setting; a plugin decides for itself now. */
export const GLOW_LEVEL = 50;

/** For tests: forget everything received. */
export function _reset(): void {
  latest = EMPTY;
  track = null;
  state = { isPlaying: false, currentTime: 0 };
  warnedVersion = undefined;
  captureRequested = false;
  for (const key of Object.keys(stats)) delete stats[key];
}
