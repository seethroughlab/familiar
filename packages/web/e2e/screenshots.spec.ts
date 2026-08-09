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
import { ensureProfile, navigateToView, waitForContentReady } from './helpers';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

// Screenshot output directory (relative to frontend/)
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const SCREENSHOT_DIR = path.join(__dirname, '..', '..', '..', 'screenshots');

// Viewport size for consistent screenshots
const VIEWPORT = { width: 1440, height: 900 };

// Ensure screenshot directory exists
test.beforeAll(async () => {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
});

/**
 * Helper to dismiss the PWA install prompt if it appears.
 */
async function dismissPwaPrompt(page: import('@playwright/test').Page) {
  const gotItButton = page.locator('button:has-text("Got it")').first();
  if (await gotItButton.isVisible({ timeout: 1000 }).catch(() => false)) {
    await gotItButton.click();
  }
}

/**
 * Dismiss PWA prompt (if visible) then take a screenshot.
 */
async function takeScreenshot(page: import('@playwright/test').Page, name: string) {
  await dismissPwaPrompt(page);
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, name),
    fullPage: false,
  });
}

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

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Clear profile to show selector
    await page.evaluate(() => {
      localStorage.removeItem('familiar-profile-id');
    });

    await page.reload();
    await page.waitForLoadState('networkidle');

    const profileHeading = page.getByRole('heading', { name: "Who's listening?" });
    if (await profileHeading.isVisible({ timeout: 3000 }).catch(() => false)) {
      await takeScreenshot(page, '00-profile-selector.png');
    }
  });
});

test.describe('Screenshot Capture', () => {
  // Allow extra time for NAS network latency
  test.setTimeout(60000);

  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await ensureProfile(page);
    await dismissPwaPrompt(page);
  });

  test('01 - Library Tracks', async ({ page }) => {
    await navigateToView(page, 'Tracks');
    // Wait for tracks to load, or detect React crash and reload
    await page.locator('[data-testid="track-row"], img').first().waitFor({ timeout: 10000 }).catch(() => {});
    const rootContent = await page.evaluate(() => document.getElementById('root')?.innerHTML?.length ?? 0);
    if (rootContent === 0) {
      // Tracks view crashed — fall back to Artists as library screenshot
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await ensureProfile(page);
      await navigateToView(page, 'Artists');
      await waitForContentReady(page, { images: true });
    }

    await takeScreenshot(page, '01-library-tracks.png');
  });

  test('02 - Library Artists', async ({ page }) => {
    await navigateToView(page, 'Artists');
    // Wait for artist images to load
    await waitForContentReady(page, { images: true });

    await takeScreenshot(page, '02-library-artists.png');
  });

  test('03 - Library Albums', async ({ page }) => {
    await navigateToView(page, 'Albums');
    await waitForContentReady(page, { images: true });

    await takeScreenshot(page, '03-library-albums.png');
  });

  test('04 - Library Mood Grid', async ({ page }) => {
    await navigateToView(page, 'Mood Grid');
    await waitForContentReady(page, { canvas: true });

    await takeScreenshot(page, '04-library-mood-grid.png');
  });


  test('07 - Library Discover', async ({ page }) => {
    await navigateToView(page, 'Discover');
    // Discover loads multiple sections with images — just wait for any content to appear
    await page.locator('img').first().waitFor({ timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(3000); // let more sections load

    await takeScreenshot(page, '07-library-discover.png');
  });

  test('09 - Playlist Detail', async ({ page }) => {
    // Wait for sidebar playlists to load, then click the first one
    const playlistLink = page.locator('a[href^="/playlists/"]').first();
    await playlistLink.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});
    if (await playlistLink.isVisible().catch(() => false)) {
      await playlistLink.click();
      await page.waitForLoadState('domcontentloaded');
      // Wait for playlist tracks to load
      await page.locator('[data-testid="track-row"]').first().waitFor({ timeout: 10000 }).catch(() => {});
    }

    await takeScreenshot(page, '09-playlist-detail.png');
  });

  test('10 - Artist Detail', async ({ page }) => {
    // Navigate to Artists, get the first artist name, then navigate to detail
    await navigateToView(page, 'Artists');
    await waitForContentReady(page, { images: true });

    // Get the first artist name from the page and navigate to their detail
    const artistName = await page.locator('button[data-list-index]').first().locator('.font-medium, .truncate').first().textContent();
    if (artistName) {
      await page.goto(`/library/artists/${encodeURIComponent(artistName.trim())}`, { waitUntil: 'domcontentloaded' });
      await page.locator('button:has-text("Play")').first().waitFor({ timeout: 15000 }).catch(() => {});
      await waitForContentReady(page, { images: true });
    }

    await takeScreenshot(page, '10-full-player.png');
  });

  test('11 - Keyboard Shortcuts', async ({ page }) => {
    await navigateToView(page, 'Artists');

    await page.keyboard.press('Shift+?');

    await page.locator('text=Keyboard Shortcuts').first().waitFor({ timeout: 5000 });
    await takeScreenshot(page, '11-keyboard-shortcuts.png');

    await page.keyboard.press('Escape');
  });

  test('12 - Settings', async ({ page }) => {
    await page.evaluate(() => {
      window.dispatchEvent(new Event('navigate-to-settings'));
    });
    await page.waitForSelector('h2:has-text("Settings")', { timeout: 10000 });
    // Wait for settings content to load (SystemStatus, ApiKeyStatus, etc.)
    await page.locator('.animate-spin').last().waitFor({ state: 'hidden', timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(1000);

    await takeScreenshot(page, '12-settings.png');
  });
});

