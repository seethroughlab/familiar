import { useState, useEffect, useRef } from 'react';
import { User, RefreshCw, Pencil, X, Check, Camera, Loader2 } from 'lucide-react';
import { getSelectedProfileId, getProfile, clearSelectedProfile, type Profile } from '../../services/profileService';
import { profilesApi } from '../../api/client';
import { showError, showWarning } from '../../stores/toastStore';

export function ProfileSettings() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [isUploadingAvatar, setIsUploadingAvatar] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadProfile();
  }, []);

  async function loadProfile() {
    try {
      const profileId = await getSelectedProfileId();
      if (profileId) {
        const p = await getProfile(profileId);
        setProfile(p);
        if (p) {
          setEditName(p.name);
        }
      }
    } catch (err) {
      console.error('Failed to load profile:', err);
    } finally {
      setLoading(false);
    }
  }

  async function handleSwitchProfile() {
    await clearSelectedProfile();
    window.dispatchEvent(new CustomEvent('profile-invalidated'));
  }

  function handleEditClick() {
    if (profile) {
      setEditName(profile.name);
      setIsEditing(true);
    }
  }

  function handleCancelEdit() {
    if (profile) {
      setEditName(profile.name);
    }
    setIsEditing(false);
  }

  async function handleSave() {
    if (!profile || !editName.trim()) return;

    setIsSaving(true);
    try {
      const updated = await profilesApi.update(profile.id, { name: editName.trim() });
      setProfile(updated);
      setIsEditing(false);
    } catch (err) {
      console.error('Failed to update profile:', err);
    } finally {
      setIsSaving(false);
    }
  }

  function handleAvatarClick() {
    fileInputRef.current?.click();
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !profile) return;

    // Validate file type
    if (!file.type.startsWith('image/')) {
      showWarning('Please select an image file');
      return;
    }

    // Validate file size (5MB max)
    if (file.size > 5 * 1024 * 1024) {
      showWarning('Image must be less than 5MB');
      return;
    }

    setIsUploadingAvatar(true);
    try {
      const updated = await profilesApi.uploadAvatar(profile.id, file);
      setProfile(updated);
    } catch (err) {
      console.error('Failed to upload avatar:', err);
      showError('Failed to upload avatar', {
        description: 'Please try again',
      });
    } finally {
      setIsUploadingAvatar(false);
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  }

  if (loading) {
    return (
      <div className="bg-zinc-800/50 rounded-lg p-4 animate-pulse">
        <div className="h-6 bg-zinc-700 rounded w-1/3"></div>
      </div>
    );
  }

  // Avatar display - either image or color with initial
  const avatarElement = (
    <div
      className={`relative w-12 h-12 rounded-lg flex items-center justify-center text-lg font-bold text-white overflow-hidden ${
        isEditing ? 'cursor-pointer group' : ''
      }`}
      style={{ backgroundColor: profile?.color || '#3B82F6' }}
      onClick={isEditing ? handleAvatarClick : undefined}
    >
      {profile?.avatar_url ? (
        <img
          src={profile.avatar_url}
          alt={profile.name}
          className="w-full h-full object-cover"
        />
      ) : (
        profile?.name?.charAt(0).toUpperCase() || <User className="w-6 h-6" />
      )}

      {/* Upload overlay in edit mode */}
      {isEditing && (
        <div className="absolute inset-0 bg-black/50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
          {isUploadingAvatar ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : (
            <Camera className="w-5 h-5" />
          )}
        </div>
      )}
    </div>
  );

  return (
    <div className="bg-zinc-800/50 rounded-lg p-4">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handleFileChange}
      />

      {isEditing ? (
        // Edit mode
        <div className="flex items-center gap-3">
          {avatarElement}

          <div className="flex-1">
            <input
              type="text"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              className="w-full bg-zinc-700 border border-zinc-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
              placeholder="Profile name"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSave();
                if (e.key === 'Escape') handleCancelEdit();
              }}
            />
            <p className="text-xs text-zinc-500 mt-1">
              Click the avatar to upload a new image
            </p>
          </div>

          <div className="flex gap-2">
            <button
              onClick={handleCancelEdit}
              disabled={isSaving}
              className="p-2 bg-zinc-700 hover:bg-zinc-600 rounded-lg text-zinc-300 hover:text-white transition-colors disabled:opacity-50"
              title="Cancel"
            >
              <X className="w-4 h-4" />
            </button>
            <button
              onClick={handleSave}
              disabled={isSaving || !editName.trim()}
              className="p-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-white transition-colors disabled:opacity-50"
              title="Save"
            >
              {isSaving ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Check className="w-4 h-4" />
              )}
            </button>
          </div>
        </div>
      ) : (
        // View mode
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {avatarElement}
            <div>
              <div className="font-medium text-white">{profile?.name || 'Unknown Profile'}</div>
              <div className="text-sm text-zinc-400">
                {profile?.has_spotify && 'Spotify'}
                {profile?.has_spotify && profile?.has_lastfm && ' · '}
                {profile?.has_lastfm && 'Last.fm'}
                {!profile?.has_spotify && !profile?.has_lastfm && 'No integrations'}
              </div>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleEditClick}
              className="flex items-center gap-2 px-3 py-2 bg-zinc-700 hover:bg-zinc-600 rounded-lg text-sm text-zinc-300 hover:text-white transition-colors"
            >
              <Pencil className="w-4 h-4" />
              Edit
            </button>
            <button
              onClick={handleSwitchProfile}
              className="flex items-center gap-2 px-3 py-2 bg-zinc-700 hover:bg-zinc-600 rounded-lg text-sm text-zinc-300 hover:text-white transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              Switch
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
