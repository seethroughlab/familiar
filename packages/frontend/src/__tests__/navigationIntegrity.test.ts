/**
 * Navigation integrity test — ensures sidebar items, routes, and browser
 * registrations stay in sync.
 *
 * Catches bugs like a sidebar link pointing to a route that doesn't exist
 * (which silently falls through to the catch-all redirect).
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { BROWSER_ROUTES, LIBRARY_ITEMS, PARKED_BROWSERS } from '../routes';
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