// Admin/System setup screenshot — shows Settings > System section (API keys + status)
test.describe('Admin Setup', () => {
  test('13 - Admin Setup Page', async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/');
    await ensureProfile(page);

    // Open Settings
    await page.evaluate(() => {
      window.dispatchEvent(new Event('navigate-to-settings'));
    });
    await page.waitForSelector('h2:has-text("Settings")', { timeout: 10000 });
    // Wait for settings content to load
    await page.locator('.animate-spin').last().waitFor({ state: 'hidden', timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(1000);

    // Scroll the settings panel to show the System section (API keys)
    const settingsPanel = page.locator('h3:has-text("System")').first();
    if (await settingsPanel.isVisible({ timeout: 3000 }).catch(() => false)) {
      await settingsPanel.scrollIntoViewIfNeeded();
    }

    await takeScreenshot(page, '13-admin-setup.png');
  });
});

// Mobile screenshots
test.describe('Mobile Screenshots', () => {
  const MOBILE_VIEWPORT = { width: 390, height: 844 }; // iPhone 14

  test('14 - Mobile Library', async ({ page }) => {
    await page.setViewportSize(MOBILE_VIEWPORT);
    await page.goto('/');
    await ensureProfile(page);
    // On mobile, sidebar links are hidden — navigate via URL
    await page.goto('/library/artists');
    await waitForContentReady(page, { images: true });

    await takeScreenshot(page, '14-mobile-library.png');
  });

  test('15 - Mobile Full Player', async ({ page }) => {
    await page.setViewportSize(MOBILE_VIEWPORT);
    await page.goto('/');
    await ensureProfile(page);
    // Navigate to artists, click into one to find playable tracks
    await page.goto('/library/artists');
    await waitForContentReady(page, { images: true });

    // Click the first artist card to show artist detail
    const artistCard = page.locator('button[data-list-index]').first();
    if (await artistCard.isVisible({ timeout: 5000 }).catch(() => false)) {
      await artistCard.click();
      await page.waitForURL(/\/library\/artists\//, { timeout: 10000 }).catch(() => {});
      await page.locator('button:has-text("Play")').first().waitFor({ timeout: 10000 }).catch(() => {});
      await waitForContentReady(page, { images: true });
    }

    await takeScreenshot(page, '15-mobile-full-player.png');
  });
});

// Heavy visualization tests run last — large library queries can overwhelm the backend
test.describe('Heavy Visualizations', () => {
  test('05 - Library Music Map', async ({ page }) => {
    test.setTimeout(90000);
    await page.setViewportSize(VIEWPORT);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await ensureProfile(page);
    await navigateToView(page, 'Music Map');

    // Wait for artist picker to load its list, then click the first artist button
    const pickerList = page.locator('ul.divide-y button').first();
    await pickerList.waitFor({ state: 'visible', timeout: 10000 });
    await pickerList.click();

    // Wait for "Loading music map..." spinner to appear then disappear
    const loadingText = page.locator('text=Loading music map');
    await loadingText.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
    await loadingText.waitFor({ state: 'hidden', timeout: 30000 }).catch(() => {});
    // Let the SVG map render
    await page.waitForTimeout(2000);

    // Zoom in so artist names are readable
    const zoomInButton = page.locator('button[title="Zoom in"]').first();
    for (let i = 0; i < 6; i++) {
      if (await zoomInButton.isVisible({ timeout: 1000 }).catch(() => false)) {
        await zoomInButton.click();
        await page.waitForTimeout(150);
      }
    }
    await page.waitForLoadState('domcontentloaded');

    await takeScreenshot(page, '05-library-music-map.png');
  });

  test('06 - Library 3D Explorer', async ({ page }) => {
    test.setTimeout(180000);
    await page.setViewportSize(VIEWPORT);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await ensureProfile(page);
    await navigateToView(page, '3D Explorer');
    // Wait for SSE streaming to finish — the loading overlay shows percentage text
    const loadingText = page.locator('text=Loading embeddings').or(page.locator('text=Connecting'));
    await loadingText.first().waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});
    await loadingText.first().waitFor({ state: 'hidden', timeout: 120000 }).catch(() => {});
    await waitForContentReady(page, { canvas: true, timeout: 15000 });
    await page.waitForTimeout(3000); // let 3D rendering settle

    await takeScreenshot(page, '06-library-explorer.png');
  });
});
