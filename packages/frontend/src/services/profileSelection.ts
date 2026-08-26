/**
 * Which profile this browser is using.
 *
 * **`localStorage`, not IndexedDB.** ADR-0071 deleted the Dexie store, and this was the one thing
 * in it that had nothing to do with caching tracks: a single id saying who is looking. A
 * synchronous key/value store is a better fit for it than a database — `getSelectedProfileId` no
 * longer has to be async to answer, and the "IndexedDB is unavailable in iOS private browsing"
 * fallback that shaped the old code disappears with the dependency.
 *
 * The async signatures are kept because callers await them across the app; changing that is a
 * separate, mechanical edit and not this one.
 */
import { createLogger } from '../utils/logger';

const log = createLogger('ProfileSelection');

const STORAGE_KEY = 'familiar:selected-profile';

let cachedProfileId: string | null = null;

function readStored(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch (error) {
    // Safari in private mode can throw on access rather than returning null
    log.warn('Failed to read the selected profile:', error);
    return null;
  }
}

/**
 * The selected profile ID without awaiting, or null before one has been resolved.
 *
 * For render paths that need to key state by listener and cannot be async. Safe wherever the
 * library is on screen: `renderApp` resolves the profile before mounting it, which populates the
 * cache. Anything that might run *before* that must use `getSelectedProfileId` and await it.
 */
export function getCachedProfileId(): string | null {
  if (cachedProfileId === null) {
    cachedProfileId = readStored();
  }
  return cachedProfileId;
}

/**
 * Get the currently selected profile ID.
 * Returns null if no profile is selected.
 */
export async function getSelectedProfileId(): Promise<string | null> {
  return getCachedProfileId();
}

/**
 * Select a profile, persisting it for this browser.
 */
export async function selectProfile(profileId: string): Promise<void> {
  cachedProfileId = profileId;

  try {
    localStorage.setItem(STORAGE_KEY, profileId);
  } catch (error) {
    log.warn('Failed to persist the selected profile; it is session-only:', error);
  }

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('profile-selected', {
      detail: { profileId },
    }));
  }
}

/**
 * Clear the selected profile.
 */
export async function clearSelectedProfile(): Promise<void> {
  cachedProfileId = null;

  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch (error) {
    log.warn('Failed to clear the selected profile:', error);
  }

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('profile-cleared'));
  }
}
