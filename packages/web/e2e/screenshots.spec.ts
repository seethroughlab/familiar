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
import { ensureProfile, navigateToView, openChatPanel } from './helpers';
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
 * Helper to dismiss the PWA install prompt if it appears.
 */
async function dismissPwaPrompt(page: import('@playwright/test').Page) {
  const gotItButton = page.locator('button:has-text("Got it")').first();
  if (await gotItButton.isVisible({ timeout: 1000 }).catch(() => false)) {
    await gotItButton.click();
    await page.waitForTimeout(300);
  }
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
      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, '00-profile-selector.png'),
        fullPage: false,
      });
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
    await page.waitForTimeout(1500);
    const rootContent = await page.evaluate(() => document.getElementById('root')?.innerHTML?.length ?? 0);
    if (rootContent === 0) {
      // Tracks view crashed — fall back to Artists as library screenshot
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await ensureProfile(page);
      await navigateToView(page, 'Artists');
      await page.locator('img').first().waitFor({ timeout: 10000 }).catch(() => {});
      await page.waitForTimeout(2000);
    }

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '01-library-tracks.png'),
      fullPage: false,
    });
  });

  test('02 - Library Artists', async ({ page }) => {
    await navigateToView(page, 'Artists');
    // Wait for artist images to load
    await page.locator('img').first().waitFor({ timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(2000);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '02-library-artists.png'),
      fullPage: false,
    });
  });

  test('03 - Library Albums', async ({ page }) => {
    await navigateToView(page, 'Albums');
    await page.waitForTimeout(2000); // Wait for album artwork to load

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '03-library-albums.png'),
      fullPage: false,
    });
  });

  test('04 - Library Mood Grid', async ({ page }) => {
    await navigateToView(page, 'Mood Grid');
    await page.waitForSelector('[class*="grid"]', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(3000);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '04-library-mood-grid.png'),
      fullPage: false,
    });
  });

  // Chat panel test - use Albums view as backdrop (Tracks can crash on some data)
  test('08 - Chat Panel', async ({ page }) => {
    await navigateToView(page, 'Albums');
    await page.waitForTimeout(2000);
    await dismissPwaPrompt(page);

    await openChatPanel(page);

    // Type a sample message to show the chat interface
    const chatInput = page.locator('[aria-label="Chat message"]').first();
    await chatInput.fill('Make me a playlist of upbeat 80s songs');
    await page.waitForTimeout(500);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '08-chat-panel.png'),
      fullPage: false,
    });
  });

  test('05 - Library Music Map', async ({ page }) => {
    await navigateToView(page, 'Music Map');
    await page.waitForTimeout(1000);

    // The artist picker modal should appear - click a good artist
    const artistOption = page.locator('button:has-text("Aphex Twin"), button:has-text("Beatles"), button:has-text("Boards Of Canada")').first();
    if (await artistOption.isVisible({ timeout: 5000 }).catch(() => false)) {
      await artistOption.click();
      await page.waitForTimeout(500);
    }

    // Wait for the map canvas to render
    await page.waitForSelector('canvas', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(3000);

    await dismissPwaPrompt(page);

    // Zoom in so artist names are readable
    const zoomInButton = page.locator('button[title="Zoom in"]').first();
    for (let i = 0; i < 6; i++) {
      if (await zoomInButton.isVisible({ timeout: 1000 }).catch(() => false)) {
        await zoomInButton.click();
        await page.waitForTimeout(150);
      }
    }
    await page.waitForTimeout(500);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '05-library-music-map.png'),
      fullPage: false,
    });
  });

  test('06 - Library 3D Explorer', async ({ page }) => {
    await navigateToView(page, '3D Explorer');
    // Wait for the 3D canvas to render
    await page.waitForSelector('canvas', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(3000);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '06-library-explorer.png'),
      fullPage: false,
    });
  });

  test('07 - Library Discover', async ({ page }) => {
    await navigateToView(page, 'Discover');
    await page.waitForTimeout(2000);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '07-library-discover.png'),
      fullPage: false,
    });
  });

  test('09 - Playlist Detail', async ({ page }) => {
    await page.waitForTimeout(1000);
    await dismissPwaPrompt(page);

    // Click the first playlist link in the sidebar
    const playlistLink = page.locator('a[href^="/playlists/"]').first();
    if (await playlistLink.isVisible({ timeout: 5000 }).catch(() => false)) {
      await playlistLink.click();
      await page.waitForTimeout(1500);
    }

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '09-playlist-detail.png'),
      fullPage: false,
    });
  });

  test('10 - Full Player', async ({ page }) => {
    // Navigate to Artists and click into one to find playable tracks
    await navigateToView(page, 'Artists');
    await page.locator('img').first().waitFor({ timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(1000);

    // Click the first artist card to open artist detail
    const artistCard = page.locator('a[href^="/artists/"]').first();
    if (await artistCard.isVisible({ timeout: 3000 }).catch(() => false)) {
      await artistCard.click();
      await page.waitForTimeout(2000);
    }

    // Start playback — try Play button first, then double-click a track row
    const playAllButton = page.locator('button:has-text("Play")').first();
    if (await playAllButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await playAllButton.click();
      await page.waitForTimeout(2000);
    } else {
      const trackRow = page.locator('[data-testid="track-row"]').first();
      if (await trackRow.isVisible({ timeout: 3000 }).catch(() => false)) {
        await trackRow.dblclick();
        await page.waitForTimeout(2000);
      }
    }

    // Expand to full player
    const expandButton = page.locator('button[aria-label="Expand player"]').first();
    if (await expandButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expandButton.click();
      await page.waitForTimeout(2000);
    }

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '10-full-player.png'),
      fullPage: false,
    });
  });

  test('11 - Keyboard Shortcuts', async ({ page }) => {
    await navigateToView(page, 'Artists');
    await page.waitForTimeout(1000);

    await page.keyboard.press('Shift+?');
    await page.waitForTimeout(500);

    await page.locator('text=Keyboard Shortcuts').first().waitFor({ timeout: 5000 });
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '11-keyboard-shortcuts.png'),
      fullPage: false,
    });

    await page.keyboard.press('Escape');
  });

  test('12 - Settings', async ({ page }) => {
    await page.evaluate(() => {
      window.dispatchEvent(new Event('navigate-to-settings'));
    });
    await page.waitForSelector('h2:has-text("Settings")', { timeout: 10000 });
    await page.waitForTimeout(500);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '12-settings.png'),
      fullPage: false,
    });
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
    await page.waitForTimeout(1000);

    // Scroll the settings panel to show the System section (API keys)
    const settingsPanel = page.locator('h3:has-text("System")').first();
    if (await settingsPanel.isVisible({ timeout: 3000 }).catch(() => false)) {
      await settingsPanel.scrollIntoViewIfNeeded();
      await page.waitForTimeout(500);
    }

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '13-admin-setup.png'),
      fullPage: false,
    });
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
    await page.locator('img').first().waitFor({ timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(1500);

    // Dismiss PWA prompt if it appears
    const gotItButton = page.locator('button:has-text("Got it")').first();
    if (await gotItButton.isVisible({ timeout: 1000 }).catch(() => false)) {
      await gotItButton.click();
      await page.waitForTimeout(300);
    }

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '14-mobile-library.png'),
      fullPage: false,
    });
  });

  test('15 - Mobile Full Player', async ({ page }) => {
    await page.setViewportSize(MOBILE_VIEWPORT);
    await page.goto('/');
    await ensureProfile(page);
    // Navigate to artists, click into one to find playable tracks
    await page.goto('/library/artists');
    await page.locator('img').first().waitFor({ timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(1000);

    // Click the first artist card
    const artistCard = page.locator('a[href^="/artists/"]').first();
    if (await artistCard.isVisible({ timeout: 3000 }).catch(() => false)) {
      await artistCard.click();
      await page.waitForTimeout(2000);
    }

    // Play a track
    const playButton = page.locator('button:has-text("Play")').first();
    if (await playButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await playButton.click();
      await page.waitForTimeout(1500);
    } else {
      const trackRow = page.locator('[data-testid="track-row"]').first();
      if (await trackRow.isVisible({ timeout: 3000 }).catch(() => false)) {
        await trackRow.dblclick();
        await page.waitForTimeout(1500);
      }
    }

    // Expand to full player (force click even if disabled — button disables when no track loaded)
    const expandButton = page.locator('button[aria-label="Expand player"]').first();
    if (await expandButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await expandButton.click({ force: true }).catch(() => {});
      await page.waitForTimeout(1500);
    }

    await page.waitForTimeout(1000);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '15-mobile-full-player.png'),
      fullPage: false,
    });
  });
});
