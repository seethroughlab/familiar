/**
 * Mobile screenshot capture, for spotting responsive problems across device widths.
 *
 * A development tool, not README material — the output goes to `screenshots/mobile/` and nothing
 * links to it. Its value is the sweep: five widths against the same screens, where a layout that
 * only breaks at 360px shows up.
 *
 * **`player-bar` and `full-player` were removed**, along with the `Playlists` screen. They drove a
 * player this app no longer has (ADR-0057 point 5, ADR-0071) by double-clicking a track row to
 * start audio — every one of them was photographing whatever happened to be on screen after a
 * click that did nothing.
 *
 * Run with the same setup as `screenshots.spec.ts`; see that file's header.
 */
import { test } from '@playwright/test';
import { ensureProfile, navigateToDestination, navigateToTab } from './helpers';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
// Three levels up, not two. `__dirname` is `packages/web/e2e`, so the old two-level path resolved
// to `packages/screenshots/mobile` — a directory nobody knew existed, which is where every mobile
// screenshot this file has ever taken actually went.
const SCREENSHOT_DIR = path.join(__dirname, '..', '..', '..', 'screenshots', 'mobile');

const MOBILE_VIEWPORTS = {
  'iphone-se': { width: 375, height: 667 },
  'iphone-14': { width: 390, height: 844 },
  'iphone-14-pro-max': { width: 430, height: 932 },
  'pixel-7': { width: 412, height: 915 },
  'galaxy-s21': { width: 360, height: 800 },
};

test.beforeAll(async () => {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
});

/** See `screenshots.spec.ts` for why this is not `waitForContentReady({ images: true })`. */
async function waitForSettled(page: import('@playwright/test').Page, budgetMs = 12000) {
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
  await page.waitForTimeout(600);
}

for (const [deviceName, viewport] of Object.entries(MOBILE_VIEWPORTS)) {
  test.describe(`Mobile - ${deviceName} (${viewport.width}x${viewport.height})`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto('/');
      await ensureProfile(page);
    });

    for (const destination of ['Library', 'Tools', 'Server'] as const) {
      test(`${destination.toLowerCase()} screenshot`, async ({ page }) => {
        await navigateToDestination(page, destination);
        await waitForSettled(page);
        await page.screenshot({
          path: path.join(SCREENSHOT_DIR, `${deviceName}-${destination.toLowerCase()}.png`),
          fullPage: false,
        });
      });
    }

    test('settings screenshot', async ({ page }) => {
      await navigateToTab(page, 'Settings');
      await waitForSettled(page);
      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, `${deviceName}-settings.png`),
        fullPage: false,
      });
    });
  });
}
