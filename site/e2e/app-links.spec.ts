import { test, expect } from '@playwright/test';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';

/**
 * Both apps are reachable from the front page, and each names its platform.
 *
 * The page carried a single "Download on the App Store" badge, which could only point at one
 * listing — so the Mac app existed and the site never said so. A badge is also exactly the thing
 * a later redesign drops without noticing, because nothing named the platform it stood for.
 *
 * These assert the *destination*, not the styling, so the links can be restyled freely.
 */

const INDEX = pathToFileURL(join(__dirname, '..', 'index.html')).href;
const APP_ID = 'id6759879772';

test.beforeEach(async ({ page }) => {
  await page.goto(INDEX);
});

test('the Mac App Store listing is linked, with its platform stated', async ({ page }) => {
  // `?platform=mac` is load-bearing: without it Apple serves the iOS listing, and a Mac visitor
  // is told the app needs an iPhone.
  const mac = page.locator(`a[href*="${APP_ID}"][href*="platform=mac"]`);
  await expect(mac.first()).toBeVisible();
});

test('each badge is Apple’s own, at its native height and undistorted', async ({ page }) => {
  // Apple asks that its badges are not rescaled or stretched. The two differ in width because the
  // wordmarks do, so asserting a shared width would be the wrong check — height and the intrinsic
  // ratio are what must hold.
  for (const [href, file] of [
    ['platform=mac', 'mac-app-store-badge.svg'],
    [APP_ID, 'app-store-badge.svg'],
  ]) {
    const img = page.locator(`a[href*="${href}"] img[src*="${file}"]`).first();
    await expect(img).toBeVisible();
    const box = await img.boundingBox();
    const natural = await img.evaluate((el: HTMLImageElement) => el.naturalWidth / el.naturalHeight);
    expect(box!.height).toBeCloseTo(40, 0);
    expect(box!.width / box!.height).toBeCloseTo(natural, 1);
  }
});

test('the iPhone listing is linked', async ({ page }) => {
  const ios = page.locator(`a[href*="${APP_ID}"]:not([href*="platform=mac"])`);
  await expect(ios.first()).toBeVisible();
});

test('both platforms are reachable above the fold, not only in the footer', async ({ page }) => {
  const hero = page.locator('.hero-apps');
  await expect(hero).toBeVisible();
  await expect(hero.locator(`a[href*="platform=mac"]`)).toHaveCount(1);
  await expect(hero.locator(`a[href*="${APP_ID}"]`)).toHaveCount(2);
});

test('the apps still say they need a server', async ({ page }) => {
  // The reason Install stays the primary call to action (ADR-0055 point 11). Someone who arrives
  // at the App Store from here with no server gets a setup screen and nothing else, so removing
  // this sentence turns a prominent link into a dead end.
  await expect(page.locator('.app-links-note')).toContainText(/server/i);
});
