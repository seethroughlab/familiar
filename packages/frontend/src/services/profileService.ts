/**
 * Profile service for Netflix-style multi-user support.
 *
 * Manages selectable profiles that work across devices.
 * No passwords needed - protected by Tailscale.
 */
import { db, type CachedProfile, isIndexedDBAvailable } from '../db';
import { profilesApi, type ProfileResponse, type ProfileCreate } from '../api/profiles';
import { useConnectivityStore } from '../stores/connectivityStore';
import { createLogger } from '../utils/logger';
import {
  getSelectedProfileId,
  selectProfile,
  clearSelectedProfile,
} from './profileSelection';

const log = createLogger('ProfileService');

export type Profile = ProfileResponse;
export type { ProfileCreate };

export interface ListProfilesOptions {
  allowCache?: boolean;
}

export interface ValidateProfileOptions {
  requireOnline?: boolean;
}

// ============================================================================
// Profile Caching Functions (for offline support)
// ============================================================================

/**
 * Cache a profile in IndexedDB for offline access.
 * Silently fails if IndexedDB isn't available.
 */
export async function cacheProfile(profile: Profile): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) {
    return; // Silently skip caching
  }

  try {
    const cached: CachedProfile = {
      id: profile.id,
      name: profile.name,
      color: profile.color,
      avatar_url: profile.avatar_url,
      has_lastfm: profile.has_lastfm,
      cachedAt: new Date(),
    };
    await db.cachedProfiles.put(cached);
  } catch (error) {
    log.warn('Failed to cache profile:', error);
  }
}

/**
 * Get a single cached profile by ID.
 * Returns undefined if IndexedDB isn't available.
 */
export async function getCachedProfile(profileId: string): Promise<CachedProfile | undefined> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) {
    return undefined;
  }

  try {
    return await db.cachedProfiles.get(profileId);
  } catch (error) {
    log.warn('Failed to get cached profile:', error);
    return undefined;
  }
}

/**
 * Get all cached profiles.
 * Returns empty array if IndexedDB isn't available.
 */
export async function getCachedProfiles(): Promise<CachedProfile[]> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) {
    return [];
  }

  try {
    return await db.cachedProfiles.toArray();
  } catch (error) {
    log.warn('Failed to get cached profiles:', error);
    return [];
  }
}

/**
 * Clear a cached profile.
 */
export async function clearCachedProfile(profileId: string): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) {
    return;
  }

  try {
    await db.cachedProfiles.delete(profileId);
  } catch (error) {
    log.warn('Failed to clear cached profile:', error);
  }
}

/**
 * Convert CachedProfile to Profile format.
 */
function cachedToProfile(cached: CachedProfile): Profile {
  return {
    id: cached.id,
    name: cached.name,
    color: cached.color,
    avatar_url: cached.avatar_url,
    has_lastfm: cached.has_lastfm,
    created_at: cached.cachedAt.toISOString(),
  };
}

// ============================================================================
// Profile Selection Functions
// ============================================================================
export { getSelectedProfileId, selectProfile, clearSelectedProfile };

/**
 * List all available profiles from the server.
 * When offline with allowCache, falls back to cached profiles.
 */
export async function listProfiles(options?: ListProfilesOptions): Promise<Profile[]> {
  try {
    const profiles = await profilesApi.list();

    // Cache all profiles for offline use
    await Promise.all(profiles.map((p) => cacheProfile(p)));

    return profiles;
  } catch (error) {
    // If offline and cache allowed, return cached profiles
    if (options?.allowCache) {
      const cached = await getCachedProfiles();
      if (cached.length > 0) {
        return cached.map(cachedToProfile);
      }
    }
    throw error;
  }
}

/**
 * Create a new profile.
 */
export async function createProfile(data: ProfileCreate): Promise<Profile> {
  return profilesApi.create(data);
}

/**
 * Get profile by ID.
 * Caches on success, falls back to cache on network error.
 */
