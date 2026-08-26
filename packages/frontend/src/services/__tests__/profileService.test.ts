/**
 * Tests for profileService - profile selection, caching, API interaction, and validation.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// The selected profile lives in localStorage now (ADR-0071 deleted the Dexie store), so these
// tests drive the same key the service writes rather than a mocked database.
const STORAGE_KEY = 'familiar:selected-profile';


vi.mock('../../utils/logger', () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
}));

// Mock profilesApi
const mockProfilesApi = {
  list: vi.fn(),
  create: vi.fn(),
  get: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
};

vi.mock('../../api/profiles', () => ({
  profilesApi: mockProfilesApi,
}));

vi.mock('../../stores/connectivityStore', () => ({
  useConnectivityStore: {
    getState: vi.fn(() => ({ browserOnline: true })),
  },
}));

describe('profileService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    localStorage.clear();
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
    has_lastfm: false,
  };






  describe('getSelectedProfileId', () => {
    it('should return profile ID from IndexedDB', async () => {
      localStorage.setItem(STORAGE_KEY, 'profile-123');

      const { getSelectedProfileId } = await getModule();
      const result = await getSelectedProfileId();

      expect(result).toBe('profile-123');
    });

    it('should return null when no profile is selected', async () => {

      const { getSelectedProfileId } = await getModule();
      const result = await getSelectedProfileId();

      expect(result).toBeNull();
    });


  });

  describe('selectProfile', () => {
    it('should persist the profile selection', async () => {
      const { selectProfile } = await getModule();
      await selectProfile('profile-789');

      expect(localStorage.getItem(STORAGE_KEY)).toBe('profile-789');
    });

  });

  describe('clearSelectedProfile', () => {
    it('should clear the stored profile and the memory cache', async () => {
      const { selectProfile, clearSelectedProfile } = await getModule();

      await selectProfile('profile-123');
      await clearSelectedProfile();

      // Memory cache should be cleared
      // Need to check IDB is asked
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });
  });

  describe('listProfiles', () => {
    it('should fetch profiles from API', async () => {
      const profiles = [sampleProfile];
      mockProfilesApi.list.mockResolvedValueOnce(profiles);

      const { listProfiles } = await getModule();
      const result = await listProfiles();

      expect(result).toHaveLength(1);
      expect(result[0].name).toBe('Test User');
      expect(mockProfilesApi.list).toHaveBeenCalled();
    });



    it('should throw when offline without allowCache', async () => {
      mockProfilesApi.list.mockRejectedValueOnce(new Error('Network error'));

      const { listProfiles } = await getModule();
      await expect(listProfiles()).rejects.toThrow('Network error');
    });
  });

  describe('createProfile', () => {
    it('should call profilesApi.create and return created profile', async () => {
      mockProfilesApi.create.mockResolvedValueOnce(sampleProfile);

      const { createProfile } = await getModule();
      const result = await createProfile({ name: 'Test User', color: '#ff0000' });

      expect(result.name).toBe('Test User');
      expect(mockProfilesApi.create).toHaveBeenCalledWith({ name: 'Test User', color: '#ff0000' });
    });

    it('should throw on API error', async () => {
      mockProfilesApi.create.mockRejectedValueOnce(new Error('Bad Request'));

      const { createProfile } = await getModule();
      await expect(createProfile({ name: '' })).rejects.toThrow('Bad Request');
    });
  });

  describe('getProfile', () => {
    it('should fetch profile by ID', async () => {
      mockProfilesApi.get.mockResolvedValueOnce(sampleProfile);

      const { getProfile } = await getModule();
      const result = await getProfile('profile-123');

      expect(result?.name).toBe('Test User');
    });

    it('should return null for a 404', async () => {
      const axiosError = new Error('Not Found');
      (axiosError as unknown as { response: { status: number } }).response = { status: 404 };
      mockProfilesApi.get.mockRejectedValueOnce(axiosError);

      const { getProfile } = await getModule();
      const result = await getProfile('deleted-profile');

      expect(result).toBeNull();
    });

  });

  describe('deleteProfile', () => {
    it('should delete via API', async () => {
      mockProfilesApi.delete.mockResolvedValueOnce(undefined);

      const { deleteProfile } = await getModule();
      await deleteProfile('profile-123');

      expect(mockProfilesApi.delete).toHaveBeenCalledWith('profile-123');
    });

    it('should clear selection if deleting the selected profile', async () => {
      // First set the selected profile
      localStorage.setItem(STORAGE_KEY, 'profile-123');

      mockProfilesApi.delete.mockResolvedValueOnce(undefined);

      const { selectProfile, deleteProfile } = await getModule();
      await selectProfile('profile-123');
      await deleteProfile('profile-123');

      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
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
      localStorage.setItem(STORAGE_KEY, 'profile-123');

      mockProfilesApi.get.mockResolvedValueOnce(sampleProfile);

      const { validateSelectedProfile } = await getModule();
      const result = await validateSelectedProfile();

      expect(result?.name).toBe('Test User');
    });

    it('should clear selection if profile was deleted on server', async () => {
      localStorage.setItem(STORAGE_KEY, 'profile-123');

      const axiosError = new Error('Not Found');
      (axiosError as unknown as { response: { status: number } }).response = { status: 404 };
      mockProfilesApi.get.mockRejectedValueOnce(axiosError);

      const { validateSelectedProfile } = await getModule();
      const result = await validateSelectedProfile();

      expect(result).toBeNull();
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });
  });
});
