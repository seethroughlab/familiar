/**
 * Navigation integrity test — ensures sidebar items, routes, and browser
 * registrations stay in sync.
 *
 * Catches bugs like a sidebar link pointing to a route that doesn't exist
 * (which silently falls through to the catch-all redirect).
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { BROWSER_ROUTES, LIBRARY_ITEMS } from '../routes';
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

  it('registered browsers are reachable via at least one route', () => {
    const routedBrowserIds = new Set<string>(BROWSER_ROUTES.map((r) => r.browserId));

    for (const id of registeredBrowserIds) {
      expect(routedBrowserIds.has(id), `Registered browser "${id}" has no route in BROWSER_ROUTES — it is unreachable`).toBe(true);
    }
  });
});
