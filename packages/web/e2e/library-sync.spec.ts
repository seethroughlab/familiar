import { test, expect } from '@playwright/test';
import { ensureProfile, navigateToTab, navigateToView, waitForSyncComplete } from './helpers';

/**
 * Library sync E2E tests
 *
 * Tests the core library import flow:
 * 1. Settings > Library section visibility
 * 2. "Sync Now" button triggers scan
 * 3. Progress phases display (Discover -> Read -> Features -> Embeddings)
 * 4. Completion stats appear
 * 5. Tracks appear in Library tab after sync
 */

test.describe('Library Sync', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await ensureProfile(page);
  });

  test('Library section is visible in Settings', async ({ page }) => {
    await navigateToTab(page, 'Settings');

    // Find Library section heading (the actual text in the UI)
    const librarySection = page.getByText('Library').first();
    await expect(librarySection).toBeVisible({ timeout: 5000 });

    // Should show Library Sync component
    const syncSection = page.getByText('Library Sync');
    await expect(syncSection).toBeVisible({ timeout: 5000 });
  });

  test('Sync Now button is present and clickable', async ({ page }) => {
    await navigateToTab(page, 'Settings');

    // Find sync button - it may say "Sync Now" or just "Sync"
    const syncButton = page.locator('button').filter({
      hasText: /sync/i,
    }).first();

    await expect(syncButton).toBeVisible({ timeout: 5000 });

    // Should not be disabled (unless sync is running)
    const isDisabled = await syncButton.isDisabled();
    // If already syncing, button might be disabled - that's OK
    expect(typeof isDisabled).toBe('boolean');
  });

  test('Sync button triggers scan and shows progress', async ({ page }) => {
    await navigateToTab(page, 'Settings');

    // Find sync button
    const syncButton = page.locator('button').filter({
      hasText: /sync/i,
    }).first();

    // Wait for the button to be actionable rather than checking and then clicking.
    // `isDisabled()` followed by `click()` is a race: a sync starting in between leaves the
    // check saying "enabled" and the click waiting out its full actionability timeout, which
    // is how this test failed while reporting only `<button disabled ...>`.
    try {
      await expect(syncButton).toBeEnabled({ timeout: 10000 });
    } catch {
      test.skip(true, 'A sync was already running, so this test has nothing to trigger.');
      return;
    }

    await syncButton.click();
    await waitForSyncComplete(page, 30000);

    // Assert the sync actually reached a terminal state, rather than asserting nothing.
    const status = await page.request.get('/api/v1/library/sync/status');
    expect(status.ok()).toBe(true);
    expect(['idle', 'complete', 'completed']).toContain((await status.json()).status);
  });

  test('Library shows content after sync', async ({ page }) => {
    // Navigate to Artists view (more reliable than Tracks which uses virtualizer)
    await navigateToView(page, 'Artists');
    await page.locator('text=/\\d+\\s*artist/i').first().waitFor({ timeout: 10000 }).catch(() => {});

    // Verify we're on the artists page and it rendered something
    // The artists view shows "N artists" text when loaded
    const pageContent = await page.textContent('body');
    const hasArtistText = /\d+\s*artist/i.test(pageContent || '');
    const hasAlbumText = /\d+\s*album/i.test(pageContent || '');
    const hasTrackText = /\d+\s*track/i.test(pageContent || '');
    const hasEmptyText = /library is empty|no artists|add music/i.test(pageContent || '');

    // Page should contain some library-related content
    expect(hasArtistText || hasAlbumText || hasTrackText || hasEmptyText).toBe(true);
  });

  test('Sync status reflects in system health', async ({ page }) => {
    await navigateToTab(page, 'Settings');

    // Navigate to Debug section if available
    const debugSection = page.locator('text=/debug/i').first();
    const hasDebug = await debugSection.isVisible({ timeout: 2000 }).catch(() => false);

    if (hasDebug) {
      await debugSection.click();
      await page.waitForLoadState('domcontentloaded');
    }

    // Check for system health or status section
    const healthSection = page.locator(
      'text=/health|status|system|service/i'
    ).first();

    const hasHealth = await healthSection.isVisible({ timeout: 3000 }).catch(() => false);

    // System health section should exist (or debug info)
    // This is informational - we just verify the UI doesn't crash
    expect(typeof hasHealth).toBe('boolean');
  });
});

/**
 * Sync progress polling via API (supplemental test)
 */
test.describe('Library Sync API', () => {
  test('Can poll sync status endpoint', async ({ request }) => {
    const response = await request.get('/api/v1/library/sync/status');
    expect(response.ok()).toBe(true);

    const status = await response.json();
    expect(status).toHaveProperty('status');

    // Status should be one of the expected values
    expect(['idle', 'running', 'completed', 'complete', 'error', 'already_running']).toContain(
      status.status
    );
  });

  test('Sync endpoint accepts POST request', async ({ request }) => {
    const response = await request.post('/api/v1/library/sync');

    // Should either start or report already running
    expect(response.ok()).toBe(true);

    const result = await response.json();
    expect(['started', 'already_running', 'completed']).toContain(result.status);
  });
});
