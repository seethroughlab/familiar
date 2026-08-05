import { db, type DeviceProfile, isIndexedDBAvailable } from '../db';
import { createLogger } from '../utils/logger';

const log = createLogger('ProfileSelection');

let cachedProfileId: string | null = null;

/**
 * The selected profile ID without awaiting IndexedDB, or null before one has been resolved.
 *
 * For render paths that need to key state by listener and cannot be async. Safe wherever the
 * library is on screen: `renderApp` resolves the profile before mounting it, which populates the
 * cache. Anything that might run *before* that must use `getSelectedProfileId` and await it.
 */
export function getCachedProfileId(): string | null {
  return cachedProfileId;
}

/**
 * Get the currently selected profile ID.
 * Returns null if no profile is selected.
 */
export async function getSelectedProfileId(): Promise<string | null> {
  if (cachedProfileId) {
    return cachedProfileId;
  }

  // Check if IndexedDB is available (fails on iOS private browsing)
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) {
    log.warn('IndexedDB not available, using memory-only mode');
    return null;
  }

  try {
    const existing = await db.deviceProfile.get('device-profile');
    if (existing) {
      cachedProfileId = existing.profileId;
      return existing.profileId;
    }
  } catch (error) {
    log.warn('Failed to read from IndexedDB:', error);
    return null;
  }

  return null;
}

/**
 * Select a profile (store in IndexedDB).
 * Falls back to memory-only if IndexedDB isn't available.
 */
export async function selectProfile(profileId: string): Promise<void> {
  cachedProfileId = profileId;

  // Try to persist to IndexedDB
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) {
    log.warn('IndexedDB not available, profile selection is session-only');
    return;
  }

  try {
    const profile: DeviceProfile = {
      id: 'device-profile',
      profileId: profileId,
      deviceId: '', // No longer used
      createdAt: new Date(),
    };
    await db.deviceProfile.put(profile);
  } catch (error) {
    log.warn('Failed to persist profile to IndexedDB:', error);
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

  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) {
    return;
  }

  try {
    await db.deviceProfile.delete('device-profile');
  } catch (error) {
    log.warn('Failed to clear profile from IndexedDB:', error);
  }

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('profile-cleared'));
  }
}
