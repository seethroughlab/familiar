/**
 * Profile service for Netflix-style multi-user support.
 *
 * Manages selectable profiles that work across devices.
 * No passwords needed - protected by Tailscale.
 */
import { profilesApi, type ProfileResponse, type ProfileCreate } from '../api/profiles';
import { useConnectivityStore } from '../stores/connectivityStore';
import {
  getSelectedProfileId,
  selectProfile,
  clearSelectedProfile,
} from './profileSelection';


export type Profile = ProfileResponse;
export type { ProfileCreate };

// ============================================================================
// Profile Selection Functions
// ============================================================================
export { getSelectedProfileId, selectProfile, clearSelectedProfile };

/**
 * List all available profiles from the server.
 *
 * Server-only. Profiles used to be mirrored into IndexedDB so the picker worked with no server;
 * ADR-0071 removed that store, and ADR-0059 had already accepted that the administration tool
 * does not open offline.
 */
export async function listProfiles(): Promise<Profile[]> {
  return profilesApi.list();
}

/**
 * Create a new profile.
 */
export async function createProfile(data: ProfileCreate): Promise<Profile> {
  return profilesApi.create(data);
}

/**
 * Get profile by ID.
 *
 * Returns null when the server says the profile is gone, and throws when it cannot be asked.
 * The two are different: a 404 means it was deleted and the selection should be cleared; a
 * network error means we do not know. There is no cache to fall back to (ADR-0071).
 */
export async function getProfile(profileId: string): Promise<Profile | null> {
  try {
    return await profilesApi.get(profileId);
  } catch (error: unknown) {
    if (
      typeof error === 'object' && error !== null &&
      'response' in error &&
      (error as { response?: { status?: number } }).response?.status === 404
    ) {
      return null;
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
 * Throws when the server cannot be reached; returns null when it says the profile is gone.
 */
export async function validateSelectedProfile(): Promise<Profile | null> {
  const profileId = await getSelectedProfileId();
  if (!profileId) {
    return null;
  }

  const profile = await getProfile(profileId);
  if (!profile) {
    // Profile was deleted, clear the selection
    await clearSelectedProfile();
    return null;
  }
  return profile;
}

/**
 * Initialize profile on app startup.
 * Returns the selected profile if valid, null if the profile selector should be shown.
 *
 * With no server there is no cached profile to fall back to (ADR-0071), so an unreachable server
 * schedules a re-check and shows the selector rather than guessing who is looking.
 */
export async function initializeProfile(): Promise<Profile | null> {
  const profileId = await getSelectedProfileId();
  if (!profileId) {
    return null;
  }

  try {
    return await validateSelectedProfile();
  } catch {
    scheduleBackgroundValidation(profileId);
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
