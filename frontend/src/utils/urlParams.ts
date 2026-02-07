/**
 * URL Parameter Schema
 *
 * Centralized definition of valid URL parameters for each app tab.
 * This ensures consistent parameter handling across navigation.
 */

export type AppTab = 'library' | 'playlists' | 'queue' | 'settings';

/**
 * Whitelist of URL parameters that are valid for each tab.
 * Parameters not in this list will be cleared when switching to that tab.
 */
export const TAB_PARAM_WHITELIST: Record<AppTab, string[]> = {
  library: [
    // Browser selection
    'browser',
    'search',
    // Artist/Album filters
    'artist',
    'album',
    'genre',
    // Year filters
    'yearFrom',
    'yearTo',
    // Detail views
    'artistDetail',
    'albumDetailArtist',
    'albumDetailAlbum',
    // Mood filters
    'energyMin',
    'energyMax',
    'valenceMin',
    'valenceMax',
    // Offline filter
    'downloadedOnly',
  ],
  playlists: ['playlist', 'smartPlaylist', 'view'],
  queue: [],
  settings: [],
};

/**
 * Parameters that should be cleared when applying a new filter type.
 * For example, applying a mood filter should clear year filters and vice versa.
 */
export const FILTER_GROUPS: Record<string, string[]> = {
  // Artist/Album context
  artistAlbum: ['artist', 'album'],
  // Year range
  year: ['yearFrom', 'yearTo'],
  // Mood quadrant
  mood: ['energyMin', 'energyMax', 'valenceMin', 'valenceMax'],
  // Genre
  genre: ['genre'],
  // Detail views
  detail: ['artistDetail', 'albumDetailArtist', 'albumDetailAlbum'],
};

/**
 * Get all filter params that should be cleared when applying a new filter.
 * This prevents conflicting filters from being active simultaneously.
 */
export function getConflictingParams(filterGroup: keyof typeof FILTER_GROUPS): string[] {
  // When applying a new filter, clear all other filter groups
  const allFilterParams: string[] = [];
  for (const [group, params] of Object.entries(FILTER_GROUPS)) {
    if (group !== filterGroup) {
      allFilterParams.push(...params);
    }
  }
  return allFilterParams;
}

/**
 * Check if a tab is valid
 */
export function isValidTab(tab: string): tab is AppTab {
  return tab === 'library' || tab === 'playlists' || tab === 'queue' || tab === 'settings';
}
