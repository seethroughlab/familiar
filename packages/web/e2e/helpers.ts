import { Page } from '@playwright/test';

/**
 * Helper to create or select a profile before tests
 */
export async function ensureProfile(page: Page, profileName = 'Test User') {
  // Wait for page to settle (use domcontentloaded instead of networkidle to avoid timeout)
  await page.waitForLoadState('domcontentloaded');

  // Wait for the app to reach a meaningful state: either the profile selector appears
  // (meaning we need to pick/create a profile) or the nav links are already visible
  // (meaning a profile is already selected). In CI, React hydration + API calls can
  // take 10-15s, so we use a generous timeout here instead of a short isVisible check.
  const navOrProfile = await page.waitForFunction(() => {
    // Check for profile selector heading
    const headings = document.querySelectorAll('h1, h2, h3');
    const hasProfileSelector = Array.from(headings).some(
      el => el.textContent?.includes("Who's listening?") && el.offsetParent !== null
    );
    if (hasProfileSelector) return 'profile-selector';

    // Check for visible nav links (app already loaded with profile)
    const links = document.querySelectorAll('a');
    const buttons = document.querySelectorAll('nav button');
    const hasVisibleLink = Array.from(links).some(
      el => (el.textContent?.includes('Tracks') || el.textContent?.includes('Artists'))
        && el.offsetParent !== null
    );
    const hasVisibleButton = Array.from(buttons).some(
      el => el.textContent?.includes('Tracks') && el.offsetParent !== null
    );
    if (hasVisibleLink || hasVisibleButton) return 'nav-ready';

    return null;
  }, undefined, { timeout: 30000 });

  const state = await navOrProfile.jsonValue();

  if (state === 'profile-selector') {
    // Find profile buttons - they have name pattern "T Test User" (letter + name)
    const profileButtons = page.getByRole('button', { name: /^[A-Z] .+/ });
    const buttonCount = await profileButtons.count();

    if (buttonCount > 0) {
      await profileButtons.first().click();
    } else {
      // No profiles exist - create one
      await page.getByRole('button', { name: /Add Profile/ }).click();
      const nameInput = page.getByPlaceholder('Enter name');
      await nameInput.waitFor({ timeout: 5000 });
      await nameInput.fill(profileName);
      await page.getByRole('button', { name: 'Create' }).click();
    }

    // Now wait for nav links after profile selection
    await page.waitForFunction(() => {
      const links = document.querySelectorAll('a');
      const buttons = document.querySelectorAll('nav button');
      const hasVisibleLink = Array.from(links).some(
        el => (el.textContent?.includes('Tracks') || el.textContent?.includes('Artists'))
          && el.offsetParent !== null
      );
      const hasVisibleButton = Array.from(buttons).some(
        el => el.textContent?.includes('Tracks') && el.offsetParent !== null
      );
      return hasVisibleLink || hasVisibleButton;
    }, undefined, { timeout: 15000 });
  }
  // If state === 'nav-ready', we're already good
}

/**
 * Navigate to a specific view by clicking its sidebar link.
 * Labels: 'Tracks', 'Artists', 'Albums', 'Mood Grid', 'Music Map', '3D Explorer', 'Discover', 'Changes'
 */
export async function navigateToView(page: Page, label: string) {
  // Desktop: sidebar link is visible
  const link = page.getByRole('link', { name: label, exact: true });
  if (await link.isVisible({ timeout: 2000 }).catch(() => false)) {
    await link.click();
    await page.waitForLoadState('domcontentloaded');
    return;
  }

  // Mobile: try bottom nav button directly (Tracks, Artists, Favorites, Chat)
  const mobileButton = page.locator(`nav button:has-text("${label}")`);
  if (await mobileButton.isVisible({ timeout: 1000 }).catch(() => false)) {
    await mobileButton.click();
    await page.waitForLoadState('domcontentloaded');
    return;
  }

  // Mobile: open "More" sheet and find the link there
  const moreButton = page.locator('nav button:has-text("More")');
  if (await moreButton.isVisible({ timeout: 1000 }).catch(() => false)) {
    await moreButton.click();
    const sheetLink = page.getByRole('link', { name: label, exact: true });
    await sheetLink.waitFor({ timeout: 3000 });
    await sheetLink.click();
    await page.waitForLoadState('domcontentloaded');
    return;
  }

  // Fallback: try clicking the link anyway (will fail with a clear error)
  await link.click();
  await page.waitForLoadState('domcontentloaded');
}

/**
 * Open the chat panel via the player bar toggle button, then wait for the chat input.
 * Falls back to clicking the mobile "Chat" button if the desktop button isn't visible.
 */
export async function openChatPanel(page: Page) {
  const desktopButton = page.locator('button[aria-label="Open chat"]');
  const mobileButton = page.locator('nav button:has-text("Chat")');

  if (await desktopButton.isVisible({ timeout: 3000 }).catch(() => false)) {
    await desktopButton.click();
  } else if (await mobileButton.isVisible({ timeout: 2000 }).catch(() => false)) {
    await mobileButton.click();
  }

  await page.locator('[aria-label="Chat message"]').first().waitFor({ timeout: 5000 });
}

/**
 * Navigate to a specific section in the sidebar-based UI
 */
