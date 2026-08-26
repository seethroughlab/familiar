/**
 * Navigation integrity test — ensures sidebar items, routes, and browser
 * registrations stay in sync.
 *
 * Catches bugs like a sidebar link pointing to a route that doesn't exist
 * (which silently falls through to the catch-all redirect).
 */
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, it, expect, beforeAll } from 'vitest';
import { BROWSER_ROUTES, DESTINATIONS, LIBRARY_ITEMS, PARKED_BROWSERS } from '../routes';
import { getBrowser, getBrowsers } from '../components/Library/types';

// Trigger all browser registrations via side-effect imports
import '../components/Library/browsers';

describe('navigation integrity', () => {
  let registeredBrowserIds: Set<string>;

  beforeAll(() => {
    registeredBrowserIds = new Set(getBrowsers().map((b) => b.metadata.id));
  });

  it('every sidebar library item has a matching route', () => {
    const routePaths = new Set<string>(BROWSER_ROUTES.map((r) => r.path));

    for (const item of LIBRARY_ITEMS) {
      // LIBRARY_ITEMS paths are like '/library/pending-review', routes are like 'pending-review'
      const routePath = item.path.replace('/library/', '');
      expect(routePaths.has(routePath), `Sidebar item "${item.label}" (${item.path}) has no matching route in BROWSER_ROUTES`).toBe(true);
    }
  });

  it('every route has a registered browser component', () => {
    for (const route of BROWSER_ROUTES) {
      const browser = getBrowser(route.browserId);
      expect(browser, `Route "${route.path}" references browserId "${route.browserId}" which is not registered`).toBeDefined();
    }
  });

  it('no duplicate browser IDs in BROWSER_ROUTES', () => {
    const ids = BROWSER_ROUTES.map((r) => r.browserId);
    const unique = new Set(ids);
    expect(ids.length).toBe(unique.size);
  });

  it('no duplicate paths in BROWSER_ROUTES', () => {
    const paths = BROWSER_ROUTES.map((r) => r.path);
    const unique = new Set(paths);
    expect(paths.length).toBe(unique.size);
  });

  it('no duplicate paths in LIBRARY_ITEMS', () => {
    const paths = LIBRARY_ITEMS.map((item) => item.path);
    const unique = new Set(paths);
    expect(paths.length).toBe(unique.size);
  });

  it('registered browsers are reachable, or explicitly parked', () => {
    // The web app is being reduced to management (docs/WEB-PARITY.md), so some browsers are
    // deliberately unmounted while their code stays — one commit to revert if something is missed.
    //
    // Naming them in `PARKED_BROWSERS` is what keeps this guard useful: an *accidentally*
    // unreachable browser still fails, because the allowance is a list rather than a switch.
    const routedBrowserIds = new Set<string>(BROWSER_ROUTES.map((r) => r.browserId));

    for (const id of registeredBrowserIds) {
      const reachable = routedBrowserIds.has(id);
      const parked = id in PARKED_BROWSERS;
      expect(
        reachable || parked,
        `Registered browser "${id}" has no route and is not in PARKED_BROWSERS — it is unreachable by accident`,
      ).toBe(true);
    }
  });

  it('every parked browser is actually registered', () => {
    // Otherwise the list becomes a graveyard of names that no longer mean anything — the same rot
    // that made keeping the whole web app as "documentation" a bad idea.
    for (const id of Object.keys(PARKED_BROWSERS)) {
      expect(
        registeredBrowserIds.has(id),
        `PARKED_BROWSERS lists "${id}", which is not a registered browser — delete the line`,
      ).toBe(true);
    }
  });

  it('no browser is both routed and parked', () => {
    for (const route of BROWSER_ROUTES) {
      expect(
        route.browserId in PARKED_BROWSERS,
        `"${route.browserId}" has a route and is also parked — one of the two is wrong`,
      ).toBe(false);
    }
  });
});

