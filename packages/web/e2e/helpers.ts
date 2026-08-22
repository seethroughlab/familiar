import { Page } from '@playwright/test';

/**
 * The navigation labels that mean "the app has finished booting".
 *
 * These are the three destinations of ADR-0058 point 2, rendered as sidebar links on desktop and
 * bottom-bar buttons on mobile. They used to be 'Tracks' / 'Artists', and when the sidebar stopped
 * listing browsers **every spec in this directory failed at `ensureProfile`** — 44 tests each
 * burning the full 30s probe timeout, which cancelled the job at its 30-minute limit before
 * Playwright could print a single failure.
 *
 * So: if the navigation is restructured again, this constant is the thing to change, and it is one
 * place rather than four copies of a `querySelectorAll` predicate.
 */
const READY_LABELS = ['Library', 'Tools', 'Server'];

/**
 * Runs **in the browser**, so it takes its labels as an argument and references nothing from this
 * module's scope — `waitForFunction` serialises the body and would otherwise throw on the closure.
 */
const NAV_READY_IN_PAGE = (labels: string[]) => {
  const matches = (el: Element) =>
    labels.some((l) => el.textContent?.includes(l)) && (el as HTMLElement).offsetParent !== null;
  return (
    Array.from(document.querySelectorAll('a')).some(matches) ||
    Array.from(document.querySelectorAll('nav button')).some(matches)
  );
};

/**
 * Helper to create or select a profile before tests
 */
export async function ensureProfile(page: Page, profileName = 'Test User') {
  // Wait for page to settle (use domcontentloaded instead of networkidle to avoid timeout)
  await page.waitForLoadState('domcontentloaded');

  // Wait for the app to reach a meaningful state: either the profile selector appears
  // (meaning we need to pick/create a profile) or the nav links are already visible
  // (meaning a profile is already selected). In CI, React hydration + API calls can
  // take 10-15s, so we use a generous timeout here instead of a short isVisible check.
  const navOrProfile = await page.waitForFunction(({ labels, navReady }) => {
    // Check for profile selector heading
    const headings = document.querySelectorAll('h1, h2, h3');
    const hasProfileSelector = Array.from(headings).some(
      el => el.textContent?.includes("Who's listening?") && el.offsetParent !== null
    );
    if (hasProfileSelector) return 'profile-selector';

    // Check for visible nav (app already loaded with profile)
    if (new Function(`return (${navReady})`)()(labels)) return 'nav-ready';

    return null;
  }, { labels: READY_LABELS, navReady: NAV_READY_IN_PAGE.toString() }, { timeout: 30000 });

  const state = await navOrProfile.jsonValue();

  if (state === 'profile-selector') {
    // Find profile buttons - they have name pattern "T Test User" (letter + name)
    const profileButtons = page.getByRole('button', { name: /^[A-Z] .+/ });
    const buttonCount = await profileButtons.count();

    if (buttonCount > 0) {
      await profileButtons.first().click();
    } else {
      // No profiles exist - create one
      await page.getByRole('button', { name: /Add Profile/ }).click();
      const nameInput = page.getByPlaceholder('Enter name');
      await nameInput.waitFor({ timeout: 5000 });
      await nameInput.fill(profileName);
      await page.getByRole('button', { name: 'Create' }).click();
    }

    // Now wait for nav after profile selection
    await page.waitForFunction(
      ({ labels, navReady }) => new Function(`return (${navReady})`)()(labels),
      { labels: READY_LABELS, navReady: NAV_READY_IN_PAGE.toString() },
      { timeout: 15000 },
    );
  }
  // If state === 'nav-ready', we're already good
}

/**
 * Where each view lives now that the sidebar lists destinations rather than browsers.
 *
 * Only `Cleanup` is still mounted. The rest were unmounted by ADR-0050 and ADR-0057 —
 * `navigateToView(page, 'Artists')` and its siblings have been walking the fallback path for some
 * time, which is why they are mapped to `null`: a spec asking for one should fail saying so,
 * rather than clicking nothing and asserting against whatever page it happened to stay on.
 */
