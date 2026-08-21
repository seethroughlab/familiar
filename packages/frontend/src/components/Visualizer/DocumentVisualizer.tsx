/**
 * Mounts a document-shaped visualizer and feeds it (ADR-0087 points 1 and 2).
 *
 * A visualizer is a folder with an `index.html`. This renders that document in a **sandboxed
 * iframe** and posts it four things — three inbound events and one handshake back. It lends the
 * plugin nothing: no React, no THREE, no globals. Whatever the document is built from is its own
 * business, which is the whole point of the decision.
 *
 * **`sandbox="allow-scripts"` and deliberately not `allow-same-origin`.** That gives the document
 * an opaque origin: no cookies, no `localStorage`, no reach into this page's DOM. It was spiked
 * against a real `WKWebView` before this was written, because a custom scheme plus an opaque origin
 * is where a surprise would hide — subresources load, both directions of `postMessage` work, and
 * the host DOM is unreachable. ADR-0087's Implementation records the measurement.
 *
 * **Sandbox does not restrict network.** A plugin can still `fetch()` anywhere. Confining that
 * wants a `Content-Security-Policy` on the document, which the thing serving it is in a position to
 * attach; it is an open decision rather than something this file has solved.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Track, TrackFeatures } from '../../types';
import type { LyricLine } from '../../api';
import { getAudioData, useAudioAnalyser } from './hooks';

export interface DocumentVisualizerProps {
  /** URL of the plugin's `index.html`. */
  src: string;
  track: Track | null;
  features: TrackFeatures | null;
  artworkUrl: string | null;
  lyrics: LyricLine[] | null;
  currentTime: number;
  duration: number;
  isPlaying: boolean;
  className?: string;
}

/** Every message this host will send. The whole outbound contract. */
export type HostMessage =
  | { type: 'familiar:track'; payload: TrackPayload }
  | { type: 'familiar:state'; payload: StatePayload }
  | { type: 'familiar:audio'; payload: AudioPayload };

export interface TrackPayload {
  id: string | null;
  title: string | null;
  artist: string | null;
  album: string | null;
  artworkUrl: string | null;
  duration: number;
  features: TrackFeatures | null;
  lyrics: LyricLine[] | null;
}

export interface StatePayload {
  isPlaying: boolean;
  currentTime: number;
}

export interface AudioPayload {
  bass: number;
  mid: number;
  treble: number;
  averageFrequency: number;
  frequencyData: number[];
}

/** The one message a plugin sends back. */
export const READY = 'familiar:ready';

/** Version of the *event* contract, not of any library (ADR-0087 point 9). */
export const EVENT_API_VERSION = 1;

function trackPayload(
  track: Track | null,
  features: TrackFeatures | null,
  artworkUrl: string | null,
  lyrics: LyricLine[] | null,
  duration: number
): TrackPayload {
  return {
    id: track?.id ?? null,
    title: track?.title ?? null,
    artist: track?.artist ?? null,
    album: track?.album ?? null,
    artworkUrl,
    duration,
    features,
    lyrics,
  };
}

export function DocumentVisualizer({
  src,
  track,
  features,
  artworkUrl,
  lyrics,
  currentTime,
  duration,
  isPlaying,
  className = '',
}: DocumentVisualizerProps) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);

  // Reset on navigation: a different document has not said it is listening yet.
  useEffect(() => { setReady(false); }, [src]);

  const send = useCallback((message: HostMessage) => {
    const target = frameRef.current?.contentWindow;
    // `'*'` because the document has an opaque origin — there is no origin string that would
    // match it, so a targeted post would silently never arrive. The payloads are the same data
    // the plugin is being shown anyway; nothing here is a secret to withhold from it.
    target?.postMessage({ ...message, apiVersion: EVENT_API_VERSION }, '*');
  }, []);

  // The handshake. Without it the host would talk to a document that has not attached a listener
  // yet, and the first track of a session would silently never arrive.
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      // Only this iframe. An opaque origin cannot be checked by string, so identity is the check.
      if (event.source !== frameRef.current?.contentWindow) return;
      const data = event.data as { type?: unknown } | null;
      if (data && typeof data === 'object' && data.type === READY) setReady(true);
    }
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  // Track — sent on ready, and whenever the track (or what is known about it) changes.
  useEffect(() => {
    if (!ready) return;
    send({ type: 'familiar:track', payload: trackPayload(track, features, artworkUrl, lyrics, duration) });
  }, [ready, send, track, features, artworkUrl, lyrics, duration]);

  // Transport. `currentTime` moves constantly, so this fires often; it is two numbers.
  useEffect(() => {
    if (!ready) return;
    send({ type: 'familiar:state', payload: { isPlaying, currentTime } });
  }, [ready, send, isPlaying, currentTime]);

  // **Subscribe, don't just read.** `getAudioData()` is a getter over a buffer that only moves while
  // the singleton analysis loop is running, and that loop is reference-counted by this hook: "the
  // first subscriber starts the singleton rAF loop; the last unsubscriber stops it."
  //
  // Every visualizer used to be a React component that called this itself, so the loop always had a
  // subscriber. A document does not — it is in an iframe and cannot call a hook — so when the
  // registry went, the surface was left with a reader and no subscriber. The buffer never filled,
  // every plugin received nothing, and `spectrum`, which draws only what it is sent, rendered a
  // black rectangle. Nothing errored anywhere.
  //
  // The return value is ignored on purpose: the frames are read below at animation rate, not
  // through React.
  useAudioAnalyser(true);

  // Audio frames, on the host's animation loop.
  //
  // **Interpolated rather than raw.** Frames arrive from a native host at 10 Hz and `getAudioData`
  // already reconstructs a 60 Hz signal from them. ADR-0087's Consequences anticipated handing the
  // plugin the raw feed and making it own that; sending the reconstructed value instead costs
  // nothing here and spares every plugin author the same piece of work.
  useEffect(() => {
    if (!ready) return;
    let raf = 0;
    const tick = () => {
      const data = getAudioData();
      if (data) {
        send({
          type: 'familiar:audio',
          payload: {
            bass: data.bass,
            mid: data.mid,
            treble: data.treble,
            averageFrequency: data.averageFrequency,
            // A plain array: structured clone handles typed arrays, but a plugin that JSON-parses
            // its way through a framework boundary gets an object with numeric keys instead.
            frequencyData: Array.from(data.frequencyData ?? []),
          },
        });
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [ready, send]);

  return (
    <iframe
      ref={frameRef}
      src={src}
      title="Visualizer"
      // No `allow-same-origin`: see the note at the top of this file.
      sandbox="allow-scripts"
      // **`absolute inset-0`, not `h-full`.** A percentage height is indeterminate unless every
      // ancestor has a definite one, and an iframe whose height cannot be resolved falls back to
      // its intrinsic 150px rather than to zero — so the failure is a short strip of visualizer at
      // the top of the window, which looks like a broken plugin rather than a broken layout.
      // Anchoring to the edges removes the whole class: it depends on the positioned ancestor
      // existing, not on an unbroken chain of heights.
      className={`absolute inset-0 w-full h-full border-0 block ${className}`}
    />
  );
}
