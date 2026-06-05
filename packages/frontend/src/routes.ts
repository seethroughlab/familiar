/**
 * Route and sidebar navigation definitions.
 *
 * Extracted to a dependency-free module so they can be imported in tests
 * without pulling in the React component tree.
 */

/** Maps URL path segments to browser registry IDs. */
export const BROWSER_ROUTES = [
  { path: 'tracks', browserId: 'track-list' },
  { path: 'artists', browserId: 'artist-list' },
  { path: 'albums', browserId: 'album-grid' },
  { path: 'music-map', browserId: 'vibe-map' },
  { path: 'discover', browserId: 'discover' },
  { path: 'discover/new-releases', browserId: 'new-releases-detail' },
  { path: 'proposed-changes', browserId: 'proposed-changes' },
  { path: 'pending-review', browserId: 'pending-review' },
] as const;

export const HOME_ROUTE = {
  path: '/home',
  label: 'Home',
} as const;

/** Sidebar library navigation items. */
export const LIBRARY_ITEMS = [
  { path: '/library/tracks', label: 'Tracks' },
  { path: '/library/artists', label: 'Artists' },
  { path: '/library/albums', label: 'Albums' },
  { path: '/library/music-map', label: 'Music Map' },
  { path: '/library/discover', label: 'Discover' },
  { path: '/library/proposed-changes', label: 'Changes' },
  { path: '/library/pending-review', label: 'Review' },
] as const;
