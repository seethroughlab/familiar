/**
 * Profile service for Netflix-style multi-user support.
 *
 * Manages selectable profiles that work across devices.
 * No passwords needed - protected by Tailscale.
 */
import { db, type DeviceProfile, type CachedProfile, isIndexedDBAvailable } from '../db';
import { getApiUrl } from '../api/base';
import { createLogger } from '../utils/logger';

const log = createLogger('ProfileService');

export interface Profile {
  id: string;
  name: string;
  color: string | null;
  avatar_url: string | null;
  created_at: string;
  has_spotify: boolean;
  has_lastfm: boolean;
}

export interface ProfileCreate {
  name: string;
  color?: string;
}

export interface ListProfilesOptions {
  allowCache?: boolean;
}

export interface ValidateProfileOptions {
  requireOnline?: boolean;
}

let cachedProfileId: string | null = null;

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
      has_spotify: profile.has_spotify,
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
    has_spotify: cached.has_spotify,
    has_lastfm: cached.has_lastfm,
    created_at: cached.cachedAt.toISOString(),
  };
}

// ============================================================================
// Profile Selection Functions
// ============================================================================

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
 * Call this after user picks a profile from the selector.
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
}

/**
 * Clear the selected profile.
 * Use this to show the profile selector again.
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
}

/**
 * List all available profiles from the server.
 * When offline with allowCache, falls back to cached profiles.
 */
export async function listProfiles(options?: ListProfilesOptions): Promise<Profile[]> {
  try {
    const response = await fetch(getApiUrl('/profiles'));
    if (!response.ok) {
      throw new Error(`Failed to list profiles: ${response.statusText}`);
    }
    const profiles: Profile[] = await response.json();

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
  const response = await fetch(getApiUrl('/profiles'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    throw new Error(`Failed to create profile: ${response.statusText}`);
  }

  return response.json();
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
    const response = await fetch(getApiUrl(`/profiles/${profileId}`));
    if (response.status === 404) {
      // Profile deleted on server - clear cache
      await clearCachedProfile(profileId);
      return null;
    }
    if (!response.ok) {
      throw new Error(`Failed to get profile: ${response.statusText}`);
    }
    const profile: Profile = await response.json();

    // Cache for offline use
    await cacheProfile(profile);

    return profile;
  } catch (error) {
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
  const response = await fetch(getApiUrl(`/profiles/${profileId}`), {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    throw new Error(`Failed to update profile: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Delete a profile.
 */
export async function deleteProfile(profileId: string): Promise<void> {
  const response = await fetch(getApiUrl(`/profiles/${profileId}`), {
    method: 'DELETE',
  });

  if (!response.ok) {
    throw new Error(`Failed to delete profile: ${response.statusText}`);
  }

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

  if (navigator.onLine) {
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
