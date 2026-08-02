/**
 * The page half of the embedded surface's bridge to the native player (ADR-0016 point 5).
 *
 * One message shape, one direction. The page posts an intent — play these track ids, starting at
 * this one — and the native side owns the queue, the playback and the reporting. Nothing comes back:
 * the web view is never told what is playing and never renders a transport, so there is one player,
 * one queue and one now-playing entry, exactly as with CarPlay.
 *
 * Narrow on purpose. ADR-0016 records the tradeoff this creates — a new seam between two clients
 * that were previously independent, where a web-app change could break the native app — and argues
 * it stays unlikely only if the seam is one message wide. Adding a second shape is a decision, not a
 * detail.
 */

/**
 * Open an artist or an album in the *app*, not in the page (ADR-0020).
 *
 * Addressed by name because that is what the API offers — `/library/artists/{artist_name}` and
 * `/library/albums/{artist_name}/{album_name}`. Names containing a slash cannot be addressed, and
 * the native side already degrades those to a filtered track list rather than failing; this inherits
 * that rather than inventing a second answer.
 */
export interface NavigateIntent {
  type: 'navigate';
  to: 'artist' | 'album';
  artist: string;
  /** Present only for `to: 'album'`. */
  album?: string;
}

/** What the native side receives. Keep this in step with the Swift `WKScriptMessageHandler`. */
export interface PlayIntent {
  type: 'play';
  /** The full context to queue, in order. */
  trackIds: string[];
  /** Which of them to start on. Always a member of `trackIds`. */
  startingAt: string;
}

/** The handler name the native side installs. */
export const BRIDGE_HANDLER = 'familiar';

/**
 * The marker `embed.html` carries so a native host can tell this document from the app's.
 *
 * Load-bearing rather than cosmetic. A server built before the `/embed` route existed answers that
 * path from its single-page-app fallback — HTTP 200, `index.html`, the whole web app with
 * `WebAudioEngine` registered. A native host that trusted the URL would embed the very thing
 * ADR-0016 point 4 forbids, and nothing would look wrong: the page would just play audio itself and
 * never use the bridge.
 */
export const SURFACE_MARKER = 'embed';
export const SURFACE_META_NAME = 'familiar-surface';

/** Whether the document currently loaded is the embedded surface. */
export function isEmbedSurfaceDocument(doc: Document = document): boolean {
  const meta = doc.querySelector(`meta[name="${SURFACE_META_NAME}"]`);
  return meta?.getAttribute('content') === SURFACE_MARKER;
}

/**
 * The profile this surface acts as, taken from the URL and nowhere else (ADR-0016 point 6).
 *
 * The native app appends `?profile=…` when it points its web view here. Reading it from the query
 * string rather than from storage is the whole of that decision: a `WKWebView` has its own
 * `localStorage`, separate from any browser, so whatever it found there would be either empty or
 * left over from a previous listener — and a surface acting as a different profile than the window
 * around it is a bug nobody would think to look for.
 *
 * Absent means **no profile**, not "fall back to storage". Falling back would reintroduce exactly
 * the failure this prevents, and do it silently.
 *
 * The server URL needs no equivalent: the document is served *by* that server, so relative API
 * paths can only reach the one it came from. Point 6 is satisfied for the URL by construction.
 */
export function profileFromURL(search: string = window.location.search): string | null {
  const value = new URLSearchParams(search).get('profile');
  return value !== null && value.trim() !== '' ? value : null;
}

interface WebKitBridgeWindow {
  webkit?: {
    messageHandlers?: Record<string, { postMessage: (message: unknown) => void } | undefined>;
  };
}

/**
 * Whether a native host is listening.
 *
 * False in an ordinary browser, which is the case that matters: this module is in the shared package
 * and must be inert everywhere except inside the Mac app's web view.
 */
export function isEmbedded(): boolean {
  const w = window as unknown as WebKitBridgeWindow;
  return typeof w.webkit?.messageHandlers?.[BRIDGE_HANDLER]?.postMessage === 'function';
}

/**
 * Hand a play intent to the native player.
 *
 * Returns whether it was delivered. A `false` means nothing will play — which is the correct failure
 * for an unbridged page, and why ADR-0017 puts a null engine underneath: the alternative to silence
 * is a second audio engine, not success.
 */
/**
 * Ask the app to open an artist or album.
 *
 * The second and — per ADR-0020 point 2 — final message shape until an ADR says otherwise. It earns
 * its place by that ADR's point 3: the native app already has these screens, they are better than a
 * web equivalent inside a web view, and the page cannot reach them.
 *
 * Returns whether it was delivered. A `false` in an ordinary browser is correct: this module ships
 * in the web app and the iOS app too, and must be inert outside a native host.
 */
export function postNavigateIntent(intent: Omit<NavigateIntent, 'type'>): boolean {
  const artist = intent.artist?.trim();
  if (!artist) return false;
  if (intent.to === 'album' && !intent.album?.trim()) return false;

  return post({
    type: 'navigate',
    to: intent.to,
    artist,
    ...(intent.to === 'album' ? { album: intent.album!.trim() } : {}),
  } satisfies NavigateIntent);
}

export function postPlayIntent(intent: Omit<PlayIntent, 'type'>): boolean {
  if (intent.trackIds.length === 0) return false;

  return post({
    type: 'play',
    trackIds: intent.trackIds,
    // Defended rather than trusted: a `startingAt` outside the list would leave the native side
    // choosing a cursor for a track it was not given, and the first track is the honest default.
    startingAt: intent.trackIds.includes(intent.startingAt) ? intent.startingAt : intent.trackIds[0],
  } satisfies PlayIntent);
}

/**
 * The one place a message actually crosses.
 *
 * Shared so the two shapes cannot fail differently — with the bridge now two messages wide
 * (ADR-0020), "inert in a browser" and "survives a throwing host" have to mean the same thing for
 * both, or the next one to be added inherits whichever half was remembered.
 */
function post(message: PlayIntent | NavigateIntent): boolean {
  const w = window as unknown as WebKitBridgeWindow;
  const handler = w.webkit?.messageHandlers?.[BRIDGE_HANDLER];
  if (!handler || typeof handler.postMessage !== 'function') return false;
  try {
    handler.postMessage(message);
    return true;
  } catch {
    // A throwing bridge is a native-side problem, and taking the page down with it would put a
    // stack trace inside a web view inside an app — the hardest place to read one.
    return false;
  }
}
