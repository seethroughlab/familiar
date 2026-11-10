import { test, expect } from '@playwright/test';
import { ensureProfile, navigateToDestination, navigateToSection } from './helpers';

test.describe('Profiles', () => {
  test('profile selector appears on first load', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // The profile selector shows "Who's listening?"
    const profileSelector = page.getByRole('heading', { name: "Who's listening?" });
    await expect(profileSelector).toBeVisible({ timeout: 5000 });
  });

  test('create a new profile from selector', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // A fresh browser context has no profile chosen, so the selector is always shown; the test
    // above asserts it. Not finding it is a failure, not a reason to skip (ADR-0174 point 1).
    await expect(page.getByRole('heading', { name: "Who's listening?" })).toBeVisible({ timeout: 5000 });

    // Click Add Profile
    await page.getByRole('button', { name: /Add Profile/ }).click();

    // Fill in profile name
    const uniqueName = `Profile ${Date.now()}`;
    const nameInput = page.getByPlaceholder('Enter name');
    await nameInput.fill(uniqueName);

    // Click Create
    await page.getByRole('button', { name: 'Create' }).click();

    // Should transition to main app
    // The destinations of ADR-0058 point 2 — this used to wait on "Tracks"/"Artists", which the
    // sidebar stopped listing when it stopped listing browsers.
    await page.waitForSelector('a:has-text("Library"), a:has-text("Tools")', { timeout: 5000 });
  });

  test('Server → People has the profile section', async ({ page }) => {
    await page.goto('/');
    await ensureProfile(page);
    // Profiles are infrastructural (ADR-0057 point 2); under ADR-0126 they are Server → People.
    await navigateToDestination(page, 'Server');
    await navigateToSection(page, 'People');

    const profileHeading = page.getByRole('heading', { name: 'People' });
    await expect(profileHeading).toBeVisible({ timeout: 5000 });

    // Should have Switch button
    const switchBtn = page.locator('button:has-text("Switch")');
    await expect(switchBtn).toBeVisible({ timeout: 3000 });
  });

  test('can select existing profile', async ({ page, request }) => {
    // Seed the profile this test selects, rather than skipping when the server has none
    // (ADR-0174 point 1). Removed afterwards so a run leaves the server as it found it.
    const name = `E2E ${Date.now()}`;
    const created = await request.post('/api/v1/profiles', { data: { name } });
    expect(created.ok()).toBe(true);
    const { id } = await created.json();
    try {
      await page.goto('/');
      await page.waitForLoadState('networkidle');
      await page.getByRole('button', { name: new RegExp(name) }).click();
      // The destinations of ADR-0058 point 2.
      await page.waitForSelector('a:has-text("Library")', { timeout: 5000 });
    } finally {
      await request.delete(`/api/v1/profiles/${id}`);
    }
  });
});
