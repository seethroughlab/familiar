import { test, expect } from '@playwright/test';
import { ensureProfile, navigateToDestination } from './helpers';

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

    // Should see the profile selector
    const profileSelector = page.getByRole('heading', { name: "Who's listening?" });
    if (!(await profileSelector.isVisible({ timeout: 3000 }).catch(() => false))) {
      test.skip(true, 'Already logged in - profile selector not shown');
      return;
    }

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

  test('the Server destination has a profile section', async ({ page }) => {
    await page.goto('/');
    await ensureProfile(page);
    // Profiles are infrastructural (ADR-0057 point 2) and live on Server now, not in Settings.
    await navigateToDestination(page, 'Server');

    const profileHeading = page.getByRole('heading', { name: 'Profiles' });
    await expect(profileHeading).toBeVisible({ timeout: 5000 });

    // Should have Switch button
    const switchBtn = page.locator('button:has-text("Switch")');
    await expect(switchBtn).toBeVisible({ timeout: 3000 });
  });

  test('can select existing profile', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Check for profile buttons (letter + name pattern)
    const profileButtons = page.getByRole('button', { name: /^[A-Z] .+/ });
    const count = await profileButtons.count();

    if (count > 0) {
      // Click a profile
      await profileButtons.first().click();
      // Should navigate to main app
      // The destinations of ADR-0058 point 2 — this used to wait on "Tracks"/"Artists", which the
    // sidebar stopped listing when it stopped listing browsers.
    await page.waitForSelector('a:has-text("Library"), a:has-text("Tools")', { timeout: 5000 });
    } else {
      test.skip(true, 'No existing profiles to select');
    }
  });
});
