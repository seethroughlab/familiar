import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type HomeModuleId =
  | 'resume'
  | 'prompts'
  | 'quick-picks'
  | 'discovery'
  | 'library-shortcuts';

export type RecentDestinationType =
  | 'browser'
  | 'artist'
  | 'album'
  | 'favorites'
  | 'downloads'
  | 'playlist'
  | 'smart-playlist'
  | 'discover';

export interface RecentDestination {
  route: string;
  label: string;
  type: RecentDestinationType;
  timestamp: number;
  subtitle?: string;
  artworkUrl?: string | null;
}

export interface HomePreferences {
  order: HomeModuleId[];
  enabled: Record<HomeModuleId, boolean>;
}

const DEFAULT_MODULE_ORDER: HomeModuleId[] = [
  'resume',
  'prompts',
  'quick-picks',
  'discovery',
  'library-shortcuts',
];

const DEFAULT_ENABLED: Record<HomeModuleId, boolean> = {
  resume: true,
  prompts: true,
  'quick-picks': true,
  discovery: true,
  'library-shortcuts': true,
};

const MAX_RECENTS = 8;
const DEFAULT_PROFILE_KEY = '__default__';

function resolveProfileKey(profileId: string | null | undefined): string {
  return profileId || DEFAULT_PROFILE_KEY;
}

function getDefaultPreferences(): HomePreferences {
  return {
    order: [...DEFAULT_MODULE_ORDER],
    enabled: { ...DEFAULT_ENABLED },
  };
}

interface HomeState {
  recentDestinationsByProfile: Record<string, RecentDestination[]>;
  preferencesByProfile: Record<string, HomePreferences>;
  addRecentDestination: (profileId: string | null | undefined, destination: Omit<RecentDestination, 'timestamp'> & { timestamp?: number }) => void;
  setModuleEnabled: (profileId: string | null | undefined, moduleId: HomeModuleId, enabled: boolean) => void;
  moveModule: (profileId: string | null | undefined, moduleId: HomeModuleId, direction: 'up' | 'down') => void;
  resetPreferences: (profileId: string | null | undefined) => void;
}

export function getHomePreferences(
  profileId: string | null | undefined,
  preferencesByProfile: Record<string, HomePreferences>
): HomePreferences {
  return preferencesByProfile[resolveProfileKey(profileId)] ?? getDefaultPreferences();
}

export function getRecentDestinations(
  profileId: string | null | undefined,
  recentDestinationsByProfile: Record<string, RecentDestination[]>
): RecentDestination[] {
  return recentDestinationsByProfile[resolveProfileKey(profileId)] ?? [];
}

export const useHomeStore = create<HomeState>()(
  persist(
    (set) => ({
      recentDestinationsByProfile: {},
      preferencesByProfile: {},

      addRecentDestination: (profileId, destination) => {
        const profileKey = resolveProfileKey(profileId);
        set((state) => {
          const existing = state.recentDestinationsByProfile[profileKey] ?? [];
          const deduped = existing.filter((item) => item.route !== destination.route);
          return {
            recentDestinationsByProfile: {
              ...state.recentDestinationsByProfile,
              [profileKey]: [
                {
                  ...destination,
                  timestamp: destination.timestamp ?? Date.now(),
                },
                ...deduped,
              ].slice(0, MAX_RECENTS),
            },
          };
        });
      },

      setModuleEnabled: (profileId, moduleId, enabled) => {
        const profileKey = resolveProfileKey(profileId);
        set((state) => {
          const current = state.preferencesByProfile[profileKey] ?? getDefaultPreferences();
          const nextEnabled = {
            ...current.enabled,
            [moduleId]: enabled,
          };
          if (!Object.values(nextEnabled).some(Boolean)) {
            nextEnabled.resume = true;
          }
          return {
            preferencesByProfile: {
              ...state.preferencesByProfile,
              [profileKey]: {
                ...current,
                enabled: nextEnabled,
              },
            },
          };
        });
      },

      moveModule: (profileId, moduleId, direction) => {
        const profileKey = resolveProfileKey(profileId);
        set((state) => {
          const current = state.preferencesByProfile[profileKey] ?? getDefaultPreferences();
          const order = [...current.order];
          const index = order.indexOf(moduleId);
          if (index < 0) return state;
          const target = direction === 'up' ? index - 1 : index + 1;
          if (target < 0 || target >= order.length) return state;
          [order[index], order[target]] = [order[target], order[index]];
          return {
            preferencesByProfile: {
              ...state.preferencesByProfile,
              [profileKey]: {
                ...current,
                order,
              },
            },
          };
        });
      },

      resetPreferences: (profileId) => {
        const profileKey = resolveProfileKey(profileId);
        set((state) => ({
          preferencesByProfile: {
            ...state.preferencesByProfile,
            [profileKey]: getDefaultPreferences(),
          },
        }));
      },
    }),
    {
      name: 'familiar-home',
      partialize: (state) => ({
        recentDestinationsByProfile: state.recentDestinationsByProfile,
        preferencesByProfile: state.preferencesByProfile,
      }),
    }
  )
);
