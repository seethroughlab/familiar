/**
 * Screenshot capture for the README.
 *
 * **This captures the web app, which is an administration tool** — three destinations and a
 * settings page (ADR-0058 point 2). It is deliberately not a tour of the library: browsing and
 * playing moved to the Mac and iPhone (ADR-0013, docs/WEB-PARITY.md), and the screenshots for
 * those come from the apps themselves and live beside these as `mac-*.png`.
 *
 * The previous version of this file shot Tracks, Artists, Albums, Mood Grid, Music Map, the 3D
 * Explorer, the full player and a mobile player. **Every one of those surfaces has been unmounted
 * or deleted** — by ADR-0050, ADR-0057 and ADR-0071 — so the suite could not have run since, and
 * the README advertised an app that no longer exists. It was excluded from CI by
 * `--grep-invert="screenshot"`, so nothing said so.
 *
 * Prerequisites: a backend with a library, and the frontend pointed at it. Against the demo server:
 *
 *   cd packages/web && VITE_API_TARGET=https://familiar-demo.fly.dev pnpm dev
 *   BASE_URL=http://localhost:3000 npx playwright test --grep="screenshot"
 *
 * Screenshots are written to `screenshots/` at the repo root.
 */
import { test, expect } from '@playwright/test';
import { ensureProfile, navigateToDestination } from './helpers';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const SCREENSHOT_DIR = path.join(__dirname, '..', '..', '..', 'screenshots');

const VIEWPORT = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

test.beforeAll(async () => {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
});

/**
 * Wait until the page has stopped loading things, then settle.
 *
 * Every admin surface here fills asynchronously — stats, health, integrations — and a fixed pause
 * photographs spinners and em-dashes. This waits for the loading affordances to go, on a budget
 * this file controls.
 *
 * **Not `waitForContentReady({ images: true })`.** That helper does not honour the timeout it is
 * given while the page is still re-rendering: asked for 8s, measured at 27s, which is what blew the
 * budget on every screen with artwork. The `Promise.race` below is the guard against the same
 * thing happening here — `waitForFunction`'s own timeout is not trusted on its own.
 */
async function waitForSettled(page: import('@playwright/test').Page, budgetMs = 15000) {
  const settled = page
    .waitForFunction(
      () => {
        if (document.querySelector('.animate-spin')) return false;
        const text = document.body.innerText || '';
        return !/Loading\.\.\.|Checking system status|Loading…/i.test(text);
      },
      { timeout: budgetMs },
    )
    .catch(() => {});
  await Promise.race([settled, new Promise((resolve) => setTimeout(resolve, budgetMs + 1000))]);
  await page.waitForTimeout(800);
}

async function takeScreenshot(page: import('@playwright/test').Page, name: string) {
  await waitForSettled(page);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, name), fullPage: false });
}

test.describe('Profile Selector', () => {
  test('00 - Profile Selector screenshot', async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/');
    // Deliberately before `ensureProfile`: this is the one screen that exists only until a profile
    // is chosen, so selecting one first would make it unphotographable.
    const heading = page.getByText(/Who's listening|Select a profile|Choose a profile/i).first();
    await heading.waitFor({ timeout: 10000 }).catch(() => {});
    await takeScreenshot(page, '00-profile-selector.png');
  });
});

test.describe('Admin surfaces', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/');
    await ensureProfile(page);
  });

  test('01 - Library destination screenshot', async ({ page }) => {
    // Where the app opens (ADR-0058 point 1): the thing being administered, not a form.
    await navigateToDestination(page, 'Library');
    await expect(page.getByRole('heading', { name: 'Library', exact: true }).first()).toBeVisible({
      timeout: 15000,
    });
    await takeScreenshot(page, '01-library.png');
  });

  test('02 - Tools destination screenshot', async ({ page }) => {
    await navigateToDestination(page, 'Tools');
    await expect(page.getByRole('heading', { name: 'Tools', exact: true }).first()).toBeVisible({
      timeout: 15000,
    });
    await takeScreenshot(page, '02-tools.png');
  });

  test('03 - Server destination screenshot', async ({ page }) => {
    await navigateToDestination(page, 'Server');
    await expect(page.getByRole('heading', { name: 'Server', exact: true }).first()).toBeVisible({
      timeout: 15000,
    });
    await takeScreenshot(page, '03-server.png');
  });

  test('05 - Duplicates screenshot', async ({ page }) => {
    // Preview-only — the server exposes no apply route for it, which the page says on its face.
    await page.goto('/tools/duplicates');
    await page.waitForLoadState('domcontentloaded');
    await takeScreenshot(page, '05-tools-duplicates.png');
  });

  test('06 - Artist cleanup screenshot', async ({ page }) => {
    // The one library browser the web app still mounts, and the reason it stayed: no native
    // equivalent, and its API tag is not in the generated Swift client.
    await page.goto('/tools/artists');
    await page.waitForLoadState('domcontentloaded');
    await takeScreenshot(page, '06-artist-cleanup.png');
  });
});

test.describe('Mobile', () => {
  test('07 - Mobile admin screenshot', async ({ page }) => {
    await page.setViewportSize(MOBILE);
    await page.goto('/');
    await ensureProfile(page);
    await takeScreenshot(page, '07-mobile-library.png');
  });
});
