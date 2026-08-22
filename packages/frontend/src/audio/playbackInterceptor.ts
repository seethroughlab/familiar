import type { Track } from '../types';

/**
 * Lets a host take over playback instead of this app performing it.
 *
 * **Why this exists.** The embedded surface (ADR-0016/0017) runs inside a `WKWebView` in the Mac
 * app and must never play audio itself — every play action belongs to the native `FamiliarPlayer`.
 * `EmbedDiscover` wires the `onPlayTrack` prop to the bridge, and that turned out to catch only some
 * of it: `DiscoverTrackList` never calls `onPlayTrack`, it drives `usePlayerStore.setQueueByTrackId`
 * directly. So pressing a track in "Unheard in Your Library" posted no intent, set a local queue,
 * and handed it to a null audio engine — which correctly did nothing, and left the row spinning
 * forever waiting for a load that would never report.
 *
 * A prop can be missed. This cannot: the store is where every play path in the app converges, so
 * intercepting here catches the ones nobody has written yet. It is the same argument ADR-0020 makes
 * for the null engine being a floor under the bridge rather than a substitute for it.
 *
 * Registration-based, matching `registerEngineFactory` and `registerProfileProvider` — the app's
 * existing idiom for behaviour only one platform entry point supplies.
 */

/** What the host is asked to play: the whole context, and where in it to start. */
export interface PlaybackIntent {
  tracks: Track[];
  startingAt: string;
}

/** Returns true when the host has taken the request and this app should do nothing further. */
export type PlaybackInterceptor = (intent: PlaybackIntent) => boolean;

let interceptor: PlaybackInterceptor | null = null;

/**
 * Hand playback to a host. Registered only by the embedded entry point; the ordinary web app and
 * the iOS app never call this, so `intercept` below is a null check for them.
 */
export function registerPlaybackInterceptor(fn: PlaybackInterceptor): void {
  interceptor = fn;
}

/**
 * Offer a play request to the host, if there is one.
 *
 * `false` means "nobody took it, carry on" — which is what every ordinary browser and the iOS app
 * always get.
 */
export function interceptPlayback(tracks: Track[], startingAt: string | undefined): boolean {
  if (!interceptor || tracks.length === 0) return false;
  const start = startingAt && tracks.some((t) => t.id === startingAt) ? startingAt : tracks[0].id;
  return interceptor({ tracks, startingAt: start });
}

/** Test-only. */
export function resetPlaybackInterceptorForTesting(): void {
  interceptor = null;
}
