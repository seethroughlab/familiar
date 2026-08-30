/**
 * Navigation integrity — every link in the app resolves to a route that is mounted.
 *
 * **This file used to be mostly about a browser registry, and that half is deleted** with the
 * registry itself (ADR-0081 point 3). Those tests checked that `BROWSER_ROUTES`, `LIBRARY_ITEMS`
 * and `PARKED_BROWSERS` agreed with each other — three lists whose only remaining member was
 * reached by a plain import that bypassed all of them.
 *
 * What survives is the half that reads the source, and it is the half that ever caught anything.
 * Its own note below records why: `/favorites` and `/downloads` sat in the sidebar through the
 * whole of the ADR-0057 strip, silently redirecting to the catch-all, and the registry-based guard
 * did not notice because they were hardcoded in a component rather than declared in a list.
 *
 * It earned its place again during ADR-0081: moving artist cleanup to `/tools/artists` left a
 * `<Link to="/library/artist-cleanup">` in `LibraryPage.tsx` pointing at a route that no longer
 * existed.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, it, expect } from 'vitest';
import { DESTINATIONS } from '../app/routes';

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

  const appSource = readSource('app/App.tsx');

  /** Absolute paths `App.tsx` mounts, plus the `/library/:path` routes it maps from the registry. */
  const mountedPaths = new Set<string>([
    ...Array.from(appSource.matchAll(/path="(\/[^"*]*)"/g), (m) => m[1]),
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
    // **All of `src/`, not `src/components/`.** ADR-0081 split the tree into `app/`, `screens/` and
    // `panels/`, and a scan rooted at `components/` would have quietly stopped covering two of the
    // three — the same shape of mistake as the bug this checks for, arriving by directory rather
    // than by list.
    const dir = resolve(process.cwd(), 'src');
    return readdirSync(dir, { recursive: true, encoding: 'utf-8' })
      .filter((f) => (f.endsWith('.tsx') || f.endsWith('.ts')) && !f.includes('__tests__'));
  };

  /**
   * Every internal navigation target in a file: `<Link to="/…">` and `navigate('/…')`.
   *
   * **Comments are stripped first.** `App.tsx` explains the catch-all with the sentence "this was
   * `Navigate to="/settings"`" — a description of what the code used to be — and scanning the raw
   * source reported it as a dead link. A check that cannot tell a thing from an account of the
   * thing is the same defect it exists to catch.
   */
  const stripComments = (source: string): string =>
    source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

  const linkTargets = (source: string): string[] => {
    const code = stripComments(source);
    return [
      ...Array.from(code.matchAll(/\bto="(\/[^"]*)"/g), (m) => m[1]),
      ...Array.from(code.matchAll(/\bnavigate\(\s*['"](\/[^'"]*)['"]/g), (m) => m[1]),
    ];
  };

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
    expect(componentFiles()).toContain('app/TopBar.tsx');
  });
});
