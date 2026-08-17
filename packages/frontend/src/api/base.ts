import axios from 'axios';
import { apiErrorTracker, extractAxiosError } from '../utils/apiErrorTracker';
import { createLogger } from '../utils/logger';

const log = createLogger('ApiBase');

// ============================================================================
// Capacitor-aware API origin
// ============================================================================

const BACKEND_URL_KEY = 'familiar_backend_url';

/** Cached origin string — empty for same-origin (web), full URL for Capacitor. */
let _apiOrigin = '';

// ============================================================================
// Preferences Provider — Registration Pattern
// The iOS package registers a Capacitor Preferences provider at boot.
// Keeps @capacitor/preferences out of the shared package.
// ============================================================================

// ============================================================================
// Profile Provider — Registration Pattern
// Breaks circular dependency: api/base should not import from services/.
// The shared bootstrap (renderApp.tsx) registers the provider at boot.
// ============================================================================

type ProfileProvider = {
  getSelectedProfileId(): Promise<string | null>;
  clearSelectedProfile(): Promise<void>;
};

let _profileProvider: ProfileProvider | null = null;

export function registerProfileProvider(p: ProfileProvider): void {
  _profileProvider = p;
}

/**
 * Initialize the API origin. Must be called once at app boot.
 *
 * Always empty, meaning "same origin as this document" — which is right for the web app and for
 * the embedded Discover page, both served by the server they talk to. The branch that read a
 * stored URL existed for the Capacitor app, which was deleted on 2026-08-11 (ADR-0001 point 6).
 *
 * `/visualizer` is the exception and sets its origin explicitly via `setApiOrigin`: it is read out
 * of the Mac app's bundle over a custom URL scheme (ADR-0034 point 4) and has no server in its own
 * location to infer one from.
 */
export async function initApiOrigin(): Promise<void> {
  _apiOrigin = '';
}

/**
 * Point this document at a server.
 *
 * Only `/visualizer` calls this, for the reason above. It caches to localStorage, which the custom
 * scheme has because it is a real origin — a `file://` or `loadHTMLString` page would not.
 */
export async function setApiOrigin(url: string): Promise<void> {
  _apiOrigin = url.replace(/\/+$/, '');
  localStorage.setItem(BACKEND_URL_KEY, _apiOrigin);
}

// ============================================================================
// Server token (ADR-0045)
//
// Stored and cached exactly like the backend URL above: localStorage for synchronous access,
// mirrored into the registered preferences provider so the native clients keep it across a
// reinstall. It is a server-wide credential, not a per-profile one — switching profiles must not
// clear it, which is why it lives here rather than in profileService.
//
// **This covers axios requests only.** Artwork and audio are `<img src>` and `el.src` on an
// `<audio>` element (see `AlbumArtwork.tsx` and `WebAudioEngine.ts:227`), and a media element
// cannot send a custom header. Those routes are unauthenticated today, so nothing is broken by
// this — but they are the reason ADR-0045 point 5 cannot simply be switched on, and that is
// recorded in the ADR rather than discovered when playback stops.
// ============================================================================

const SERVER_TOKEN_KEY = 'familiar_server_token';

let _serverToken = '';

/**
 * Load the stored server token. Call at boot, beside `initApiOrigin`.
 *
 * localStorage only. The second source was the Capacitor Preferences plugin, reached through a
 * registered provider — and the Capacitor app was deleted on 2026-08-11 (ADR-0001 point 6), so
 * nothing ever registered one.
 */
export async function initServerToken(): Promise<void> {
  _serverToken = localStorage.getItem(SERVER_TOKEN_KEY) ?? '';
}

/** Persist a server token. Empty string clears it. */
export async function setServerToken(token: string): Promise<void> {
  _serverToken = token.trim();
  if (_serverToken) {
    localStorage.setItem(SERVER_TOKEN_KEY, _serverToken);
  } else {
    localStorage.removeItem(SERVER_TOKEN_KEY);
  }
}

export function getServerToken(): string {
  return _serverToken;
}

/** Base origin for non-axios URLs (stream, artwork, etc). Empty string for same-origin. */
export function getApiOrigin(): string {
  return _apiOrigin;
}

/** Build a full API URL path, e.g. getApiUrl('/tracks/123/stream') → '/api/v1/tracks/123/stream' */
export function getApiUrl(path: string): string {
  return `${getApiOrigin()}/api/v1${path}`;
}

const api = axios.create({
  baseURL: '/api/v1',
});

// Dynamic baseURL: prepend origin on native platform
api.interceptors.request.use((config) => {
  if (_apiOrigin) {
    config.baseURL = `${_apiOrigin}/api/v1`;
  }
  return config;
});

/**
 * Encode a value for use in a URL path segment.
 * Double-encodes slashes so they survive the server's automatic URL decode
 * (e.g. "ATB/York" → "ATB%252FYork" → server decodes to "ATB%2FYork" → handler unquote gives "ATB/York")
 */
export function encodePathSegment(value: string): string {
  return encodeURIComponent(value).replace(/%2F/gi, '%252F');
}

// Add the server token to all requests (ADR-0045). Separate interceptor from the profile header
// below because they answer different questions: the token says whether this client may act at
// all, the profile says which listener it acts as.
api.interceptors.request.use((config) => {
  if (_serverToken && !config.headers['X-Familiar-Token']) {
    config.headers['X-Familiar-Token'] = _serverToken;
  }
  return config;
});

// Add X-Profile-ID header to all requests (if a profile is selected)
api.interceptors.request.use(async (config) => {
  // An explicitly-supplied profile wins. The offline outbox replays actions against the
  // profile that queued them, which is not necessarily the one selected now — before this,
  // switching profiles while actions were pending sent them all to the wrong profile.
  if (config.headers['X-Profile-ID']) {
    return config;
  }
  try {
    const profileId = await _profileProvider?.getSelectedProfileId();
    if (profileId) {
      config.headers['X-Profile-ID'] = profileId;
    }
  } catch (error) {
    // Log but don't block requests if profile check fails
    log.error('Failed to get profile ID:', error);
  }
  return config;
});

/**
 * Extra per-request options. Narrow to `headers` on purpose: the only caller is the
 * outbox pinning a replay to the profile that queued it, and a full `AxiosRequestConfig`
 * would invite callers to override things like `baseURL` or interceptor-managed fields.
 */
export type RequestOptions = { headers?: Record<string, string> };

// Handle 401 errors and track all API errors for debugging
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    // Track error for debugging visibility
    const errorInfo = extractAxiosError(error);
    apiErrorTracker.track(errorInfo);

    // A missing or wrong server token (ADR-0045). Checked before the profile case below and kept
    // distinct from it: both are 401, but clearing the selected profile in response to a token
    // failure would log the listener out of a profile that was never the problem, and then the
    // profile selector itself would 401 too.
    if (error.response?.status === 401 && error.response?.data?.detail?.includes('X-Familiar-Token')) {
      window.dispatchEvent(new CustomEvent('server-token-required'));
      return Promise.reject(error);
    }

    // Check if this is an "invalid profile" error
    if (
      error.response?.status === 401 &&
      (error.response?.data?.detail?.includes('re-register') ||
       error.response?.data?.detail?.includes('Invalid profile'))
    ) {
      // Clear the invalid profile selection
      await _profileProvider?.clearSelectedProfile();
      // The app should redirect to profile selector
      // Dispatch a custom event that App.tsx can listen for
      window.dispatchEvent(new CustomEvent('profile-invalidated'));
    }

    return Promise.reject(error);
  }
);

export default api;
