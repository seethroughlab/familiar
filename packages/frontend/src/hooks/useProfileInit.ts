/**
 * Custom hook for profile initialization and lifecycle management.
 *
 * Handles:
 * - Initial profile check with IndexedDB timeout (iOS safety)
 * - URL ?reset=true PWA state reset
 * - Profile invalidation listener (from API client)
 * - Plugin system initialization
 *
 * Returns { profile, setProfile, checkingProfile }.
 */
import { useState, useEffect, useCallback } from 'react';
import { createLogger } from '../utils/logger';
import { initializeProfile, type Profile } from '../services/profileService';

const log = createLogger('ProfileInit');
import { pluginLoader } from '../services/pluginLoader';

// PWA Reset utility - clears all persisted state
function resetPWAState() {
  log.info('Resetting PWA state');
  // Clear all localStorage keys for this app
  const keysToRemove = Object.keys(localStorage).filter(
    (k) => k.startsWith('familiar-') || k.startsWith('zustand-')
  );
  keysToRemove.forEach((k) => localStorage.removeItem(k));

  // Clear IndexedDB databases
  if ('indexedDB' in window) {
    indexedDB.databases?.().then((dbs) => {
      dbs.forEach((db) => {
        if (db.name) {
          indexedDB.deleteDatabase(db.name);
        }
      });
    });
  }

  // Clear URL state
  window.history.replaceState(null, '', window.location.pathname);

  // Reload to apply clean state
  window.location.reload();
}

// Expose reset function globally for debugging
if (typeof window !== 'undefined') {
  (window as unknown as { resetFamiliar: () => void }).resetFamiliar = resetPWAState;
}

interface ProfileInitResult {
  profile: Profile | null | undefined;
  setProfile: (p: Profile | null) => void;
  checkingProfile: boolean;
}

export function useProfileInit(): ProfileInitResult {
  const [profile, setProfile] = useState<Profile | null | undefined>(undefined);
  const [checkingProfile, setCheckingProfile] = useState(true);

  // Check for reset parameter in URL
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('reset') === 'true') {
      resetPWAState();
    }
  }, []);

  const checkProfile = useCallback(async () => {
    setCheckingProfile(true);
    try {
      // Add timeout to prevent hanging on iOS when IndexedDB/Dexie gets stuck
      const timeoutPromise = new Promise<null>((resolve) => {
        setTimeout(() => {
          log.warn('Profile initialization timed out - IndexedDB may be unavailable');
          resolve(null);
        }, 5000);
      });

      const p = await Promise.race([
        initializeProfile(),
        timeoutPromise,
      ]);
      setProfile(p);
    } catch (err) {
      log.error('Failed to check profile:', err);
      setProfile(null);
    } finally {
      setCheckingProfile(false);
    }
  }, []);

  useEffect(() => {
    checkProfile();

    // Listen for profile invalidation events (from API client)
    const handleInvalidated = () => {
      setProfile(null);
    };
    window.addEventListener('profile-invalidated', handleInvalidated);

    return () => {
      window.removeEventListener('profile-invalidated', handleInvalidated);
    };
  }, [checkProfile]);

  // Initialize plugin system and load plugins
  useEffect(() => {
    // Initialize the global Familiar API for plugins
    pluginLoader.initializeGlobalAPI();

    // Load all enabled plugins
    pluginLoader.loadAllPlugins().catch((err) => {
      log.error('Failed to load plugins:', err);
    });
  }, []);

  return { profile, setProfile, checkingProfile };
}
