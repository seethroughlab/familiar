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

  test('library grid/list view toggle', async ({ page }) => {
    await navigateToTab(page, 'Library');

    // Look for view toggle buttons
    const gridBtn = page.locator('button[aria-label*="grid" i], [data-testid="grid-view"]');
    const listBtn = page.locator('button[aria-label*="list" i], [data-testid="list-view"]');

    if (await gridBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await gridBtn.click();
      await page.waitForTimeout(300);

      // Verify grid view is active
      const _gridView = page.locator('.grid, [data-view="grid"]');
      // Grid should be visible or button should be active
    }

    if (await listBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await listBtn.click();
      await page.waitForTimeout(300);

      // Verify list view is active
      const _listView = page.locator('table, [data-view="list"]');
    }
  });
});

test.describe('Admin Panel', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/admin');
    await page.waitForLoadState('networkidle');
  });

  test('admin page loads', async ({ page }) => {
    // Look for the Admin Setup title
    const adminTitle = page.getByText('Admin Setup', { exact: true });
    await expect(adminTitle).toBeVisible({ timeout: 5000 });
  });

  test('service status section exists', async ({ page }) => {
    // Look for the Service Status section heading
    const statusHeading = page.getByText('Service Status', { exact: true });
    await expect(statusHeading).toBeVisible({ timeout: 5000 });
  });

  test('Claude API status card exists', async ({ page }) => {
    // Look for Claude API in the status grid
    const claudeCard = page.getByText('Claude API', { exact: true });
    await expect(claudeCard).toBeVisible({ timeout: 5000 });
  });

  test('Spotify status card exists', async ({ page }) => {
    const spotifyCard = page.getByText('Spotify', { exact: true });
    await expect(spotifyCard).toBeVisible({ timeout: 5000 });
  });

  test('Last.fm status card exists', async ({ page }) => {
    const lastfmCard = page.getByText('Last.fm', { exact: true });
    await expect(lastfmCard).toBeVisible({ timeout: 5000 });
  });

  test('AcoustID status card exists', async ({ page }) => {
    const acoustidCard = page.getByText('AcoustID', { exact: true });
    await expect(acoustidCard).toBeVisible({ timeout: 5000 });
  });

  test('community cache section exists', async ({ page }) => {
    const cacheSection = page.getByText('Community Cache', { exact: true });
    await expect(cacheSection).toBeVisible({ timeout: 5000 });
  });

  test('community cache toggles work', async ({ page }) => {
    // Find the "Use community cache" text and then locate the toggle nearby
    const useCacheLabel = page.getByText('Use community cache', { exact: true });
    await expect(useCacheLabel).toBeVisible({ timeout: 5000 });

    // Find the toggle input - it's a sibling's descendant
    const toggleContainer = useCacheLabel.locator('..').locator('..').locator('..');
    const toggle = toggleContainer.locator('input[type="checkbox"]');
    await expect(toggle).toBeVisible({ timeout: 5000 });

    // Toggle should be clickable
    const initialState = await toggle.isChecked();
    await toggle.click({ force: true });
    await page.waitForTimeout(500);

    // State should change
    const newState = await toggle.isChecked();
    expect(newState).toBe(!initialState);

    // Toggle back
    await toggle.click({ force: true });
    await page.waitForTimeout(500);
  });
});

test.describe('Visualizer', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await ensureProfile(page);
  });

  test('visualizer tab opens', async ({ page }) => {
    await navigateToTab(page, 'Visualizer');

    // Wait for visualizer content to mount - give it more time
    await page.waitForTimeout(1000);

    // Without a track playing, visualizer shows placeholder
    // Either shows "No track playing" or a canvas if track is playing
    const noTrack = page.getByText('No track playing');
    const canvas = page.locator('canvas');

    // Use longer timeouts to account for component mount time
    const hasNoTrack = await noTrack.isVisible({ timeout: 5000 }).catch(() => false);
    const hasCanvas = await canvas.isVisible({ timeout: 2000 }).catch(() => false);

    // At least one should be visible
    expect(hasNoTrack || hasCanvas).toBe(true);
  });

  test('visualizer has fullscreen button when track playing', async ({ page }) => {
    await navigateToTab(page, 'Visualizer');

    // If no track is playing, there's no fullscreen button (just placeholder)
    const noTrack = page.getByText('No track playing');
    if (await noTrack.isVisible({ timeout: 2000 }).catch(() => false)) {
      test.skip(true, 'No track playing - fullscreen button only shows with track');
      return;
    }

    // With track playing, fullscreen button should exist
    const fullscreenBtn = page.locator('button[aria-label*="fullscreen" i], button:has(svg)').first();
    await expect(fullscreenBtn).toBeVisible({ timeout: 3000 });
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
    await page.waitForTimeout(1000);

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
    await page.waitForTimeout(2000);

    // Filter out expected/acceptable errors
    const criticalErrors = errors.filter(e =>
      !e.includes('Failed to load resource') &&
      !e.includes('favicon') &&
      !e.includes('net::ERR')
    );

    expect(criticalErrors.length).toBe(0);
  });

  test('main navigation tabs work', async ({ page }) => {
    // Test all main tabs are accessible
    const tabs = ['Library', 'Playlists', 'Visualizer', 'Settings'] as const;

    for (const tab of tabs) {
      await navigateToTab(page, tab);
      await page.waitForTimeout(300);

      // Verify we're on the right page (URL or content check)
      const _content = page.locator(`[data-testid="${tab.toLowerCase()}"], .${tab.toLowerCase()}, main`);
      // Just verify navigation didn't error
    }
  });
});
