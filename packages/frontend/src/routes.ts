/**
 * Route and sidebar navigation definitions.
 *
 * Extracted to a dependency-free module so they can be imported in tests
 * without pulling in the React component tree.
 *
 * ## The web app is being reduced to management (see `docs/WEB-PARITY.md`)
 *
 * The Mac and iPhone now cover the listening path, so the browser keeps only what it is uniquely
 * good for. The retired browsers are **unmounted, not deleted** — their components and registrations
 * stay, so this is one commit to revert if something turns out to be missed. `PARKED_BROWSERS` below
 * is what keeps that honest rather than silent.
 */

/** Maps URL path segments to browser registry IDs. */
export const BROWSER_ROUTES = [
  { path: 'tracks', browserId: 'track-list' },
  // No native equivalent, and its API tag (`Library Organization`) is not in the generated Swift
  // client — so this is genuinely browser-only work, not a duplicate of something on the Mac.
  { path: 'artist-cleanup', browserId: 'artist-cleanup' },
] as const;

/**
 * Registered browsers deliberately left without a route.
 *
 * `navigationIntegrity.test.ts` asserts every registered browser is reachable — the guard against a
 * component nobody can get to. Unmounting these breaks that guard on purpose, so they are named here
 * instead: the test allows exactly this set and nothing else, which means an *accidentally*
 * unreachable browser still fails the suite.
 *
 * Each entry says where the capability went. When one of these is deleted for good, delete its line.
 */
export const PARKED_BROWSERS: Record<string, string> = {
  // **Parked but NOT deletable.** `EmbedDiscover` lazy-imports `DiscoverBrowser`, so this component
  // is what both Apple clients render inside their WKWebView. Unmounted from this app's routes;
  // still very much alive. See ADR-0050 point 4 — parked and deletable are not the same thing, and
  // this is the entry that proves it.
  discover: 'Mac and iPhone embed this same code via /embed (ADR-0016/0017/0019) — do not delete',
};

/** Where the app opens. Settings, because that is what the browser is for now. */
export const HOME_ROUTE = {
  path: '/settings',
  label: 'Settings',
} as const;

/** Sidebar library navigation items. */
export const LIBRARY_ITEMS = [
  // Kept as the "simple player": a browser can still find a track and play it, which is what a guest
  // machine or a second computer needs, and it keeps `WebAudioEngine` and the effects chain
  // exercised rather than rotting untested.
  { path: '/library/tracks', label: 'Tracks' },
  { path: '/library/artist-cleanup', label: 'Cleanup' },
] as const;
