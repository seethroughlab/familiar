import { Page } from '@playwright/test';

/**
 * Helper to create or select a profile before tests
 */
export async function ensureProfile(page: Page, profileName = 'Test User') {
  // Wait for page to settle (use domcontentloaded instead of networkidle to avoid timeout)
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(1000); // Brief wait for initial render

  // Check if we're on profile selector (shows "Who's listening?")
  const profileSelector = page.getByRole('heading', { name: "Who's listening?" });
  if (await profileSelector.isVisible({ timeout: 3000 }).catch(() => false)) {
    // Find profile buttons - they have name pattern "T Test User" (letter + name)
    const profileButtons = page.getByRole('button', { name: /^[A-Z] .+/ });
    const buttonCount = await profileButtons.count();

    if (buttonCount > 0) {
      // Click the first profile button
      await profileButtons.first().click();
    } else {
      // No profiles exist - create one
      await page.getByRole('button', { name: /Add Profile/ }).click();
      await page.waitForTimeout(300);

      // Fill in profile name in the modal dialog
      const nameInput = page.getByPlaceholder('Enter name');
      await nameInput.waitFor({ timeout: 3000 });
      await nameInput.fill(profileName);

      // Click Create button
      await page.getByRole('button', { name: 'Create' }).click();
    }

    // Wait for app to load after profile selection
    await page.waitForTimeout(500);
  }

  // Wait for main app to load - Library button indicates we're in the app
  await page.waitForSelector('button:has-text("Library")', { timeout: 10000 });
}

/**
 * Navigate to a specific tab in the main UI
 */
export async function navigateToTab(page: Page, tabName: 'Library' | 'Playlists' | 'Queue' | 'Visualizer' | 'Settings') {
  // The tab buttons contain the text directly
  const tabButton = page.locator(`button:has-text("${tabName}")`).first();
  await tabButton.click();
  await page.waitForTimeout(300); // Allow tab transition
}

/**
 * Navigate to admin page
 */
export async function navigateToAdmin(page: Page) {
  await page.goto('/admin');
  await page.waitForLoadState('networkidle');
}

/**
 * Get the audio element from the page
 */
export async function getAudioElement(page: Page) {
  return page.locator('audio').first();
}

/**
 * Check if audio is currently playing
 */
export async function isAudioPlaying(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const audio = document.querySelector('audio');
    return audio ? !audio.paused : false;
  });
}

/**
 * Get current audio time
 */
export async function getAudioCurrentTime(page: Page): Promise<number> {
  return page.evaluate(() => {
    const audio = document.querySelector('audio');
    return audio ? audio.currentTime : 0;
  });
}

/**
 * Get audio duration
 */
export async function getAudioDuration(page: Page): Promise<number> {
  return page.evaluate(() => {
    const audio = document.querySelector('audio');
    return audio ? audio.duration : 0;
  });
}

/**
 * Get audio volume
 */
export async function getAudioVolume(page: Page): Promise<number> {
  return page.evaluate(() => {
    const audio = document.querySelector('audio');
    return audio ? audio.volume : 0;
  });
}

/**
 * Wait for audio to be ready
 */
export async function waitForAudioReady(page: Page, timeout = 10000) {
  await page.waitForFunction(
    () => {
      const audio = document.querySelector('audio');
      return audio && audio.readyState >= 2; // HAVE_CURRENT_DATA
    },
    { timeout }
  );
}
