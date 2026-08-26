import { test, expect } from '@playwright/test';
import { ensureProfile, navigateToDestination } from './helpers';

test.describe('Settings', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await ensureProfile(page);
  });

  test('a settings URL lands on the dashboard', async ({ page }) => {
    // ADR-0080 deleted the destination — theme was the only control left on it, and the interface
    // is one look now. An old bookmark hits the catch-all rather than an error, which is the whole
    // point of the catch-all; asserting it here keeps that promise honest.
    await page.goto('/settings');
    await page.waitForLoadState('domcontentloaded');
    await expect(page.getByRole('heading', { name: 'Library', exact: true }).first())
      .toBeVisible({ timeout: 10000 });
  });

  test('API key status is visible on the Server destination', async ({ page }) => {
    // Keys are infrastructural (ADR-0057 point 2) and moved to Server with ADR-0058 point 2.
    await navigateToDestination(page, 'Server');

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

  test('community cache is visible on the Tools destination', async ({ page }) => {
    await navigateToDestination(page, 'Tools');

    // Should see the Community Cache section
    const cacheHeading = page.getByText('Community Cache', { exact: true });
    await expect(cacheHeading).toBeVisible({ timeout: 5000 });

    // Should show both toggles
    await expect(page.getByText('Use community cache', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Contribute to cache', { exact: true })).toBeVisible({ timeout: 5000 });
  });
});

test.describe('UI Elements', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await ensureProfile(page);
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

  test('main navigation works', async ({ page }) => {
    // The top bar lists destinations, not browsers (ADR-0058 point 2, ADR-0080 point 1). Of the
    // browsers only
    // Cleanup is still reachable — the track list left with the player (ADR-0057 point 5) — which
    // the navigation helpers cover; what this asserts is that each destination is mounted and
    // renders its own heading, the failure `navigationIntegrity.test.ts` guards statically.
    const destinations = [
      { link: 'Tools', heading: 'Tools' },
      { link: 'Server', heading: 'Server' },
      { link: 'Library', heading: 'Library' },
    ] as const;

    for (const { link, heading } of destinations) {
      await navigateToDestination(page, link);
      await expect(page.getByRole('heading', { name: heading, exact: true }).first())
        .toBeVisible({ timeout: 10000 });
    }
  });
});
