/**
 * Route and sidebar navigation definitions.
 *
 * Extracted to a dependency-free module so they can be imported in tests
 * without pulling in the React component tree.
 *
 * ## The web app is an administration tool (ADR-0058, `docs/WEB-PARITY.md`)
 *
 * The Mac and iPhone cover the listening path, so the browser keeps only what it is uniquely good
 * for: three destinations, and the jobs you run against a library.
 *
 * **The browser registry is gone** (ADR-0081 point 3). `BROWSER_ROUTES`, `PARKED_BROWSERS` and
 * `LIBRARY_ITEMS` lived here while the retired browsers were unmounted-but-not-deleted, so the
 * reduction stayed one commit from being reverted. That period is over: artist cleanup became an
 * ordinary screen at `/tools/artists`, which left a registry of one whose only consumer imported it
 * directly. The survivor is `components/Embed/DiscoverSurface.tsx`, rendered by the embedded page
 * the Apple clients load — reached by a plain import, which is all it ever needed.
 */


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
  'pending-review':
    'no web component — the `api/pendingTracks.ts` wrapper was deleted under ADR-0077, which had ' +
    'named this very line as a comment describing dead code instead of removing it',
  'update-channel':
    'never existed — the Server slot held `InstallStatus` (PWA install state), retired by ADR-0059',
  // Duplicates, the organiser and artwork coverage were here. All three shipped in phases 4 and 5;
  // their lines are deleted rather than marked done, so this stays a list of what is missing.
};

