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
/// Where the app opens. The library, since ADR-0058 point 1 — it was `/settings`, which opened an
/// administration tool on a form rather than on the thing being administered.
export const HOME_ROUTE = {
  path: '/',
  label: 'Library',
} as const;

/**
 * The three destinations (ADR-0058 point 2).
 *
 * Replaces a sidebar that listed library *browsers* — a shape left over from being a music player.
 * An administration tool is organised by what you are administering: the library, the tools you run
 * against it, and the server underneath.
 *
 * **Every destination here renders content that exists today.** `navigationIntegrity.test.ts`
 * asserts each has a route, because a destination whose page is not mounted is the defect this
 * codebase has shipped three times over (`familiar` #70, #74, #76) and the one ADR-0057 point 5
 * exists to prevent. Two things ADR-0058 point 2 names are deliberately *not* linked, for exactly
 * that reason — see `UNBUILT_DESTINATION_ITEMS`.
 */
export const DESTINATIONS = [
  { path: '/', label: 'Library', description: 'Size, analysis and listening' },
  { path: '/tools', label: 'Tools', description: 'Run something against the library' },
  { path: '/server', label: 'Server', description: 'Health, profiles and keys' },
] as const;

/**
 * Named in ADR-0058 point 2, absent from the navigation, and why.
 *
 * The same bookkeeping `PARKED_BROWSERS` does above: written down rather than silently omitted, so
 * the gap between the ADR and the app is a record instead of a discrepancy someone rediscovers.
 */
export const UNBUILT_DESTINATION_ITEMS: Record<string, string> = {
  'pending-review': 'no web component — `api/pendingTracks.ts` is a wrapper nothing calls',
  // Duplicates, the organiser and artwork coverage were here. All three shipped in phases 4 and 5;
  // their lines are deleted rather than marked done, so this stays a list of what is missing.
};

/** Sidebar library navigation items. */
export const LIBRARY_ITEMS = [
  // Kept as the "simple player": a browser can still find a track and play it, which is what a guest
  // machine or a second computer needs, and it keeps `WebAudioEngine` and the effects chain
  // exercised rather than rotting untested.
  //
  // It reaches these from the Tools page rather than the sidebar (ADR-0058 point 3): the player is
  // scheduled for deletion, and a top-level destination is not what you give something on the way
  // out. `LIBRARY_ITEMS` stays as the route/label pairing both pages read.
  { path: '/library/tracks', label: 'Tracks' },
  { path: '/library/artist-cleanup', label: 'Cleanup' },
] as const;
