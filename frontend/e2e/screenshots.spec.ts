/**
 * Screenshot capture script for README documentation.
 *
 * Captures screenshots of all main interface screens.
 *
 * Prerequisites:
 * 1. Backend running: cd backend && make run
 * 2. Frontend running: cd frontend && npm run dev
 *
 * Run with: BASE_URL=http://localhost:5173 npm run screenshots
 *
 * Or if using production build served by backend:
 * Run with: npm run screenshots
 *
 * Screenshots are saved to ../screenshots/ directory.
 * Add new screens as the interface grows.
 */
import { test } from '@playwright/test';
import { ensureProfile, navigateToTab } from './helpers';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

// Screenshot output directory (relative to frontend/)
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const SCREENSHOT_DIR = path.join(__dirname, '..', '..', 'screenshots');

// Viewport size for consistent screenshots
const VIEWPORT = { width: 1440, height: 900 };

// Ensure screenshot directory exists
test.beforeAll(async () => {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
});

/**
 * Helper to select a library browser view.
 * Opens the browser picker dropdown and selects the specified browser.
 */
async function selectBrowser(page: import('@playwright/test').Page, browserName: string) {
  // The browser picker button shows the current view name with a chevron
  // It's located in the library tab content area
  const pickerButton = page.locator('button:has(svg.lucide-chevron-down)').first();

  // Try to click the picker button
  if (await pickerButton.isVisible({ timeout: 3000 }).catch(() => false)) {
    await pickerButton.click();
    await page.waitForTimeout(300);

    // Find and click the browser option in the dropdown
    const browserOption = page.locator(`button:has-text("${browserName}")`).first();
    if (await browserOption.isVisible({ timeout: 2000 }).catch(() => false)) {
      await browserOption.click();
      await page.waitForTimeout(300);
    }
  }
}

test.describe('Screenshot Capture', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/');
    await ensureProfile(page);
  });

  test('01 - Library Track List', async ({ page }) => {
    // Default view is the track list
    await navigateToTab(page, 'Library');
    await page.waitForTimeout(1000); // Wait for data to load

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '01-library-tracks.png'),
      fullPage: false,
    });
  });

  test('02 - Library Mood Grid', async ({ page }) => {
    await navigateToTab(page, 'Library');
    await selectBrowser(page, 'Mood Grid');
    await page.waitForTimeout(1000);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '02-library-mood-grid.png'),
      fullPage: false,
    });
  });

  test('03 - Library Music Map', async ({ page }) => {
    await navigateToTab(page, 'Library');
    await selectBrowser(page, 'Music Map');
    await page.waitForTimeout(2000); // Music Map takes longer to compute

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '03-library-music-map.png'),
      fullPage: false,
    });
  });

  test('04 - Library Timeline', async ({ page }) => {
    await navigateToTab(page, 'Library');
    await selectBrowser(page, 'Timeline');
    await page.waitForTimeout(1000);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '04-library-timeline.png'),
      fullPage: false,
    });
  });

  test('05 - Playlists View', async ({ page }) => {
    await navigateToTab(page, 'Playlists');
    await page.waitForTimeout(1000);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '05-playlists.png'),
      fullPage: false,
    });
  });

  test('06 - Visualizer', async ({ page }) => {
    await navigateToTab(page, 'Visualizer');
    await page.waitForTimeout(1000);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '06-visualizer.png'),
      fullPage: false,
    });
  });

  test('07 - Settings', async ({ page }) => {
    await navigateToTab(page, 'Settings');
    await page.waitForTimeout(500);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '07-settings.png'),
      fullPage: false,
    });
  });

  test('08 - Chat Panel with AI', async ({ page }) => {
    // Chat panel is always visible on desktop
    // Focus on the chat input to show the interface
    const chatInput = page.locator('textarea[placeholder*="message"], input[placeholder*="message"]').first();
    if (await chatInput.isVisible()) {
      await chatInput.focus();
    }
    await page.waitForTimeout(500);

    // Take a screenshot of just the left panel (chat area)
    // We'll capture the full page and crop in post if needed
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '08-chat-panel.png'),
      fullPage: false,
    });
  });

  test('09 - Full Player', async ({ page }) => {
    // First, we need to play a track to see the full player
    await navigateToTab(page, 'Library');
    await page.waitForTimeout(500);

    // Try to double-click a track to play it
    const trackRow = page.locator('tr[data-track-id], [role="row"]').first();
    if (await trackRow.isVisible()) {
      await trackRow.dblclick();
      await page.waitForTimeout(1000);
    }

    // Click the expand button in the player bar to open full player
    const expandButton = page.locator('button[aria-label*="expand"], button:has(svg.lucide-maximize2)').first();
    if (await expandButton.isVisible()) {
      await expandButton.click();
      await page.waitForTimeout(500);
    }

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '09-full-player.png'),
      fullPage: false,
    });

    // Close full player
    const closeButton = page.locator('button[aria-label*="close"], button:has(svg.lucide-x)').first();
    if (await closeButton.isVisible()) {
      await closeButton.click();
    }
  });

  test('10 - Keyboard Shortcuts', async ({ page }) => {
    await navigateToTab(page, 'Library');
    await page.waitForTimeout(500);

    // Press ? to open shortcuts help modal
    await page.keyboard.press('Shift+?');
    await page.waitForTimeout(500);

    // Wait for the shortcuts modal to appear
    const shortcutsModal = page.locator('text=Keyboard Shortcuts').first();
    if (await shortcutsModal.isVisible({ timeout: 2000 }).catch(() => false)) {
      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, '10-keyboard-shortcuts.png'),
        fullPage: false,
      });
    }

    // Close the modal
    await page.keyboard.press('Escape');
  });

});

