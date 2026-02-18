/**
 * URL Parameter Utilities
 *
 * Filter group definitions for managing conflicting URL parameters.
 */

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
};

/**
 * Get all filter params that should be cleared when applying a new filter.
 * This prevents conflicting filters from being active simultaneously.
 */
export function getConflictingParams(filterGroup: keyof typeof FILTER_GROUPS): string[] {
  const allFilterParams: string[] = [];
  for (const [group, params] of Object.entries(FILTER_GROUPS)) {
    if (group !== filterGroup) {
      allFilterParams.push(...params);
    }
  }
  return allFilterParams;
}
