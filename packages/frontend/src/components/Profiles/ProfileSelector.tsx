/**
 * Netflix-style profile selector.
 *
 * Shown when:
 * - No profile is selected (first visit)
 * - Selected profile was deleted
 * - User clicks "Switch Profile" in settings
 */
import { useState, useEffect, useRef } from 'react';
import {
  listProfiles,
  createProfile,
  selectProfile,
  type Profile,
} from '../../services/profileService';
import { useConnectivityStore } from '../../stores/connectivityStore';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';

import { createLogger } from '../../utils/logger';

const log = createLogger('ProfileSelector');

// Default profile colors
const PROFILE_COLORS = [
  '#3B82F6', // Blue
  '#10B981', // Green
  '#8B5CF6', // Purple
  '#F59E0B', // Amber
  '#EF4444', // Red
  '#EC4899', // Pink
  '#06B6D4', // Cyan
  '#F97316', // Orange
];

interface ProfileSelectorProps {
  onProfileSelected: (profile: Profile) => void;
}

export function ProfileSelector({ onProfileSelected }: ProfileSelectorProps) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newProfileName, setNewProfileName] = useState('');
  const [selectedColor, setSelectedColor] = useState(PROFILE_COLORS[0]);
  const [error, setError] = useState<string | null>(null);
  const [usingCache, setUsingCache] = useState(false);
  const { isOffline } = useOfflineStatus();
  const autoSelectedRef = useRef(false);

  useEffect(() => {
    loadProfiles();
  }, []);

  // Auto-select if offline with exactly one cached profile
  useEffect(() => {
    async function autoSelect() {
      if (isOffline && usingCache && profiles.length === 1 && !autoSelectedRef.current) {
        autoSelectedRef.current = true;
        const profile = profiles[0];
        try {
          await selectProfile(profile.id);
          onProfileSelected(profile);
        } catch (err) {
          log.error('Failed to auto-select profile:', err);
        }
      }
    }
    autoSelect();
  }, [isOffline, usingCache, profiles, onProfileSelected]);

  async function loadProfiles() {
    try {
      setLoading(true);
      setUsingCache(false);
      const profileList = await listProfiles();
      setProfiles(profileList);

      // Check if we got cached profiles (network failed but cache succeeded)
      // We detect this by checking if we're offline
      if (!useConnectivityStore.getState().browserOnline && profileList.length > 0) {
        setUsingCache(true);
      }
    } catch (err) {
      // Check if we have any cached profiles to show
      if (!useConnectivityStore.getState().browserOnline) {
        setError('Connect to the network to create your first profile');
      } else {
        setError('Failed to load profiles');
      }
      log.error(err);
    } finally {
      setLoading(false);
    }
  }

  async function handleSelectProfile(profile: Profile) {
    try {
      await selectProfile(profile.id);
      onProfileSelected(profile);
    } catch (err) {
      setError('Failed to select profile');
      log.error(err);
    }
  }

  async function handleCreateProfile() {
    if (!newProfileName.trim()) return;

    try {
      setCreating(true);
      const profile = await createProfile({
        name: newProfileName.trim(),
        color: selectedColor,
      });
      await selectProfile(profile.id);
      onProfileSelected(profile);
    } catch (err) {
      setError('Failed to create profile');
      log.error(err);
    } finally {
      setCreating(false);
    }
  }

  if (loading) {
    return (
      <div role="status" aria-label="Loading profiles" className="min-h-screen bg-zinc-950 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-950 flex flex-col items-center justify-center p-8">
      <h1 className="text-4xl font-bold text-white mb-2">Who's listening?</h1>
      <p className="text-zinc-400 mb-12">Select your profile to continue</p>

      {/* Offline indicator */}
      {isOffline && usingCache && (
        <div className="mb-8 px-4 py-2 bg-amber-500/20 border border-amber-500/50 rounded-lg text-warning flex items-center gap-2">
          <svg
            className="w-5 h-5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M18.364 5.636a9 9 0 010 12.728m0 0l-2.829-2.829m2.829 2.829L21 21M15.536 8.464a5 5 0 010 7.072m0 0l-2.829-2.829m-4.243 2.829a4.978 4.978 0 01-1.414-2.83m-1.414 5.658a9 9 0 01-2.167-9.238m7.824 2.167a1 1 0 111.414 1.414m-1.414-1.414L3 3m8.293 8.293l1.414 1.414"
            />
          </svg>
          Offline - using cached profiles
        </div>
      )}

      {error && (
        <div className="mb-8 px-4 py-2 bg-red-500/20 border border-danger/50 rounded-lg text-danger">
          {error}
        </div>
      )}

      {/* Profile Grid */}
      <div className="flex flex-wrap justify-center gap-6 mb-12 max-w-4xl">
        {profiles.map((profile) => (
          <button
            key={profile.id}
            onClick={() => handleSelectProfile(profile)}
            className="group flex flex-col items-center gap-3 p-4 rounded-lg hover:bg-zinc-800/50 transition-colors"
          >
            <div
              className="w-24 h-24 rounded-lg flex items-center justify-center text-3xl font-bold text-white shadow-lg group-hover:ring-4 ring-white/20 transition-all overflow-hidden"
              style={{ backgroundColor: profile.color || PROFILE_COLORS[0] }}
            >
              {profile.avatar_url ? (
                <img
                  src={profile.avatar_url}
                  alt={profile.name}
                  className="w-full h-full object-cover"
                />
              ) : (
                profile.name.charAt(0).toUpperCase()
              )}
            </div>
            <span className="text-zinc-300 group-hover:text-white transition-colors">
              {profile.name}
            </span>
            <div className="flex gap-2 text-xs text-zinc-500">
              {profile.has_lastfm && <span>Last.fm</span>}
            </div>
          </button>
        ))}

        {/* Add Profile Button - hidden when offline */}
        {!isOffline && (
          <button
            onClick={() => {
              setNewProfileName('');
              setSelectedColor(PROFILE_COLORS[profiles.length % PROFILE_COLORS.length]);
              const modal = document.getElementById('create-profile-modal');
              if (modal instanceof HTMLDialogElement) {
                modal.showModal();
              }
            }}
            className="group flex flex-col items-center gap-3 p-4 rounded-lg hover:bg-zinc-800/50 transition-colors"
          >
            <div className="w-24 h-24 rounded-lg flex items-center justify-center text-4xl font-light text-zinc-500 border-2 border-dashed border-zinc-700 group-hover:border-zinc-500 group-hover:text-zinc-400 transition-all">
              +
            </div>
            <span className="text-zinc-500 group-hover:text-zinc-400 transition-colors">
              Add Profile
            </span>
          </button>
        )}
      </div>

      {/* Create Profile Modal */}
      <dialog
        id="create-profile-modal"
        className="bg-zinc-900 rounded-xl p-6 backdrop:bg-black/70 max-w-md w-full"
      >
        <h2 className="text-2xl font-bold text-white mb-6">Create Profile</h2>

        <div className="space-y-6">
          {/* Name Input */}
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">
              Profile Name
            </label>
            <input
              type="text"
              value={newProfileName}
              onChange={(e) => setNewProfileName(e.target.value)}
              placeholder="Enter name"
              className="w-full px-4 py-3 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter' && newProfileName.trim()) {
                  handleCreateProfile();
                }
              }}
            />
          </div>

          {/* Color Picker */}
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">
              Profile Color
            </label>
            <div className="flex flex-wrap gap-3">
              {PROFILE_COLORS.map((color) => (
                <button
                  key={color}
                  onClick={() => setSelectedColor(color)}
                  className={`w-10 h-10 rounded-lg transition-all ${
                    selectedColor === color
                      ? 'ring-2 ring-white ring-offset-2 ring-offset-zinc-900 scale-110'
                      : 'hover:scale-105'
                  }`}
                  style={{ backgroundColor: color }}
                />
              ))}
            </div>
          </div>

          {/* Preview */}
          <div className="flex justify-center py-4">
            <div
              className="w-20 h-20 rounded-lg flex items-center justify-center text-2xl font-bold text-white shadow-lg"
              style={{ backgroundColor: selectedColor }}
            >
              {newProfileName ? newProfileName.charAt(0).toUpperCase() : '?'}
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-3 pt-4">
            <button
              onClick={() => {
                const modal = document.getElementById('create-profile-modal');
                if (modal instanceof HTMLDialogElement) {
                  modal.close();
                }
              }}
              className="flex-1 px-4 py-3 bg-zinc-800 text-zinc-300 rounded-lg hover:bg-zinc-700 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleCreateProfile}
              disabled={!newProfileName.trim() || creating}
              className="flex-1 px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {creating ? 'Creating...' : 'Create'}
            </button>
          </div>
        </div>
      </dialog>

    </div>
  );
}