/**
 * Links are checked against the routes that actually exist in `App.tsx`.
 *
 * The suite above already claimed to catch "a sidebar link pointing to a route that doesn't exist"
 * — and did not. `/favorites` and `/downloads` sat in the sidebar for the whole of the ADR-0057
 * strip, silently redirecting to the catch-all, because they were **hardcoded in the component**
 * rather than declared in `routes.ts`, and the guard only ever read the registry.
 *
 * So this reads the source instead. A registry can only vouch for what someone remembered to put in
 * it; the JSX is where the affordance really is.
 */
describe('navigation links resolve to mounted routes', () => {
  // `import.meta.url` is not a file URL under vitest's transform, so paths resolve from the
  // package root (vitest's cwd) instead.
  const readSource = (relative: string) =>
    readFileSync(resolve(process.cwd(), 'src', relative), 'utf-8');

  const appSource = readSource('App.tsx');

  /** Absolute paths `App.tsx` mounts, plus the `/library/:path` routes it maps from the registry. */
  const mountedPaths = new Set<string>([
    ...Array.from(appSource.matchAll(/path="(\/[^"*]*)"/g), (m) => m[1]),
    ...BROWSER_ROUTES.map((r) => `/library/${r.path}`),
    // `<Route index>` is the destination for '/', and carries no `path` attribute to match.
    ...(/<Route index/.test(appSource) ? ['/'] : []),
  ]);

  /** Strip route params so `/listen/:code?` covers a link to `/listen/abc`. */
  const isMounted = (target: string) =>
    mountedPaths.has(target) ||
    [...mountedPaths].some((p) => p.includes(':') && new RegExp(
      `^${p.replace(/:[^/?]+\??/g, '[^/]*').replace(/\/$/, '')}/?$`,
    ).test(target));

  it('every destination in the top bar is mounted', () => {
    for (const d of DESTINATIONS) {
      expect(
        isMounted(d.path),
        `Destination "${d.label}" (${d.path}) has no route in App.tsx — it would hit the catch-all`,
      ).toBe(true);
    }
  });

  /*
   * ADR-0080 point 4: the scan reads the whole component tree, not three hand-listed files.
   *
   * It read `Sidebar.tsx`, `LibraryPage.tsx` and `ToolsPage.tsx`. That is how `StatusMenu.tsx` kept
   * a "Proposed Changes" button pointing at `/library/proposed-changes` — unmounted since ADR-0057
   * — for as long as it did: the guard whose whole purpose is catching a link to nowhere could not
   * see the file the link was in. A list of files to check is the same shape of mistake as the bug
   * it is checking for, so there is no list any more.
   */
  const componentFiles = (): string[] => {
    const dir = resolve(process.cwd(), 'src', 'components');
    return readdirSync(dir, { recursive: true, encoding: 'utf-8' })
      .filter((f) => f.endsWith('.tsx') || f.endsWith('.ts'))
      .map((f) => `components/${f}`);
  };

  /** Every internal navigation target in a file: `<Link to="/…">` and `navigate('/…')`. */
  const linkTargets = (source: string): string[] => [
    ...Array.from(source.matchAll(/\bto="(\/[^"]*)"/g), (m) => m[1]),
    ...Array.from(source.matchAll(/\bnavigate\(\s*['"](\/[^'"]*)['"]/g), (m) => m[1]),
  ];

  it('every internal link in every component is mounted', () => {
    const dead: string[] = [];
    let total = 0;

    for (const relative of componentFiles()) {
      for (const target of linkTargets(readSource(relative))) {
        total++;
        if (!isMounted(target)) dead.push(`${relative} -> ${target}`);
      }
    }

    // Finding nothing at all means the regexes stopped matching, not that the app is clean.
    expect(total).toBeGreaterThan(0);
    expect(dead, `these links have no route in App.tsx and would silently redirect:\n${dead.join('\n')}`)
      .toEqual([]);
  });

  it('the top bar is one of the files that scan reads', () => {
    // The destinations are `<Link to={item.path}>` — dynamic, so the test above cannot see them and
    // the destinations test does that job. This asserts the bar is still where the scan looks, so a
    // rename cannot quietly drop the shell's navigation out of coverage.
    expect(componentFiles()).toContain('components/TopBar.tsx');
  });
});
