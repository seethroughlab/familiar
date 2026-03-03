/**
 * Tests for profileService - profile selection, caching, API interaction, and validation.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock db tables
const mockDeviceProfileGet = vi.fn();
const mockDeviceProfilePut = vi.fn();
const mockDeviceProfileDelete = vi.fn();
const mockCachedProfilesGet = vi.fn();
const mockCachedProfilesPut = vi.fn();
const mockCachedProfilesDelete = vi.fn();
const mockCachedProfilesToArray = vi.fn();

vi.mock('../../db', () => ({
  db: {
    deviceProfile: {
      get: (...args: unknown[]) => mockDeviceProfileGet(...args),
      put: (...args: unknown[]) => mockDeviceProfilePut(...args),
      delete: (...args: unknown[]) => mockDeviceProfileDelete(...args),
    },
    cachedProfiles: {
      get: (...args: unknown[]) => mockCachedProfilesGet(...args),
      put: (...args: unknown[]) => mockCachedProfilesPut(...args),
      delete: (...args: unknown[]) => mockCachedProfilesDelete(...args),
      toArray: () => mockCachedProfilesToArray(),
    },
  },
  isIndexedDBAvailable: vi.fn(() => Promise.resolve(true)),
}));

vi.mock('../../utils/logger', () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
}));

describe('profileService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    mockDeviceProfileGet.mockResolvedValue(undefined);
    mockDeviceProfilePut.mockResolvedValue(undefined);
    mockDeviceProfileDelete.mockResolvedValue(undefined);
    mockCachedProfilesGet.mockResolvedValue(undefined);
    mockCachedProfilesPut.mockResolvedValue(undefined);
    mockCachedProfilesDelete.mockResolvedValue(undefined);
    mockCachedProfilesToArray.mockResolvedValue([]);
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const getModule = async () => await import('../profileService');

  const sampleProfile = {
    id: 'profile-123',
    name: 'Test User',
    color: '#ff0000',
    avatar_url: null,
    created_at: '2024-01-01T00:00:00Z',
    has_spotify: true,
    has_lastfm: false,
  };

  const sampleCachedProfile = {
    id: 'profile-123',
    name: 'Test User',
    color: '#ff0000',
    avatar_url: null,
    has_spotify: true,
    has_lastfm: false,
    cachedAt: new Date(),
  };

  describe('cacheProfile', () => {
    it('should cache a profile in IndexedDB', async () => {
      const { cacheProfile } = await getModule();
      await cacheProfile(sampleProfile);

      expect(mockCachedProfilesPut).toHaveBeenCalledWith(
        expect.objectContaining({
          id: 'profile-123',
          name: 'Test User',
          color: '#ff0000',
          has_spotify: true,
          has_lastfm: false,
          cachedAt: expect.any(Date),
        })
      );
    });

    it('should skip caching when IndexedDB is unavailable', async () => {
      const dbModule = await import('../../db');
      vi.mocked(dbModule.isIndexedDBAvailable).mockResolvedValueOnce(false);

      const { cacheProfile } = await getModule();
      await cacheProfile(sampleProfile);

      expect(mockCachedProfilesPut).not.toHaveBeenCalled();
    });

    it('should silently handle db errors', async () => {
      mockCachedProfilesPut.mockRejectedValueOnce(new Error('IDB error'));

      const { cacheProfile } = await getModule();
      await cacheProfile(sampleProfile);
      // Should not throw
    });
  });

  describe('getCachedProfile', () => {
    it('should return cached profile by ID', async () => {
      mockCachedProfilesGet.mockResolvedValueOnce(sampleCachedProfile);

      const { getCachedProfile } = await getModule();
      const result = await getCachedProfile('profile-123');

      expect(result).toEqual(sampleCachedProfile);
      expect(mockCachedProfilesGet).toHaveBeenCalledWith('profile-123');
    });

    it('should return undefined when not found', async () => {
      mockCachedProfilesGet.mockResolvedValueOnce(undefined);

      const { getCachedProfile } = await getModule();
      const result = await getCachedProfile('nonexistent');

      expect(result).toBeUndefined();
    });

    it('should return undefined when IndexedDB is unavailable', async () => {
      const dbModule = await import('../../db');
      vi.mocked(dbModule.isIndexedDBAvailable).mockResolvedValueOnce(false);

      const { getCachedProfile } = await getModule();
      const result = await getCachedProfile('profile-123');

      expect(result).toBeUndefined();
    });
  });

  describe('getCachedProfiles', () => {
    it('should return all cached profiles', async () => {
      mockCachedProfilesToArray.mockResolvedValueOnce([sampleCachedProfile]);

      const { getCachedProfiles } = await getModule();
      const result = await getCachedProfiles();

      expect(result).toHaveLength(1);
      expect(result[0].id).toBe('profile-123');
    });

    it('should return empty array when IndexedDB is unavailable', async () => {
      const dbModule = await import('../../db');
      vi.mocked(dbModule.isIndexedDBAvailable).mockResolvedValueOnce(false);

      const { getCachedProfiles } = await getModule();
      const result = await getCachedProfiles();

      expect(result).toEqual([]);
    });
  });

  describe('clearCachedProfile', () => {
    it('should delete cached profile by ID', async () => {
      const { clearCachedProfile } = await getModule();
      await clearCachedProfile('profile-123');

      expect(mockCachedProfilesDelete).toHaveBeenCalledWith('profile-123');
    });
  });

  describe('getSelectedProfileId', () => {
    it('should return profile ID from IndexedDB', async () => {
      mockDeviceProfileGet.mockResolvedValueOnce({
        id: 'device-profile',
        profileId: 'profile-123',
        deviceId: '',
        createdAt: new Date(),
      });

      const { getSelectedProfileId } = await getModule();
      const result = await getSelectedProfileId();

      expect(result).toBe('profile-123');
    });

    it('should return null when no profile is selected', async () => {
      mockDeviceProfileGet.mockResolvedValueOnce(undefined);

      const { getSelectedProfileId } = await getModule();
      const result = await getSelectedProfileId();

      expect(result).toBeNull();
    });

    it('should return null when IndexedDB is unavailable', async () => {
      const dbModule = await import('../../db');
      vi.mocked(dbModule.isIndexedDBAvailable).mockResolvedValueOnce(false);

      const { getSelectedProfileId } = await getModule();
      const result = await getSelectedProfileId();

      expect(result).toBeNull();
    });

    it('should cache the profile ID in memory after first read', async () => {
      mockDeviceProfileGet.mockResolvedValueOnce({
        id: 'device-profile',
        profileId: 'profile-456',
        deviceId: '',
        createdAt: new Date(),
      });

      const { getSelectedProfileId } = await getModule();

      const first = await getSelectedProfileId();
      const second = await getSelectedProfileId();

      expect(first).toBe('profile-456');
      expect(second).toBe('profile-456');
      // Should only read from db once (cached after first call)
      expect(mockDeviceProfileGet).toHaveBeenCalledTimes(1);
    });
  });

  describe('selectProfile', () => {
    it('should persist profile selection to IndexedDB', async () => {
      const { selectProfile } = await getModule();
      await selectProfile('profile-789');

      expect(mockDeviceProfilePut).toHaveBeenCalledWith(
        expect.objectContaining({
          id: 'device-profile',
          profileId: 'profile-789',
        })
      );
    });

    it('should set memory cache even when IndexedDB is unavailable', async () => {
      const dbModule = await import('../../db');
      vi.mocked(dbModule.isIndexedDBAvailable).mockResolvedValueOnce(false);

      const { selectProfile, getSelectedProfileId } = await getModule();
      await selectProfile('profile-memory');

      const result = await getSelectedProfileId();
      expect(result).toBe('profile-memory');
      expect(mockDeviceProfilePut).not.toHaveBeenCalled();
    });
  });

  describe('clearSelectedProfile', () => {
    it('should clear profile from IndexedDB and memory', async () => {
      const { selectProfile, clearSelectedProfile } = await getModule();

      await selectProfile('profile-123');
      await clearSelectedProfile();

      // Memory cache should be cleared
      // Need to check IDB is asked
      expect(mockDeviceProfileDelete).toHaveBeenCalledWith('device-profile');
    });
  });

  describe('listProfiles', () => {
    it('should fetch profiles from API', async () => {
      const profiles = [sampleProfile];
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(profiles),
      } as Response);

      const { listProfiles } = await getModule();
      const result = await listProfiles();

      expect(result).toHaveLength(1);
      expect(result[0].name).toBe('Test User');
      expect(global.fetch).toHaveBeenCalledWith('/api/v1/profiles');
    });

    it('should cache fetched profiles', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve([sampleProfile]),
      } as Response);

      const { listProfiles } = await getModule();
      await listProfiles();

      expect(mockCachedProfilesPut).toHaveBeenCalled();
    });

    it('should fall back to cache when offline with allowCache', async () => {
      vi.mocked(global.fetch).mockRejectedValueOnce(new Error('Network error'));
      mockCachedProfilesToArray.mockResolvedValueOnce([sampleCachedProfile]);

      const { listProfiles } = await getModule();
      const result = await listProfiles({ allowCache: true });

      expect(result).toHaveLength(1);
      expect(result[0].id).toBe('profile-123');
    });

    it('should throw when offline without allowCache', async () => {
      vi.mocked(global.fetch).mockRejectedValueOnce(new Error('Network error'));

      const { listProfiles } = await getModule();
      await expect(listProfiles()).rejects.toThrow('Network error');
    });
  });

  describe('createProfile', () => {
    it('should post to API and return created profile', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(sampleProfile),
      } as Response);

      const { createProfile } = await getModule();
      const result = await createProfile({ name: 'Test User', color: '#ff0000' });

      expect(result.name).toBe('Test User');
      expect(global.fetch).toHaveBeenCalledWith('/api/v1/profiles', expect.objectContaining({
        method: 'POST',
      }));
    });

    it('should throw on API error', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: false,
        statusText: 'Bad Request',
      } as Response);

      const { createProfile } = await getModule();
      await expect(createProfile({ name: '' })).rejects.toThrow('Failed to create profile');
    });
  });

  describe('getProfile', () => {
    it('should fetch profile by ID and cache it', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(sampleProfile),
      } as Response);

      const { getProfile } = await getModule();
      const result = await getProfile('profile-123');

      expect(result?.name).toBe('Test User');
      expect(mockCachedProfilesPut).toHaveBeenCalled();
    });

    it('should return null and clear cache for 404', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: false,
        status: 404,
      } as Response);

      const { getProfile } = await getModule();
      const result = await getProfile('deleted-profile');

      expect(result).toBeNull();
      expect(mockCachedProfilesDelete).toHaveBeenCalledWith('deleted-profile');
    });

    it('should fall back to cache on network error with allowCache', async () => {
      vi.mocked(global.fetch).mockRejectedValueOnce(new Error('Network error'));
      mockCachedProfilesGet.mockResolvedValueOnce(sampleCachedProfile);

      const { getProfile } = await getModule();
      const result = await getProfile('profile-123', { allowCache: true });

      expect(result).not.toBeNull();
      expect(result?.id).toBe('profile-123');
    });
  });

  describe('deleteProfile', () => {
    it('should delete via API', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({ ok: true } as Response);

      const { deleteProfile } = await getModule();
      await deleteProfile('profile-123');

      expect(global.fetch).toHaveBeenCalledWith('/api/v1/profiles/profile-123', expect.objectContaining({
        method: 'DELETE',
      }));
    });

    it('should clear selection if deleting the selected profile', async () => {
      // First set the selected profile
      mockDeviceProfileGet.mockResolvedValue({
        id: 'device-profile',
        profileId: 'profile-123',
        deviceId: '',
        createdAt: new Date(),
      });

      vi.mocked(global.fetch).mockResolvedValueOnce({ ok: true } as Response);

      const { selectProfile, deleteProfile } = await getModule();
      await selectProfile('profile-123');
      await deleteProfile('profile-123');

      expect(mockDeviceProfileDelete).toHaveBeenCalledWith('device-profile');
    });
  });

  describe('validateSelectedProfile', () => {
    it('should return null when no profile is selected', async () => {
      // No profile set, no IDB result
      const { validateSelectedProfile } = await getModule();
      const result = await validateSelectedProfile();

      expect(result).toBeNull();
    });

    it('should validate against server and return profile', async () => {
      mockDeviceProfileGet.mockResolvedValueOnce({
        id: 'device-profile',
        profileId: 'profile-123',
        deviceId: '',
        createdAt: new Date(),
      });

      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(sampleProfile),
      } as Response);

      const { validateSelectedProfile } = await getModule();
      const result = await validateSelectedProfile();

      expect(result?.name).toBe('Test User');
    });

    it('should clear selection if profile was deleted on server', async () => {
      mockDeviceProfileGet.mockResolvedValueOnce({
        id: 'device-profile',
        profileId: 'profile-123',
        deviceId: '',
        createdAt: new Date(),
      });

      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: false,
        status: 404,
      } as Response);

      const { validateSelectedProfile } = await getModule();
      const result = await validateSelectedProfile();

      expect(result).toBeNull();
      expect(mockDeviceProfileDelete).toHaveBeenCalledWith('device-profile');
    });
  });
});
