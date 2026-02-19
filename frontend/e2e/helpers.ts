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

  // Wait for main app to load - sidebar nav link indicates we're in the app
  await page.waitForSelector('a:has-text("Tracks"), a:has-text("Artists")', { timeout: 10000 });
}

/**
 * Navigate to a specific section in the sidebar-based UI
 */
export async function navigateToTab(page: Page, tabName: 'Library' | 'Playlists' | 'Queue' | 'Settings') {
  switch (tabName) {
    case 'Library': {
      // Click "Tracks" link in sidebar to navigate to library view
      const tracksLink = page.locator('a:has-text("Tracks")').first();
      await tracksLink.click();
      break;
    }
    case 'Settings': {
      // Click Settings button in sidebar footer (force click to bypass player bar overlay)
      const settingsBtn = page.locator('button:has-text("Settings")').first();
      await settingsBtn.click({ force: true });
      break;
    }
    case 'Playlists':
    case 'Queue':
      // These are visible in the sidebar by default, no navigation needed
      break;
  }
  await page.waitForTimeout(300);
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