export async function getProfile(
  profileId: string,
  options?: { allowCache?: boolean }
): Promise<Profile | null> {
  try {
    const profile = await profilesApi.get(profileId);

    // Cache for offline use
    await cacheProfile(profile);

    return profile;
  } catch (error: unknown) {
    // Profile deleted on server - clear cache
    if (
      typeof error === 'object' && error !== null &&
      'response' in error &&
      (error as { response?: { status?: number } }).response?.status === 404
    ) {
      await clearCachedProfile(profileId);
      return null;
    }
    // If offline and cache allowed, return cached profile
    if (options?.allowCache) {
      const cached = await getCachedProfile(profileId);
      if (cached) {
        return cachedToProfile(cached);
      }
    }
    throw error;
  }
}

/**
 * Update a profile.
 */
export async function updateProfile(profileId: string, data: Partial<ProfileCreate>): Promise<Profile> {
  return profilesApi.update(profileId, data);
}

/**
 * Delete a profile.
 */
export async function deleteProfile(profileId: string): Promise<void> {
  await profilesApi.delete(profileId);

  // If this was the selected profile, clear it
  const selectedId = await getSelectedProfileId();
  if (selectedId === profileId) {
    await clearSelectedProfile();
  }
}

/**
 * Validate that the selected profile still exists.
 * Returns the profile if valid, null otherwise.
 *
 * When offline (requireOnline=false), uses cached profile data.
 */
export async function validateSelectedProfile(
  options?: ValidateProfileOptions
): Promise<Profile | null> {
  const profileId = await getSelectedProfileId();
  if (!profileId) {
    return null;
  }

  const requireOnline = options?.requireOnline ?? true;

  try {
    const profile = await getProfile(profileId, { allowCache: !requireOnline });
    if (!profile) {
      // Profile was deleted, clear the selection
      await clearSelectedProfile();
      return null;
    }
    return profile;
  } catch (error) {
    // Network error - if we don't require online, try cache
    if (!requireOnline) {
      const cached = await getCachedProfile(profileId);
      if (cached) {
        return cachedToProfile(cached);
      }
    }
    throw error;
  }
}

/**
 * Initialize profile on app startup.
 * Returns the selected profile if valid, null if profile selector should be shown.
 *
 * When offline, uses cached profile data and schedules background validation.
 */
export async function initializeProfile(): Promise<Profile | null> {
  const profileId = await getSelectedProfileId();
  if (!profileId) {
    return null;
  }

  try {
    // Try online validation first
    return await validateSelectedProfile({ requireOnline: true });
  } catch {
    // Network error - try cached profile
    const cached = await getCachedProfile(profileId);
    if (cached) {
      // Schedule background validation when online
      scheduleBackgroundValidation(profileId);
      return cachedToProfile(cached);
    }
    return null;
  }
}

/**
 * Schedule background validation when network becomes available.
 * Dispatches 'profile-invalidated' event if profile was deleted.
 */
function scheduleBackgroundValidation(profileId: string): void {
  const handleOnline = async () => {
    window.removeEventListener('online', handleOnline);
    try {
      const profile = await getProfile(profileId);
      if (!profile) {
        // Profile was deleted on server
        await clearSelectedProfile();
        await clearCachedProfile(profileId);
        window.dispatchEvent(new CustomEvent('profile-invalidated'));
      }
    } catch {
      // Still can't reach server, try again later
      window.addEventListener('online', handleOnline, { once: true });
    }
  };

  if (useConnectivityStore.getState().browserOnline) {
    // Already online, validate immediately
    handleOnline();
  } else {
    // Wait for online
    window.addEventListener('online', handleOnline, { once: true });
  }
}

// Legacy exports for backwards compatibility during migration
export const getOrCreateDeviceProfile = getSelectedProfileId;
export const clearDeviceProfile = clearSelectedProfile;
export const getCurrentProfileId = getSelectedProfileId;