// Profile selector screenshot (separate test to avoid profile auto-selection)
test.describe('Profile Selector', () => {
  test('00 - Profile Selector', async ({ page, request }) => {
    await page.setViewportSize(VIEWPORT);

    // Clean up test profiles first - delete any that look like test data
    try {
      const profilesRes = await request.get('/api/v1/profiles');
      if (profilesRes.ok()) {
        const profiles = await profilesRes.json();
        for (const profile of profiles) {
          const name = profile.name;
          // Delete test profiles: "Test*", "User 1", "User 2", "Profile xxxx"
          if (
            name.includes('Test') ||
            name.includes('test') ||
            /^User \d+$/.test(name) ||
            /^Profile [a-f0-9]+$/.test(name)
          ) {
            await request.delete(`/api/v1/profiles/${profile.id}`);
          }
        }
      }
    } catch {
      // Ignore errors - profiles might not exist
    }

    // Navigate and clear local storage
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Clear profile to show selector
    await page.evaluate(() => {
      localStorage.removeItem('familiar-profile-id');
    });

    // Reload to show profile selector
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Wait for profile selector to appear
    const profileHeading = page.getByRole('heading', { name: "Who's listening?" });
    if (await profileHeading.isVisible({ timeout: 3000 }).catch(() => false)) {
      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, '00-profile-selector.png'),
        fullPage: false,
      });
    }
  });
});

// Admin page screenshot
test.describe('Admin Setup', () => {
  test('11 - Admin Setup Page', async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/admin');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '11-admin-setup.png'),
      fullPage: false,
    });
  });
});

// Mobile screenshots for README
test.describe('Mobile Screenshots', () => {
  const MOBILE_VIEWPORT = { width: 390, height: 844 }; // iPhone 14

  test('12 - Mobile Library', async ({ page }) => {
    await page.setViewportSize(MOBILE_VIEWPORT);
    await page.goto('/');
    await ensureProfile(page);
    await navigateToTab(page, 'Library');
    await page.waitForTimeout(1000);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '12-mobile-library.png'),
      fullPage: false,
    });
  });

  test('13 - Mobile Settings', async ({ page }) => {
    await page.setViewportSize(MOBILE_VIEWPORT);
    await page.goto('/');
    await ensureProfile(page);
    await navigateToTab(page, 'Settings');
    await page.waitForTimeout(500);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '13-mobile-settings.png'),
      fullPage: false,
    });
  });

  test('14 - Mobile Full Player', async ({ page }) => {
    await page.setViewportSize(MOBILE_VIEWPORT);
    await page.goto('/');
    await ensureProfile(page);
    await navigateToTab(page, 'Library');
    await page.waitForTimeout(500);

    // Play a track
    const trackRow = page.locator('tr[data-track-id], [role="row"]').first();
    if (await trackRow.isVisible()) {
      await trackRow.dblclick();
      await page.waitForTimeout(1000);
    }

    // Expand to full player
    const expandButton = page.locator('button:has(svg.lucide-maximize2)').first();
    if (await expandButton.isVisible()) {
      await expandButton.click();
      await page.waitForTimeout(500);
    }

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '14-mobile-full-player.png'),
      fullPage: false,
    });
  });
});
