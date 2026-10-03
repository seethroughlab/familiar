import { test, expect } from '@playwright/test';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';

/**
 * Both apps are linked, each names its platform, and they are offered where the reader has chosen
 * a server: the install section's step 3 (ADR-0143), not the hero.
 *
 * The page once carried a single "Download on the App Store" badge, which could only point at one
 * listing — so the Mac app existed and the site never said so. Then both badges sat in the hero,
 * where they competed with Install (ADR-0055 point 11), and a visitor with no server who followed
 * one reached a setup screen and nothing else. Since 2026-10-02 they are in step 3 only.
 *
 * These assert the *destination*, not the styling, so the links can be restyled freely.
 */

const INDEX = pathToFileURL(join(__dirname, '..', 'index.html')).href;
const APP_ID = 'id6759879772';

test.beforeEach(async ({ page }) => {
  await page.goto(INDEX);
});

test('the Mac App Store listing is linked from step 3, with its platform stated', async ({ page }) => {
  // `?platform=mac` is load-bearing: without it Apple serves the iOS listing, and a Mac visitor
  // is told the app needs an iPhone.
  await page.locator('[data-chooser="client"]').getByRole('tab', { name: 'Mac' }).click();
  await expect(page.locator(`#c-mac a[href*="${APP_ID}"][href*="platform=mac"]`)).toBeVisible();
});

test('the iPhone listing is linked from step 3', async ({ page }) => {
  await expect(page.locator(`#c-iphone a[href*="${APP_ID}"]:not([href*="platform=mac"])`)).toBeVisible();
});

test('each badge is Apple’s own, at its native height and undistorted', async ({ page }) => {
  // Apple asks that its badges are not rescaled or stretched. The two differ in width because the
  // wordmarks do, so asserting a shared width would be the wrong check — height and the intrinsic
  // ratio are what must hold.
  for (const [tab, panel, file] of [
    ['iPhone & iPad', '#c-iphone', 'app-store-badge.svg'],
    ['Mac', '#c-mac', 'mac-app-store-badge.svg'],
  ]) {
    await page.locator('[data-chooser="client"]').getByRole('tab', { name: tab }).click();
    const img = page.locator(`${panel} img[src*="${file}"]`);
    await expect(img).toBeVisible();
    const box = await img.boundingBox();
    const natural = await img.evaluate((el: HTMLImageElement) => el.naturalWidth / el.naturalHeight);
    expect(box!.height).toBeCloseTo(40, 0);
    expect(box!.width / box!.height).toBeCloseTo(natural, 1);
  }
});

test('outside the install section, the only way in is Install', async ({ page }) => {
  // ADR-0055 point 11: one call to action. An App Store link anywhere but step 3 is offered
  // before the reader has a server to connect to.
  const stray = await page.locator(`a[href*="${APP_ID}"]`).evaluateAll((links) =>
    links.filter((a) => !a.closest('#install')).map((a) => a.getAttribute('href')),
  );
  expect(stray).toEqual([]);
  await expect(page.locator('header .hero-cta a.primary')).toHaveAttribute('href', '#install');
});