export async function navigateToTab(page: Page, tabName: 'Library' | 'Playlists' | 'Queue' | 'Settings') {
  switch (tabName) {
    case 'Library': {
      await navigateToView(page, 'Tracks');
      break;
    }
    case 'Settings': {
      // Open Settings modal via custom event (same mechanism used by the app internally)
      // Direct button click is unreliable in CI due to player bar overlay
      await page.evaluate(() => {
        window.dispatchEvent(new Event('navigate-to-settings'));
      });
      // Wait for the lazy-loaded Settings modal to render
      await page.waitForSelector('h2:has-text("Settings")', { timeout: 10000 });
      break;
    }
    case 'Playlists':
    case 'Queue':
      // These are visible in the sidebar by default, no navigation needed
      break;
  }
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

/**
 * Wait for library sync to complete
 */
export async function waitForSyncComplete(page: Page, timeout = 120000) {
  const startTime = Date.now();

  while (Date.now() - startTime < timeout) {
    // Check sync status via page context
    const status = await page.evaluate(async () => {
      const response = await fetch('/api/v1/library/sync/status');
      if (response.ok) {
        return response.json();
      }
      return null;
    });

    if (status && (status.status === 'idle' || status.status === 'completed' || status.status === 'complete')) {
      return status;
    }

    if (status && status.status === 'error') {
      throw new Error(`Sync failed: ${status.message}`);
    }

    await page.waitForTimeout(1000);
  }

  throw new Error('Sync timed out');
}

/**
 * Trigger library sync and wait for completion
 */
export async function syncLibraryAndWait(page: Page, timeout = 120000) {
  // Trigger sync
  const startResult = await page.evaluate(async () => {
    const response = await fetch('/api/v1/library/sync', { method: 'POST' });
    if (response.ok) {
      return response.json();
    }
    return null;
  });

  if (!startResult) {
    throw new Error('Failed to start sync');
  }

  if (startResult.status === 'already_running') {
    // Wait for existing sync to complete
    return waitForSyncComplete(page, timeout);
  }

  // Wait for sync to complete
  return waitForSyncComplete(page, timeout);
}

/**
 * Check if analysis is complete for tracks
 */
export async function waitForAnalysisComplete(page: Page, timeout = 180000) {
  const startTime = Date.now();

  while (Date.now() - startTime < timeout) {
    const stats = await page.evaluate(async () => {
      const response = await fetch('/api/v1/library/stats');
      if (response.ok) {
        return response.json();
      }
      return null;
    });

    if (stats) {
      const total = stats.total_tracks || 0;
      const analyzed = stats.analyzed_tracks || 0;
      const pending = stats.pending_analysis || 0;

      if (total === 0 || pending === 0 || analyzed >= total) {
        return { total, analyzed, pending };
      }
    }

    await page.waitForTimeout(2000);
  }

  throw new Error('Analysis timed out');
}

// ============================================================================
// Crossfade / Audio Playback Helpers
// ============================================================================

/**
 * Get the state of all <audio> elements in the page
 */
export async function getAllAudioStates(page: Page) {
  return page.evaluate(() => {
    const elements = Array.from(document.querySelectorAll('audio'));
    return elements.map((el, i) => ({
      index: i,
      src: el.src,
      paused: el.paused,
      currentTime: el.currentTime,
      duration: el.duration,
      volume: el.volume,
      readyState: el.readyState,
    }));
  });
}

/**
 * Check if at least one audio element is not paused
 */
export async function isAnyAudioPlaying(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const elements = Array.from(document.querySelectorAll('audio'));
    return elements.some(el => !el.paused);
  });
}

/**
 * Seek the currently playing audio element to a specific time
 */
export async function seekAudio(page: Page, time: number) {
  await page.evaluate((t) => {
    const elements = Array.from(document.querySelectorAll('audio'));
    const playing = elements.find(el => !el.paused);
    if (playing) {
      playing.currentTime = t;
    }
  }, time);
}

/**
 * Wait for the displayed track title to change from the current one
 */
export async function waitForTrackChange(page: Page, currentTitle: string, timeout = 15000) {
  const startTime = Date.now();
  while (Date.now() - startTime < timeout) {
    const title = await page.evaluate(() => {
      // Look for track title in the player bar or full player
      const el = document.querySelector('[data-testid="track-title"]') ||
                 document.querySelector('.track-title');
      return el?.textContent || '';
    });
    if (title && title !== currentTitle) {
      return title;
    }
    await page.waitForTimeout(100);
  }
  throw new Error(`Track title didn't change from "${currentTitle}" within ${timeout}ms`);
}

/**
 * Detect if there's a gap in audio playback (all elements paused)
 * during a given monitoring window.
 * Returns true if a gap was detected.
 */
/**
 * Wait for visual content (images/canvas) to be ready for screenshots.
 */
export async function waitForContentReady(page: Page, opts?: {
  images?: boolean; canvas?: boolean; timeout?: number
}) {
  const timeout = opts?.timeout ?? 10000;
  if (opts?.images) {
    await page.waitForFunction(() => {
      const images = Array.from(document.querySelectorAll('img'));
      return images.length > 0 && images.every(img => img.complete);
    }, { timeout }).catch(() => {});
  }
  if (opts?.canvas) {
    await page.waitForSelector('canvas', { timeout }).catch(() => {});
  }
}

export async function detectAudioGap(page: Page, durationMs: number): Promise<boolean> {
  return page.evaluate(async (ms) => {
    const pollInterval = 50;
    const end = Date.now() + ms;
    let gapDetected = false;

    while (Date.now() < end) {
      const elements = Array.from(document.querySelectorAll('audio'));
      const anyPlaying = elements.some(el => !el.paused && el.currentTime > 0);
      if (!anyPlaying && elements.length > 0) {
        gapDetected = true;
        break;
      }
      await new Promise(r => setTimeout(r, pollInterval));
    }

    return gapDetected;
  }, durationMs);
}
