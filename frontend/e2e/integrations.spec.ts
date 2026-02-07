import { test, expect } from '@playwright/test';

// These tests verify the Admin panel displays integration status cards correctly.
// API keys are configured via environment variables (docker/.env).

test.describe('Admin Panel Integrations', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/admin');
    await page.waitForLoadState('networkidle');
  });

  test('shows Service Status section', async ({ page }) => {
    const statusSection = page.getByText('Service Status', { exact: true });
    await expect(statusSection).toBeVisible({ timeout: 5000 });
  });

  test('Spotify status card is visible', async ({ page }) => {
    const spotifyCard = page.getByText('Spotify', { exact: true });
    await expect(spotifyCard).toBeVisible({ timeout: 5000 });
  });

  test('Last.fm status card is visible', async ({ page }) => {
    const lastfmCard = page.getByText('Last.fm', { exact: true });
    await expect(lastfmCard).toBeVisible({ timeout: 5000 });
  });

  test('Claude API status card is visible', async ({ page }) => {
    const claudeCard = page.getByText('Claude API', { exact: true });
    await expect(claudeCard).toBeVisible({ timeout: 5000 });
  });

  test('AcoustID status card is visible', async ({ page }) => {
    const acoustidCard = page.getByText('AcoustID', { exact: true });
    await expect(acoustidCard).toBeVisible({ timeout: 5000 });
  });

  test('Community Cache section is visible', async ({ page }) => {
    const cacheSection = page.getByText('Community Cache', { exact: true });
    await expect(cacheSection).toBeVisible({ timeout: 5000 });
  });

  test('all service cards show status indicators', async ({ page }) => {
    // Each service card should have either a green check or grey X icon
    const statusGrid = page.locator('.grid-cols-2').first();
    await expect(statusGrid).toBeVisible({ timeout: 5000 });

    // There should be 4 service cards
    const serviceCards = statusGrid.locator('.bg-zinc-800');
    await expect(serviceCards).toHaveCount(4);
  });
});
