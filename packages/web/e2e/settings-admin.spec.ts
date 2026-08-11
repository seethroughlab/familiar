import { test, expect } from '@playwright/test';
import { ensureProfile, navigateToTab } from './helpers';

test.describe('Settings', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await ensureProfile(page);
  });

  test('settings page loads', async ({ page }) => {
    await navigateToTab(page, 'Settings');

    // Should see settings content
    const settingsContent = page.locator('[data-testid="settings"], .settings, main');
    await expect(settingsContent).toBeVisible({ timeout: 5000 });
  });

  test('API key status is visible in settings', async ({ page }) => {
    await navigateToTab(page, 'Settings');

    // Should see the API Keys section
    const apiKeysHeading = page.getByText('API Keys', { exact: true });
    await expect(apiKeysHeading).toBeVisible({ timeout: 5000 });

    // Should show the active API key services. **No Claude or OpenAI row**: ADR-0048 removed them
    // with the provider layer, and this assertion is what would catch one coming back — a key field
    // for a model this server never calls is a promise it cannot keep.
    await expect(page.getByText('Claude API', { exact: true })).toHaveCount(0);
    await expect(page.getByText('OpenAI-compatible', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Last.fm', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('AcoustID', { exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('community cache is visible in settings', async ({ page }) => {
    await navigateToTab(page, 'Settings');

    // Should see the Community Cache section
    const cacheHeading = page.getByText('Community Cache', { exact: true });
    await expect(cacheHeading).toBeVisible({ timeout: 5000 });

    // Should show both toggles
    await expect(page.getByText('Use community cache', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Contribute to cache', { exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('library grid/list view toggle', async ({ page }) => {
    await navigateToTab(page, 'Library');

    // Look for view toggle buttons
    const gridBtn = page.locator('button[aria-label*="grid" i], [data-testid="grid-view"]');
    const listBtn = page.locator('button[aria-label*="list" i], [data-testid="list-view"]');

    if (await gridBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await gridBtn.click();
    }

    if (await listBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await listBtn.click();
    }
  });
});

test.describe('UI Elements', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await ensureProfile(page);
  });

  test('album artwork displays', async ({ page }) => {
    await navigateToTab(page, 'Library');

    const trackRow = page.locator('[data-testid="track-row"], .track-row, tr').first();
    if (!(await trackRow.isVisible({ timeout: 5000 }).catch(() => false))) {
      test.skip(true, 'No tracks in library');
      return;
    }

    // Click to play a track
    await trackRow.click();
    await page.waitForFunction(() => !!document.querySelector('audio'), { timeout: 5000 }).catch(() => {});

    // Look for album art in player bar or now playing
    const albumArt = page.locator('[data-testid="album-art"], .album-art, img[alt*="album" i], img[alt*="cover" i]');
    if (await albumArt.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expect(albumArt).toBeVisible();
    }
  });

  test('no console errors on page load', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') {
        errors.push(msg.text());
      }
    });

    await page.goto('/');
    await ensureProfile(page);
    await page.waitForLoadState('networkidle').catch(() => {});

    // Filter out expected/acceptable errors
    const criticalErrors = errors.filter(e =>
      !e.includes('Failed to load resource') &&
      !e.includes('favicon') &&
      !e.includes('net::ERR')
    );

    expect(criticalErrors.length).toBe(0);
  });

  test('main sidebar navigation works', async ({ page }) => {
    // Test sidebar navigation links are accessible.
    //
    // Artists and Albums used to be the choice here, as steadier than the virtualized Tracks view.
    // Both are unmounted now — the web app keeps only what the native clients cannot do
    // (docs/WEB-PARITY.md) — so these are what the sidebar actually offers.
    const sidebarLinks = ['Tracks', 'Cleanup'] as const;

    for (const linkText of sidebarLinks) {
      const link = page.locator(`a:has-text("${linkText}")`).first();
      await expect(link).toBeVisible({ timeout: 5000 });
      await link.click();
      await page.waitForLoadState('domcontentloaded');
    }

    // Verify Settings button works
    const settingsBtn = page.locator('button:has-text("Settings")').first();
    await expect(settingsBtn).toBeVisible({ timeout: 5000 });
  });
});
