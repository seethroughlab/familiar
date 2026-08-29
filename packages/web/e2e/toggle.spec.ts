import { test, expect } from '@playwright/test';
const URL = 'file:///Users/jeff/Developer/familiar/.claude/worktrees/adr-0094-impl/site/index.html';

test('with JS: one panel at a time, and the pills switch it', async ({ page }) => {
  await page.goto(URL);
  const panels = page.locator('.platform-panel');
  await expect(panels).toHaveCount(4);
  await expect(page.locator('.platform-panel:visible')).toHaveCount(1);
  await expect(page.locator('#p-macos')).toBeVisible();
  await page.getByRole('tab', { name: 'Synology' }).click();
  await expect(page.locator('#p-synology')).toBeVisible();
  await expect(page.locator('#p-macos')).toBeHidden();
  await expect(page.locator('.platform-panel:visible')).toHaveCount(1);
  // Synology's whole point: no terminal.
  await expect(page.locator('#p-synology pre')).toHaveCount(0);
  // Arrow keys move within the strip.
  await page.getByRole('tab', { name: 'Synology' }).press('ArrowRight');
  await expect(page.locator('#p-linux')).toBeVisible();
});

test('without JS: every panel is visible, under its own heading', async ({ browser }) => {
  const ctx = await browser.newContext({ javaScriptEnabled: false });
  const page = await ctx.newPage();
  await page.goto(URL);
  await expect(page.locator('.platform-panel:visible')).toHaveCount(4);
  for (const h of ['macOS', 'Windows', 'Synology', 'Linux & NAS']) {
    await expect(page.locator('.platform-heading', { hasText: h })).toBeVisible();
  }
  // No pill strip offered, since nothing could act on it.
  await expect(page.locator('.platform-tabs')).toBeHidden();
  await ctx.close();
});

test('the Windows caveat and the no-login paragraph are on the page', async ({ page }) => {
  await page.goto(URL);
  await page.getByRole('tab', { name: 'Windows' }).click();
  await expect(page.locator('#p-windows .platform-caveat')).toContainText('Untested');
  await expect(page.locator('#remote .note')).toContainText('Familiar has no login');
});