const VIEW_PATHS: Record<string, { destination: string; link: string } | null> = {
  // ADR-0058 point 3 had moved the track list onto the Tools page while the player was still
  // scheduled for deletion. It has now been deleted, and ADR-0057 point 5 took the "Track list"
  // link with it — a capability and its affordances leave together. There is no tracks browser
  // left to reach: `BROWSER_ROUTES` is down to `artist-cleanup` alone.
  Tracks: null,
  Cleanup: { destination: 'Library', link: 'Artist cleanup' },
  Artists: null,
  Albums: null,
  'Mood Grid': null,
  'Music Map': null,
  '3D Explorer': null,
  Discover: null,
};

/**
 * Go to one of the three destinations (ADR-0058 point 2).
 *
 * Most of what used to be on the Settings page now lives on one of these: scan and analysis on
 * Library, keys and profiles and diagnostics on Server, backup and community cache on Tools.
 */
export async function navigateToDestination(
  page: Page,
  destination: 'Library' | 'Tools' | 'Server',
) {
  await clickNav(page, destination);
}

/**
 * Click a link or nav button by its visible text, desktop or mobile.
 *
 * The sidebar renders `<Link>`s; the mobile bottom bar renders `<button>`s. Both carry the same
 * labels, so one helper covers both viewports.
 */
async function clickNav(page: Page, label: string) {
  const link = page.getByRole('link', { name: label, exact: true }).first();
  if (await link.isVisible({ timeout: 5000 }).catch(() => false)) {
    await link.click();
    await page.waitForLoadState('domcontentloaded');
    return;
  }

  const button = page.locator(`nav button:has-text("${label}")`).first();
  if (await button.isVisible({ timeout: 2000 }).catch(() => false)) {
    await button.click();
    await page.waitForLoadState('domcontentloaded');
    return;
  }

  // Not exact-matched anywhere: fall back to a substring link, then let Playwright report it.
  const loose = page.getByRole('link', { name: label }).first();
  await loose.click({ timeout: 5000 });
  await page.waitForLoadState('domcontentloaded');
}

/**
 * Navigate to a specific view, **by clicking**, the way someone actually reaches it.
 *
 * Deliberately not `page.goto`: that is a full document load, and every spec here calls
 * `ensureProfile` once in `beforeEach` and then expects the app to stay booted. Client-side
 * routing keeps it that way; a reload re-runs the whole boot on every navigation.
 */
export async function navigateToView(page: Page, label: string) {
  if (label in VIEW_PATHS) {
    const path = VIEW_PATHS[label];
    if (path === null) {
      throw new Error(
        `navigateToView("${label}"): that view is not mounted in the web app (ADR-0050/0057). ` +
          `Update the spec rather than the helper.`,
      );
    }
    await clickNav(page, path.destination);
    await clickNav(page, path.link);
    return;
  }

  // Desktop: sidebar link is visible
  const link = page.getByRole('link', { name: label, exact: true });
  if (await link.isVisible({ timeout: 2000 }).catch(() => false)) {
    await link.click();
    await page.waitForLoadState('domcontentloaded');
    return;
  }

  // Mobile: try bottom nav button directly (Tracks, Artists, Favorites, Chat)
  const mobileButton = page.locator(`nav button:has-text("${label}")`);
  if (await mobileButton.isVisible({ timeout: 1000 }).catch(() => false)) {
    await mobileButton.click();
    await page.waitForLoadState('domcontentloaded');
    return;
  }

  // Mobile: open "More" sheet and find the link there
  const moreButton = page.locator('nav button:has-text("More")');
  if (await moreButton.isVisible({ timeout: 1000 }).catch(() => false)) {
    await moreButton.click();
    const sheetLink = page.getByRole('link', { name: label, exact: true });
    await sheetLink.waitFor({ timeout: 3000 });
    await sheetLink.click();
    await page.waitForLoadState('domcontentloaded');
    return;
  }

  // Fallback: try clicking the link anyway (will fail with a clear error)
  await link.click();
  await page.waitForLoadState('domcontentloaded');
}


/**
 * Navigate to a specific section in the sidebar-based UI.
 *
 * `Queue` is gone from the union: the queue left with the player (ADR-0057 point 5), and its case
 * here was already a no-op, so a spec asking for it would have silently asserted against whatever
 * page it happened to be on. Removing it from the type makes that a compile error instead.
 */
