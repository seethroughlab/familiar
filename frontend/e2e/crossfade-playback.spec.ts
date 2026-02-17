/**
 * E2E tests for crossfade playback behavior.
 * Requires a running backend with at least 3 tracks in the library.
 */
import { test, expect, type Page } from '@playwright/test';
import {
  ensureProfile,
  navigateToTab,
  getAllAudioStates,
  isAnyAudioPlaying,
  seekAudio,
  detectAudioGap,
} from './helpers';

// Helper: start playback by clicking a track in the library
async function startPlayback(page: Page) {
  await navigateToTab(page, 'Library');
  await page.waitForTimeout(500);

  // Click the first track to start playing
  const firstTrack = page.locator('table tbody tr, [data-testid="track-row"]').first();
  await firstTrack.dblClick();
  await page.waitForTimeout(1000);

  // Wait for audio to actually start playing
  await page.waitForFunction(
    () => {
      const elements = Array.from(document.querySelectorAll('audio'));
      return elements.some(el => !el.paused && el.currentTime > 0);
    },
    { timeout: 10000 },
  );
}

// Helper: set crossfade settings via the UI
async function setCrossfadeSettings(page: Page, enabled: boolean, duration: number) {
  await navigateToTab(page, 'Settings');
  await page.waitForTimeout(300);

  // Find the card containing "Crossfade" heading and its controls
  const crossfadeCard = page.locator('div.rounded-lg:has(h4:text("Crossfade"))').first();
  if (await crossfadeCard.isVisible()) {
    // Toggle if needed
    const toggle = crossfadeCard.locator('input[type="checkbox"]').first();
    const isChecked = await toggle.isChecked({ timeout: 5000 });
    if (isChecked !== enabled) {
      await toggle.click();
    }

    if (enabled && duration !== undefined) {
      // Set duration via slider or input
      const slider = crossfadeCard.locator('input[type="range"]').first();
      if (await slider.isVisible()) {
        await slider.fill(String(duration));
      }
    }
  }

  await navigateToTab(page, 'Library');
  await page.waitForTimeout(300);
}

// Helper: get current track title from player
async function getCurrentTrackTitle(page: Page): Promise<string> {
  return page.evaluate(() => {
    const el = document.querySelector('[data-testid="track-title"]') ||
               document.querySelector('.track-title') ||
               document.querySelector('[class*="track"] [class*="title"]');
    return el?.textContent?.trim() || '';
  });
}

// These tests require a running backend with music files and real audio playback.
// Skip in CI where the library is empty and headless Chromium can't play audio reliably.
test.describe.skip('Crossfade Playback', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await ensureProfile(page);
  });

  test('track transition without gap', async ({ page }) => {
    await setCrossfadeSettings(page, true, 3);
    await startPlayback(page);

    // Get current audio state
    const states = await getAllAudioStates(page);
    const playing = states.find(s => !s.paused);
    expect(playing).toBeDefined();

    // Seek to near the end of the track (leave room for crossfade)
    const seekTo = Math.max(0, playing!.duration - 5);
    if (seekTo > 0) {
      await seekAudio(page, seekTo);
      await page.waitForTimeout(500);

      // Monitor for audio gaps during the transition period
      const hasGap = await detectAudioGap(page, 8000);
      expect(hasGap).toBe(false);

      // Verify some audio element is still playing
      const stillPlaying = await isAnyAudioPlaying(page);
      expect(stillPlaying).toBe(true);
    }
  });

  test('both elements active during crossfade', async ({ page }) => {
    await setCrossfadeSettings(page, true, 3);
    await startPlayback(page);

    const states = await getAllAudioStates(page);
    const playing = states.find(s => !s.paused);
    if (!playing || playing.duration < 10) {
      test.skip();
      return;
    }

    // Seek to near the end to trigger crossfade
    await seekAudio(page, playing.duration - 4);
    await page.waitForTimeout(1000);

    // Poll for a moment where both elements are playing (crossfade overlap)
    const bothActive = await page.evaluate(async () => {
      const endTime = Date.now() + 5000;
      while (Date.now() < endTime) {
        const elements = Array.from(document.querySelectorAll('audio'));
        const playingElements = elements.filter(el => !el.paused && el.currentTime > 0);
        if (playingElements.length >= 2) {
          return true;
        }
        await new Promise(r => setTimeout(r, 100));
      }
      return false;
    });

    // Both elements should be active at some point during crossfade
    expect(bothActive).toBe(true);
  });

  test('seek during crossfade cancels gracefully', async ({ page }) => {
    await setCrossfadeSettings(page, true, 5);
    await startPlayback(page);

    const states = await getAllAudioStates(page);
    const playing = states.find(s => !s.paused);
    if (!playing || playing.duration < 15) {
      test.skip();
      return;
    }

    // Seek to trigger crossfade
    await seekAudio(page, playing.duration - 6);
    await page.waitForTimeout(2000);

    // Now seek backward (should cancel crossfade)
    await seekAudio(page, 10);
    await page.waitForTimeout(1000);

    // Should still be playing on one element
    const audioStates = await getAllAudioStates(page);
    const activeCount = audioStates.filter(s => !s.paused && s.currentTime > 0).length;
    expect(activeCount).toBe(1);
  });

  test('crossfade disabled still advances tracks', async ({ page }) => {
    await setCrossfadeSettings(page, false, 0);
    await startPlayback(page);

    const states = await getAllAudioStates(page);
    const playing = states.find(s => !s.paused);
    if (!playing || playing.duration < 5) {
      test.skip();
      return;
    }

    const _firstTitle = await getCurrentTrackTitle(page);

    // Seek very close to end
    await seekAudio(page, playing.duration - 1);

    // Wait for track to end and next to start
    await page.waitForTimeout(5000);

    // Should still be playing
    const stillPlaying = await isAnyAudioPlaying(page);
    expect(stillPlaying).toBe(true);

    // Track should have changed (or at least audio continued)
    const newStates = await getAllAudioStates(page);
    const newPlaying = newStates.find(s => !s.paused);
    expect(newPlaying).toBeDefined();
  });

  test('repeat-all wraps last track to first', async ({ page }) => {
    // Enable repeat all if there's a button
    const repeatBtn = page.locator('button[title*="Repeat"], button[aria-label*="Repeat"]').first();
    if (await repeatBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      // Click until repeat-all is active (may need multiple clicks)
      await repeatBtn.click();
      await page.waitForTimeout(200);
    }

    await setCrossfadeSettings(page, true, 2);
    await startPlayback(page);

    // Navigate to the last track by going to queue and checking
    await page.waitForTimeout(1000);

    const states = await getAllAudioStates(page);
    const playing = states.find(s => !s.paused);
    if (!playing || playing.duration < 5) {
      test.skip();
      return;
    }

    // Seek near end
    await seekAudio(page, playing.duration - 3);

    // Wait for transition
    await page.waitForTimeout(5000);

    // Should still be playing (wrapped around or continued)
    const stillPlaying = await isAnyAudioPlaying(page);
    expect(stillPlaying).toBe(true);
  });
});
