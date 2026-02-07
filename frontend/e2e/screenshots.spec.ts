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

/**
 * Helper to dismiss the PWA install prompt if it appears.
 */
async function dismissPwaPrompt(page: import('@playwright/test').Page) {
  const gotItButton = page.locator('button:has-text("Got it")').first();
  if (await gotItButton.isVisible({ timeout: 1000 }).catch(() => false)) {
    await gotItButton.click();
    await page.waitForTimeout(300);
  }
}

test.describe('Screenshot Capture', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/');
    await ensureProfile(page);
    // Dismiss PWA prompt if it appears
    await dismissPwaPrompt(page);
  });

  test('01 - Library Track List', async ({ page }) => {
    await navigateToTab(page, 'Library');
    // Select the Tracks view (not Albums which might be default)
    await selectBrowser(page, 'Tracks');
    await page.waitForTimeout(1500); // Wait for data to load

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '01-library-tracks.png'),
      fullPage: false,
    });
  });

  test('02 - Library Mood Grid', async ({ page }) => {
    await navigateToTab(page, 'Library');
    await selectBrowser(page, 'Mood Grid');
    // Mood Grid needs time to load the grid data from the API
    // Wait for the grid cells to appear (they have specific classes)
    await page.waitForSelector('[class*="grid"]', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(3000); // Extra time for rendering

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '02-library-mood-grid.png'),
      fullPage: false,
    });
  });

  test('03 - Library Music Map', async ({ page }) => {
    // Navigate to library first
    await navigateToTab(page, 'Library');
    await page.waitForTimeout(500);

    // Select Music Map browser
    await selectBrowser(page, 'Music Map');
    await page.waitForTimeout(1000);

    // The artist picker modal should appear - click a good artist
    const artistOption = page.locator('button:has-text("Aphex Twin"), button:has-text("Beatles"), button:has-text("Boards Of Canada")').first();
    if (await artistOption.isVisible({ timeout: 5000 }).catch(() => false)) {
      await artistOption.click();
      await page.waitForTimeout(500);
    }

    // Wait for the map canvas to render
    await page.waitForSelector('canvas', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(3000); // Map needs time to compute positions

    // Dismiss PWA prompt before zooming
    await dismissPwaPrompt(page);

    // Zoom in so artist names are readable
    // Click the zoom in button multiple times (more clicks = more zoom)
    const zoomInButton = page.locator('button[title="Zoom in"]').first();
    for (let i = 0; i < 6; i++) {
      if (await zoomInButton.isVisible({ timeout: 1000 }).catch(() => false)) {
        await zoomInButton.click();
        await page.waitForTimeout(150);
      }
    }
    await page.waitForTimeout(500); // Let the zoom animation settle

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '03-library-music-map.png'),
      fullPage: false,
    });
  });

  test('04 - Library Album Grid', async ({ page }) => {
    await navigateToTab(page, 'Library');
    await selectBrowser(page, 'Albums');
    await page.waitForTimeout(2000); // Wait for album artwork to load

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '04-library-albums.png'),
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

  test('06 - Full Player', async ({ page }) => {
    // First switch to Track List and play a track so the full player has something to show
    await navigateToTab(page, 'Library');
    await selectBrowser(page, 'Tracks');
    await page.waitForTimeout(1500);

    // Click the Play button in the toolbar to start playback
    const playAllButton = page.locator('button:has-text("Play")').first();
    if (await playAllButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await playAllButton.click();
      await page.waitForTimeout(2000); // Wait for playback to start
    } else {
      // Fallback: try double-clicking a track row
      const trackRow = page.locator('[data-testid="track-row"]').first();
      if (await trackRow.isVisible({ timeout: 3000 }).catch(() => false)) {
        await trackRow.dblclick();
        await page.waitForTimeout(2000);
      }
    }

    // Expand to full player via the ChevronUp button
    const expandButton = page.locator('button[aria-label="Expand player"]').first();
    if (await expandButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expandButton.click();
      await page.waitForTimeout(2000); // Give full player time to animate in
    }

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '06-full-player.png'),
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
    // The chat panel is visible on the left side of any view
    // Navigate to Library with Tracks view to show a good backdrop
    await navigateToTab(page, 'Library');
    await selectBrowser(page, 'Tracks');
    await page.waitForTimeout(1000);

    // Dismiss PWA prompt if it appears
    await dismissPwaPrompt(page);

    // Type a sample message to show the chat interface in action
    // The chat input is an input element, not textarea
    const chatInput = page.locator('input[placeholder*="Familiar"]').first();
    if (await chatInput.isVisible({ timeout: 5000 }).catch(() => false)) {
      await chatInput.fill('Make me a playlist of upbeat 80s songs');
      await page.waitForTimeout(500);
    }

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '08-chat-panel.png'),
      fullPage: false,
    });

    // Clear the input after screenshot
    if (await chatInput.isVisible({ timeout: 1000 }).catch(() => false)) {
      await chatInput.clear();
    }
  });

  test('09 - AI Playlist Detail', async ({ page }) => {
    // Navigate to Playlists and expand an AI playlist to show its tracks
    await navigateToTab(page, 'Playlists');
    await page.waitForTimeout(1000);

    // Dismiss PWA prompt if it appears
    await dismissPwaPrompt(page);

    // Click on an AI playlist to expand it and show its tracks
    const playlistButton = page.locator('button:has-text("Crystalline Reverie"), button:has-text("Digital Nostalgia"), button:has-text("Essential IDM")').first();
    if (await playlistButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await playlistButton.click();
      await page.waitForTimeout(1500); // Wait for tracks to load
    }

    // Dismiss PWA prompt again if it reappeared
    await dismissPwaPrompt(page);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '09-ai-playlist.png'),
      fullPage: false,
    });
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
    // Mobile defaults to Track List view, wait for it to load
    await page.waitForTimeout(1500);

    // Play a track - on mobile, track rows are visible directly
    const trackRow = page.locator('[data-testid="track-row"]').first();
    if (await trackRow.isVisible({ timeout: 5000 }).catch(() => false)) {
      await trackRow.dblclick();
      await page.waitForTimeout(1500);
    }

    // Expand to full player
    const expandButton = page.locator('button[aria-label="Expand player"]').first();
    if (await expandButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await expandButton.click();
      await page.waitForTimeout(1500);
    }

    // The mobile full player shows the visualizer by default, which is nice
    // Just wait for it to render
    await page.waitForTimeout(1000);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '14-mobile-full-player.png'),
      fullPage: false,
    });
  });
});