export async function navigateToTab(page: Page, tabName: 'Library' | 'Playlists' | 'Settings') {
  switch (tabName) {
    case 'Library': {
      // Was `navigateToView(page, 'Tracks')`, which reached the track list on the Tools page.
      // Both are gone; Library is a destination in its own right and is where the app opens
      // (ADR-0058 points 1 and 2).
      await navigateToDestination(page, 'Library');
      break;
    }
    case 'Settings': {
      // Was a `navigate-to-settings` window event. Deleting the player deleted `useAppBootstrap`,
      // and the listener with it, so the event reached nothing — the test failed here rather than
      // on an assertion, which is how the dead affordance in `StatusMenu` was found.
      //
      // Clicking the sidebar's own Settings control is what a person does, and it fails loudly if
      // that control ever goes the same way. The old comment justified the event by saying a click
      // was "unreliable in CI behind the player bar overlay" — there is no player bar now.
      //
      // Not `clickNav`: Settings is deliberately not a destination, so it sits in the sidebar
      // *footer*, outside the `<nav>` that `clickNav`'s button selector is scoped to. Desktop
      // renders it as a `<button>` (labelled by its text expanded, by `title` collapsed); the
      // mobile bar renders a `<Link>`. Try both, same as `clickNav` does for destinations.
      const settingsButton = page.getByRole('button', { name: 'Settings' }).first();
      if (await settingsButton.isVisible({ timeout: 5000 }).catch(() => false)) {
        await settingsButton.click();
      } else {
        await page.getByRole('link', { name: 'Settings' }).first().click({ timeout: 5000 });
      }
      await page.waitForSelector('h2:has-text("Settings")', { timeout: 10000 });
      break;
    }
    case 'Playlists':
      // Visible in the sidebar by default, no navigation needed
      break;
  }
}

/**
 * Wait for library sync to complete
 */
export async function waitForSyncComplete(page: Page, timeout = 120000) {
  const startTime = Date.now();

  while (Date.now() - startTime < timeout) {
    // Check sync status via page context
    const status = await page.evaluate(async () => {
      const response = await fetch('/api/v1/library/sync/status');
      if (response.ok) {
        return response.json();
      }
      return null;
    });

    if (status && (status.status === 'idle' || status.status === 'completed' || status.status === 'complete')) {
      return status;
    }

    if (status && status.status === 'error') {
      throw new Error(`Sync failed: ${status.message}`);
    }

    await page.waitForTimeout(1000);
  }

  throw new Error('Sync timed out');
}

/**
 * Trigger library sync and wait for completion
 */
export async function syncLibraryAndWait(page: Page, timeout = 120000) {
  // Trigger sync
  const startResult = await page.evaluate(async () => {
    const response = await fetch('/api/v1/library/sync', { method: 'POST' });
    if (response.ok) {
      return response.json();
    }
    return null;
  });

  if (!startResult) {
    throw new Error('Failed to start sync');
  }

  if (startResult.status === 'already_running') {
    // Wait for existing sync to complete
    return waitForSyncComplete(page, timeout);
  }

  // Wait for sync to complete
  return waitForSyncComplete(page, timeout);
}

/**
 * Check if analysis is complete for tracks
 */
export async function waitForAnalysisComplete(page: Page, timeout = 180000) {
  const startTime = Date.now();

  while (Date.now() - startTime < timeout) {
    const stats = await page.evaluate(async () => {
      const response = await fetch('/api/v1/library/stats');
      if (response.ok) {
        return response.json();
      }
      return null;
    });

    if (stats) {
      const total = stats.total_tracks || 0;
      const analyzed = stats.analyzed_tracks || 0;
      const pending = stats.pending_analysis || 0;

      if (total === 0 || pending === 0 || analyzed >= total) {
        return { total, analyzed, pending };
      }
    }

    await page.waitForTimeout(2000);
  }

  throw new Error('Analysis timed out');
}

// ============================================================================
// Crossfade / Audio Playback Helpers
// ============================================================================

/**
 * Wait for visual content (images/canvas) to be ready for screenshots.
 */
export async function waitForContentReady(page: Page, opts?: {
  images?: boolean; canvas?: boolean; timeout?: number
}) {
  const timeout = opts?.timeout ?? 10000;
  if (opts?.images) {
    await page.waitForFunction(() => {
      const images = Array.from(document.querySelectorAll('img'));
      return images.length > 0 && images.every(img => img.complete);
    }, { timeout }).catch(() => {});
  }
  if (opts?.canvas) {
    await page.waitForSelector('canvas', { timeout }).catch(() => {});
  }
}
