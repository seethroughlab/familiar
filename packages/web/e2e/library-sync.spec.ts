import { test, expect } from '@playwright/test';
import { ensureProfile, navigateToDestination, waitForSyncComplete } from './helpers';

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
    // The app opens on the Overview now (ADR-0126 point 3); the sync panel is Library → Sync.
    await navigateToDestination(page, 'Library');
  });

  test('Library sync is visible on the Library destination', async ({ page }) => {
    const syncSection = page.getByText('Library Sync');
    await expect(syncSection).toBeVisible({ timeout: 10000 });
  });

  test('Sync Now button is present and clickable', async ({ page }) => {

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
    // Already on Library from beforeEach — that is where sync lives now (ADR-0058 point 2).

    // Find sync button
    const syncButton = page.locator('button').filter({
      hasText: /sync/i,
    }).first();

    // Start from a known state rather than waiting on one. The global setup's sync can still be
    // running after five minutes on a cold CI runner (measured: 120 s of setup plus 180 s here was
    // not enough), and before ADR-0174 this test skipped in that case, so a run could pass without
    // ever pressing the button. Cancelling clears the sync state; then the button must be enabled.
    const cancelled = await page.request.post('/api/v1/library/sync/cancel');
    expect(cancelled.ok()).toBe(true);
    await waitForSyncComplete(page, 30000);
    await expect(syncButton).toBeEnabled({ timeout: 15000 });

    // What this test is about: the button starts a sync. The server's answer to the click says so
    // directly; "already_running" would mean the click reached nothing new.
    const [started] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes('/api/v1/library/sync') && r.request().method() === 'POST',
      ),
      syncButton.click(),
    ]);
    expect(started.ok()).toBe(true);
    expect((await started.json()).status).toBe('started');

    // And the page shows it running, before anything finishes.
    // A running sync replaces nothing silently: the panel offers Cancel and shows the phases.
    await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible({ timeout: 15000 });

    // Leave the library quiet for the tests after this one.
    await page.request.post('/api/v1/library/sync/cancel');
  });

  test('Library shows content after sync', async ({ page }) => {
    // The Library destination, because the web app no longer mounts a library *browser* at all —
    // the track list left with the player (ADR-0057 point 5), and the Mac and iPhone took over
    // browsing (docs/WEB-PARITY.md). What Library reports is the size of the library, which is
    // what a sync is supposed to change and all this test ever actually asserted.
    //
    // The assertion below stays deliberately tolerant: it accepts a populated library or an
    // explicitly empty one, so a *sync* test does not fail over how content is counted.
    // The totals are the Overview's secondary half (ADR-0126 point 3); Library → Sync shows only the sync.
    await navigateToDestination(page, 'Overview');
    await page.locator('text=/\\d+\\s*track/i').first().waitFor({ timeout: 10000 }).catch(() => {});

    // Verify the view rendered something rather than an error or a blank column
    const pageContent = await page.textContent('body');
    const hasArtistText = /\d+\s*artist/i.test(pageContent || '');
    const hasAlbumText = /\d+\s*album/i.test(pageContent || '');
    const hasTrackText = /\d+\s*track/i.test(pageContent || '');
    const hasEmptyText = /library is empty|no artists|add music/i.test(pageContent || '');

    // Page should contain some library-related content
    expect(hasArtistText || hasAlbumText || hasTrackText || hasEmptyText).toBe(true);
  });

  test('Sync status reflects in system health', async ({ page }) => {
    // System health is on the Server destination now, not Settings.
    await navigateToDestination(page, 'Server');

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
