/**
 * Whether this browser keeps a profile's favourites offline (ADR-0029 point 4).
 *
 * **This setting moved off the server.** It used to be the single key in `Profile.settings` — one
 * boolean per listener, which meant a phone with 64 GB and a desktop with 500 GB could not disagree
 * about holding 1,700 tracks offline. Whether to keep audio on a device depends on that device, so
 * ADR-0029 makes it device-local and leaves the server with no listener preferences at all.
 *
 * Keyed by profile *inside* the store, unlike `familiar-queue-sync`, which is a rollout gate and
 * genuinely per-device-only. Favourites belong to a listener, so two people using one browser must
 * not share the answer — the same reasoning that suffixes the native key with the profile id.
 *
 * `seededProfiles` records which profiles have had the server's old value copied across, so it is
 * copied exactly once. Without it, anyone who had this on would silently stop getting downloads,
 * which reads as a bug rather than as a setting that moved.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface FavoritesAutoDownloadState {
  enabledByProfile: Record<string, boolean>;
  seededProfiles: string[];
  isEnabled: (profileId: string | null | undefined) => boolean;
  setEnabled: (profileId: string, enabled: boolean) => void;
  hasSeeded: (profileId: string | null | undefined) => boolean;
  /** Record the server's old value as this profile's starting point, once. */
  seed: (profileId: string, enabled: boolean) => void;
}

export const useFavoritesAutoDownloadStore = create<FavoritesAutoDownloadState>()(
  persist(
    (set, get) => ({
      enabledByProfile: {},
      seededProfiles: [],
      isEnabled: (profileId) => (profileId ? (get().enabledByProfile[profileId] ?? false) : false),
      setEnabled: (profileId, enabled) =>
        set((state) => ({
          enabledByProfile: { ...state.enabledByProfile, [profileId]: enabled },
        })),
      hasSeeded: (profileId) => (profileId ? get().seededProfiles.includes(profileId) : false),
      seed: (profileId, enabled) =>
        set((state) =>
          state.seededProfiles.includes(profileId)
            ? state
            : {
                enabledByProfile: { ...state.enabledByProfile, [profileId]: enabled },
                seededProfiles: [...state.seededProfiles, profileId],
              }
        ),
    }),
    {
      name: 'familiar-favorites-auto-download',
      // Functions are recreated by the initialiser on rehydrate; only the data is stored.
      partialize: (state) => ({
        enabledByProfile: state.enabledByProfile,
        seededProfiles: state.seededProfiles,
      }),
    }
  )
);
