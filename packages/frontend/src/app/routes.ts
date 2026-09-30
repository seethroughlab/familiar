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


/// Where the app opens: the Overview, which answers "is it healthy, is anything running, what
/// needs attention" before showing a single total (ADR-0126 point 3). It was the Library under
/// ADR-0058 point 1, which had itself replaced opening on a settings form.
export const HOME_ROUTE = {
  path: '/',
  label: 'Overview',
} as const;

/**
 * The four destinations (ADR-0126 point 1).
 *
 * Organised around the *units* an operator reasons about — the collection, the analysis pipeline,
 * the installation — rather than around where code lived. The previous three (Library, Tools,
 * Server) split a provider across three sections and the pipeline across four; ADR-0126's Context
 * has the panel-level audit that showed it. "Tools" named a directory. "Settings" is not used
 * because the two settings an operator most wants — library paths and API keys — are environment
 * variables the web app cannot set, and the label would promise them.
 *
 * **Every destination here renders content that exists today.** `navigationIntegrity.test.ts`
 * asserts each has a route, because a destination whose page is not mounted is the defect this
 * codebase has shipped three times over (`familiar` #70, #74, #76). Pending review is deliberately
 * *not* a section — see `UNBUILT_DESTINATION_ITEMS`.
 */
export const DESTINATIONS = [
  { path: '/', label: 'Overview', description: 'Health, what is running, what needs attention' },
  { path: '/library', label: 'Library', description: 'Sync, duplicates, artists, artwork, files' },
  { path: '/analysis', label: 'Analysis', description: 'The pipeline: backlog, phases, configuration' },
  { path: '/server', label: 'Server', description: 'Health, jobs, providers, backup, people' },
] as const;

export type DestinationPath = (typeof DESTINATIONS)[number]['path'];

/**
 * Local navigation inside a destination (ADR-0126 point 7): every section is its own route, so
 * it can be linked, reloaded and reached with browser history. The first entry is the index.
 *
 * Grouped so a unit stays whole (point 2): a provider is one card under `/server/providers`;
 * the pipeline's configuration and status are both under `/analysis`; the S3 installation backup
 * is `/server/backup` and the profile transfer is under `/server/people`, because they were two
 * unrelated things sharing the word "backup".
 */
export const SECTIONS: Record<Exclude<DestinationPath, '/'>, readonly { path: string; label: string }[]> = {
  '/library': [
    { path: '/library', label: 'Sync' },
    { path: '/library/duplicates', label: 'Duplicates' },
    { path: '/library/artists', label: 'Artists' },
    { path: '/library/artwork', label: 'Artwork' },
    { path: '/library/organize', label: 'Organiser' },
  ],
  '/analysis': [
    { path: '/analysis', label: 'Status' },
    { path: '/analysis/configuration', label: 'Configuration' },
  ],
  '/server': [
    { path: '/server', label: 'Health' },
    { path: '/server/jobs', label: 'Jobs' },
    { path: '/server/providers', label: 'Providers' },
    { path: '/server/backup', label: 'Backup' },
    { path: '/server/people', label: 'People' },
    { path: '/server/access', label: 'Access' },
    { path: '/server/diagnostics', label: 'Diagnostics' },
  ],
};

/**
 * Old router paths redirect to their successors (ADR-0126, Consequences) for as long as bookmarks
 * and README links might reach them. A router concern: ADR-0079's alias rule is about API paths
 * in `compat.py` and does not apply here.
 */
export const LEGACY_REDIRECTS: Record<string, string> = {
  '/tools': '/library',
  '/tools/duplicates': '/library/duplicates',
  '/tools/artwork': '/library/artwork',
  '/tools/organize': '/library/organize',
  '/tools/artists': '/library/artists',
};

/**
 * Does `pathname` fall under `destination`? Ancestor matching (ADR-0126 point 8): `/library/duplicates`
 * lights Library. `/` is exact, or it would match everything. Written once here because the
 * previous bar hand-rolled one ancestor rule for Library and exact equality for the rest, which
 * is why the Tools destination went dark on every tool child route.
 */
export function isUnder(pathname: string, destination: string): boolean {
  if (destination === '/') return pathname === '/';
  return pathname === destination || pathname.startsWith(`${destination}/`);
}

/**
 * Named in ADR-0058 point 2 and ADR-0126 point 4, absent from the navigation, and why.
 *
 * Written down rather than silently omitted, so the gap between the ADR and the app is a record
 * instead of a discrepancy someone rediscovers.
 */
export const UNBUILT_DESTINATION_ITEMS: Record<string, string> = {
  'pending-review':
    'no web component — the `api/pendingTracks.ts` wrapper was deleted under ADR-0077, which had ' +
    'named this very line as a comment describing dead code instead of removing it. ADR-0126 point 4: ' +
    'Review joins Library when a screen exists; until then it is not a section and not a link',
  'update-channel':
    'never existed — the Server slot held `InstallStatus` (PWA install state), retired by ADR-0059',
  'duplicates-count-on-overview':
    'the count comes from a POST preview that takes ~40 s against 26k tracks; the Overview shows ' +
    'no duplicates item until a persisted count exists (ADR-0126 follow-up)',
};
