/**
 * Mobile screenshot capture for identifying responsive design issues.
 *
 * Captures screenshots at various mobile viewport sizes.
 *
 * Prerequisites:
 * 1. Backend running on port 4400
 * 2. Frontend dev server or served by backend
 *
 * Run with: npx playwright test mobile-screenshots
 */
import { test } from '@playwright/test';
import { ensureProfile, navigateToTab, waitForContentReady } from './helpers';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const SCREENSHOT_DIR = path.join(__dirname, '..', '..', 'screenshots', 'mobile');

// Common mobile viewport sizes
const MOBILE_VIEWPORTS = {
  'iphone-se': { width: 375, height: 667 },
  'iphone-14': { width: 390, height: 844 },
  'iphone-14-pro-max': { width: 430, height: 932 },
  'pixel-7': { width: 412, height: 915 },
  'galaxy-s21': { width: 360, height: 800 },
};

// Screens to capture
const SCREENS = [
  { name: 'library', tab: 'Library' },
  { name: 'playlists', tab: 'Playlists' },
  { name: 'settings', tab: 'Settings' },
] as const;

test.beforeAll(async () => {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
});

// Test each viewport size
for (const [deviceName, viewport] of Object.entries(MOBILE_VIEWPORTS)) {
  test.describe(`Mobile - ${deviceName} (${viewport.width}x${viewport.height})`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto('/');
      await ensureProfile(page);
    });

    for (const screen of SCREENS) {
      test(`${screen.name}`, async ({ page }) => {
        await navigateToTab(page, screen.tab as 'Library' | 'Playlists' | 'Settings');
        await waitForContentReady(page, { images: true }).catch(() => {});

        await page.screenshot({
          path: path.join(SCREENSHOT_DIR, `${deviceName}-${screen.name}.png`),
          fullPage: false,
        });
      });
    }

    // Player bar test
    test('player-bar', async ({ page }) => {
      await navigateToTab(page, 'Library');

      // Try to play a track
      const trackRow = page.locator('tr[data-track-id], [role="row"]').first();
      if (await trackRow.isVisible()) {
        await trackRow.dblclick();
        await page.waitForFunction(() => !!document.querySelector('audio'), { timeout: 5000 }).catch(() => {});
      }

      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, `${deviceName}-player-bar.png`),
        fullPage: false,
      });
    });

    // Full player test
    test('full-player', async ({ page }) => {
      await navigateToTab(page, 'Library');

      // Play a track
      const trackRow = page.locator('tr[data-track-id], [role="row"]').first();
      if (await trackRow.isVisible()) {
        await trackRow.dblclick();
        await page.waitForFunction(() => !!document.querySelector('audio'), { timeout: 5000 }).catch(() => {});
      }

      // Expand to full player
      const expandButton = page.locator('button[aria-label="Expand player"]').first();
      if (await expandButton.isVisible()) {
        await expandButton.click();
        await waitForContentReady(page, { images: true }).catch(() => {});
      }

      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, `${deviceName}-full-player.png`),
        fullPage: false,
      });
    });
  });
}
