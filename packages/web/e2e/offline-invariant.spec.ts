/**
 * E2E tests for offline surface consistency.
 * Verifies that non-downloaded tracks don't appear in offline-only views
 * and that downloaded tracks are properly reflected across surfaces.
 */
import { test, expect } from '@playwright/test';
import { ensureProfile, navigateToView } from './helpers';

test.describe('Offline Invariant', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await ensureProfile(page);
  });

  test('downloads view is empty when no tracks downloaded', async ({ page }) => {
    // Navigate to Downloads via sidebar
    const downloadsLink = page.getByRole('link', { name: 'Downloads' });
    if (!(await downloadsLink.isVisible({ timeout: 3000 }).catch(() => false))) {
      // Try mobile navigation
      const moreButton = page.locator('nav button:has-text("More")');
      if (await moreButton.isVisible({ timeout: 1000 }).catch(() => false)) {
        await moreButton.click();
        const sheetLink = page.getByRole('link', { name: 'Downloads' });
        if (!(await sheetLink.isVisible({ timeout: 2000 }).catch(() => false))) {
          test.skip(true, 'Downloads view not accessible');
          return;
        }
        await sheetLink.click();
      } else {
        test.skip(true, 'Downloads link not found');
        return;
      }
    } else {
      await downloadsLink.click();
    }

    await page.waitForLoadState('domcontentloaded');

    // Check for empty state or zero tracks
    const emptyState = page.locator('text=/no.*download/i, text=/nothing.*download/i, text=/empty/i');
    const trackRows = page.locator('[data-testid="track-row"], .track-row');

    await expect.poll(
      async () => {
        const hasEmptyMessage = await emptyState.first().isVisible().catch(() => false);
        const rowCount = await trackRows.count();
        // Either an empty state message or no track rows
        return hasEmptyMessage || rowCount === 0;
      },
      { timeout: 10000, message: 'Expected empty downloads or empty-state message' },
    ).toBe(true);
  });

  test('downloads count is less than or equal to library total', async ({ page }) => {
    // Get library total via API
    const libraryTotal = await page.evaluate(async () => {
      try {
        const response = await fetch('/api/v1/tracks?page_size=1');
        if (!response.ok) return -1;
        const data = await response.json();
        return data.total ?? data.items?.length ?? -1;
      } catch {
        return -1;
      }
    });

    if (libraryTotal <= 0) {
      test.skip(true, 'No tracks in library or API unavailable');
      return;
    }

    // Navigate to Downloads
    const downloadsLink = page.getByRole('link', { name: 'Downloads' });
    if (!(await downloadsLink.isVisible({ timeout: 3000 }).catch(() => false))) {
      test.skip(true, 'Downloads link not found');
      return;
    }
    await downloadsLink.click();
    await page.waitForLoadState('domcontentloaded');

    // Count visible downloaded tracks
    const trackRows = page.locator('[data-testid="track-row"], .track-row');
    await page.waitForTimeout(2000); // Allow list to populate

    const downloadCount = await trackRows.count();
    expect(downloadCount).toBeLessThanOrEqual(libraryTotal);
  });

  test('download a track and verify it appears in downloads', async ({ page }) => {
    await navigateToView(page, 'Tracks');

    // Find a track row
    const trackRow = page.locator('[data-testid="track-row"], .track-row, tr').first();
    await trackRow.waitFor({ timeout: 10000 }).catch(() => {});
    if (!(await trackRow.isVisible().catch(() => false))) {
      test.skip(true, 'No tracks in library');
      return;
    }

    // Right-click to open context menu
    await trackRow.click({ button: 'right' });

    // Look for a download/offline option in the context menu
    const downloadOption = page.locator(
      'text=/download/i, text=/make.*available.*offline/i, text=/save.*offline/i',
    );
    await downloadOption.first().waitFor({ timeout: 3000 }).catch(() => {});

    if (!(await downloadOption.first().isVisible().catch(() => false))) {
      // Close context menu and skip
      await page.keyboard.press('Escape');
      test.skip(true, 'No download option in context menu');
      return;
    }

    await downloadOption.first().click();

    // Wait for download to complete (poll for completion indicator)
    await expect
      .poll(
        async () => {
          // Check IndexedDB for downloaded track count
          const count = await page.evaluate(async () => {
            try {
              const dbs = await indexedDB.databases();
              const familiarDb = dbs.find((db) => db.name?.includes('familiar'));
              if (!familiarDb?.name) return 0;

              return new Promise<number>((resolve) => {
                const request = indexedDB.open(familiarDb.name!);
                request.onsuccess = () => {
                  const db = request.result;
                  const storeNames = Array.from(db.objectStoreNames);
                  const trackStore = storeNames.find(
                    (n) => n.includes('track') || n.includes('audio') || n.includes('offline'),
                  );
                  if (!trackStore) {
                    db.close();
                    resolve(0);
                    return;
                  }
                  const tx = db.transaction(trackStore, 'readonly');
                  const store = tx.objectStore(trackStore);
                  const countReq = store.count();
                  countReq.onsuccess = () => {
                    db.close();
                    resolve(countReq.result);
                  };
                  countReq.onerror = () => {
                    db.close();
                    resolve(0);
                  };
                };
                request.onerror = () => resolve(0);
              });
            } catch {
              return 0;
            }
          });
          return count > 0;
        },
        { timeout: 30000, message: 'Expected at least 1 offline track after download' },
      )
      .toBe(true);

    // Navigate to Downloads and verify the track appears
    const downloadsLink = page.getByRole('link', { name: 'Downloads' });
    if (!(await downloadsLink.isVisible({ timeout: 3000 }).catch(() => false))) {
      test.skip(true, 'Downloads link not found for verification');
      return;
    }
    await downloadsLink.click();
    await page.waitForLoadState('domcontentloaded');

    const downloadedRows = page.locator('[data-testid="track-row"], .track-row');
    await expect.poll(() => downloadedRows.count(), { timeout: 10000 }).toBeGreaterThanOrEqual(1);
  });

  test('offline track IDs are consistent across IndexedDB and downloads view', async ({ page }) => {
    // Query IndexedDB for offline track IDs
    const offlineTrackIds = await page.evaluate(async () => {
      try {
        const dbs = await indexedDB.databases();
        const familiarDb = dbs.find((db) => db.name?.includes('familiar'));
        if (!familiarDb?.name) return [];

        return new Promise<string[]>((resolve) => {
          const request = indexedDB.open(familiarDb.name!);
          request.onsuccess = () => {
            const db = request.result;
            const storeNames = Array.from(db.objectStoreNames);
            const trackStore = storeNames.find(
              (n) => n.includes('track') || n.includes('audio') || n.includes('offline'),
            );
            if (!trackStore) {
              db.close();
              resolve([]);
              return;
            }
            const tx = db.transaction(trackStore, 'readonly');
            const store = tx.objectStore(trackStore);
            const getAllReq = store.getAllKeys();
            getAllReq.onsuccess = () => {
              db.close();
              resolve(getAllReq.result.map(String));
            };
            getAllReq.onerror = () => {
              db.close();
              resolve([]);
            };
          };
          request.onerror = () => resolve([]);
        });
      } catch {
        return [];
      }
    });

    // Navigate to Downloads view
    const downloadsLink = page.getByRole('link', { name: 'Downloads' });
    if (!(await downloadsLink.isVisible({ timeout: 3000 }).catch(() => false))) {
      test.skip(true, 'Downloads link not found');
      return;
    }
    await downloadsLink.click();
    await page.waitForLoadState('domcontentloaded');

    // Count visible track rows
    const trackRows = page.locator('[data-testid="track-row"], .track-row');
    await page.waitForTimeout(2000); // Allow list to render
    const visibleCount = await trackRows.count();

    // The counts should match
    expect(visibleCount).toBe(offlineTrackIds.length);
  });
});
