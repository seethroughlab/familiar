import axios from 'axios';
import { getSelectedProfileId, clearSelectedProfile } from '../services/profileService';
import { apiErrorTracker, extractAxiosError } from '../utils/apiErrorTracker';
import { createLogger } from '../utils/logger';

const log = createLogger('ApiBase');

// ============================================================================
// Capacitor-aware API origin
// ============================================================================

const BACKEND_URL_KEY = 'familiar_backend_url';

/** Cached origin string — empty for same-origin (web), full URL for Capacitor. */
let _apiOrigin = '';

/** True when running inside a Capacitor native shell. */
function isNativePlatform(): boolean {
  // Capacitor injects this on the window object
  return !!(window as unknown as Record<string, unknown>).Capacitor &&
    (window as unknown as { Capacitor: { isNativePlatform?: () => boolean } })
      .Capacitor.isNativePlatform?.() === true;
}

// ============================================================================
// Preferences Provider — Registration Pattern
// The iOS package registers a Capacitor Preferences provider at boot.
// Keeps @capacitor/preferences out of the shared package.
// ============================================================================

type PreferencesProvider = {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
};

let _preferencesProvider: PreferencesProvider | null = null;

export function registerPreferencesProvider(p: PreferencesProvider): void {
  _preferencesProvider = p;
}

/**
 * Initialize the API origin. Must be called once at app boot.
 * On native, loads the backend URL from the registered preferences provider
 * and caches it in localStorage for synchronous access.
 */
export async function initApiOrigin(): Promise<void> {
  if (!isNativePlatform()) {
    _apiOrigin = '';
    return;
  }

  // Try localStorage first (synchronous cache)
  const cached = localStorage.getItem(BACKEND_URL_KEY);
  if (cached) {
    _apiOrigin = cached.replace(/\/+$/, '');
    log.info('API origin from cache:', _apiOrigin);
    return;
  }

  // Try registered preferences provider
  if (_preferencesProvider) {
    try {
      const value = await _preferencesProvider.get(BACKEND_URL_KEY);
      if (value) {
        _apiOrigin = value.replace(/\/+$/, '');
        localStorage.setItem(BACKEND_URL_KEY, _apiOrigin);
        log.info('API origin from Preferences:', _apiOrigin);
      }
    } catch {
      log.warn('Could not load backend URL from preferences provider');
    }
  }
}

/**
 * Save a backend URL (called from ServerSettings).
 * Persists to both localStorage and the registered preferences provider.
 */
export async function setApiOrigin(url: string): Promise<void> {
  _apiOrigin = url.replace(/\/+$/, '');
  localStorage.setItem(BACKEND_URL_KEY, _apiOrigin);

  if (isNativePlatform() && _preferencesProvider) {
    try {
      await _preferencesProvider.set(BACKEND_URL_KEY, _apiOrigin);
    } catch {
      // localStorage is sufficient as fallback
    }
  }
}

/** Base origin for non-axios URLs (stream, artwork, etc). Empty string for same-origin. */
export function getApiOrigin(): string {
  return _apiOrigin;
}

/** True when running inside a Capacitor native shell (re-exported for guards). */
export { isNativePlatform };

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

// Add X-Profile-ID header to all requests (if a profile is selected)
api.interceptors.request.use(async (config) => {
  try {
    const profileId = await getSelectedProfileId();
    if (profileId) {
      config.headers['X-Profile-ID'] = profileId;
    }
  } catch (error) {
    // Log but don't block requests if profile check fails
    log.error('Failed to get profile ID:', error);
  }
  return config;
});

// Handle 401 errors and track all API errors for debugging
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    // Track error for debugging visibility
    const errorInfo = extractAxiosError(error);
    apiErrorTracker.track(errorInfo);

    // Check if this is an "invalid profile" error
    if (
      error.response?.status === 401 &&
      (error.response?.data?.detail?.includes('re-register') ||
       error.response?.data?.detail?.includes('Invalid profile'))
    ) {
      // Clear the invalid profile selection
      await clearSelectedProfile();
      // The app should redirect to profile selector
      // Dispatch a custom event that App.tsx can listen for
      window.dispatchEvent(new CustomEvent('profile-invalidated'));
    }

    return Promise.reject(error);
  }
);

export default api;
