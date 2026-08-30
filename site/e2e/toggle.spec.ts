import { test, expect } from '@playwright/test';

/**
 * The marketing site's platform chooser (ADR-0095).
 *
 * `site/` is static HTML with no build step and no dev server, so this loads the file directly.
 * It lives here rather than in `packages/web/e2e/` for one reason: that suite's `globalSetup` POSTs
 * `/api/v1/library/sync` and fails without a backend, and this test needs no server at all.
 * The `file://` base is resolved in `site/playwright.config.ts`, so this file works in any
 * checkout or worktree and needs no `import.meta.url` — which would make Playwright treat the spec
 * as ESM and fail against this repository's CommonJS default.
 *
 * **The case worth having a test for is the second one.** ADR-0095 point 6 says the section must
 * still say everything it needs to when the script does not run, because this project's recurring
 * defect is an affordance whose destination is not mounted — and a tab strip that hides three
 * panels and then fails to render one is exactly that defect with a new face. Nothing else checks
 * it: the page looks correct in a browser precisely because the script *did* run.
 */
const PLATFORMS = ['macOS', 'Windows', 'Synology', 'OpenMediaVault', 'Linux & NAS'];

test.describe('install platform chooser', () => {
  test('shows one platform at a time, and the pills switch it', async ({ page }) => {
    await page.goto('index.html');

    await expect(page.locator('.platform-panel')).toHaveCount(PLATFORMS.length);
    await expect(page.locator('.platform-panel:visible')).toHaveCount(1);
    await expect(page.locator('#p-macos')).toBeVisible();

    await page.getByRole('tab', { name: 'Synology' }).click();
    await expect(page.locator('#p-synology')).toBeVisible();
    await expect(page.locator('#p-macos')).toBeHidden();
    await expect(page.locator('.platform-panel:visible')).toHaveCount(1);

    // Arrow keys move within the strip, which is what `role="tablist"` promises. Asserting the
    // *neighbour* rather than a fixed panel: this caught the OpenMediaVault pill being inserted
    // between Synology and Linux, which is the test working, so it stays order-sensitive.
    await page.getByRole('tab', { name: 'Synology' }).press('ArrowRight');
    await expect(page.locator('#p-omv')).toBeVisible();
  });

  test('without JavaScript, every panel is visible under its own heading', async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    await page.goto('index.html');

    await expect(page.locator('.platform-panel:visible')).toHaveCount(PLATFORMS.length);
    for (const name of PLATFORMS) {
      await expect(page.locator('.platform-heading', { hasText: name })).toBeVisible();
    }
    // And no pill strip, because nothing could act on it (ADR-0095 point 6).
    await expect(page.locator('.platform-tabs')).toBeHidden();

    await context.close();
  });

  test('the GUI panels show no commands, which is why they are their own panels', async ({ page }) => {
    // Synology and OpenMediaVault both install through a web interface. If a command appears in
    // either, the reason for splitting them out of "Linux & NAS" has gone.
    await page.goto('index.html');
    for (const [tab, panel] of [['Synology', '#p-synology'], ['OpenMediaVault', '#p-omv']] as const) {
      await page.getByRole('tab', { name: tab }).click();
      await expect(page.locator(`${panel} pre`)).toHaveCount(0);
    }
  });

  test('the Windows caveat and the no-login paragraph are on the page', async ({ page }) => {
    await page.goto('index.html');
    await page.getByRole('tab', { name: 'Windows' }).click();
    await expect(page.locator('#p-windows .platform-caveat')).toContainText('Untested');
    await expect(page.locator('#remote .note')).toContainText('Familiar has no login');
  });

  test('the sticky nav does not bury the Install heading', async ({ page }) => {
    await page.setViewportSize({ width: 1100, height: 900 });
    await page.goto('index.html');
    await page.locator('.topnav-install').click();

    const nav = await page.locator('.topnav').boundingBox();
    // The *heading* is what gets buried, not the pills — those sit far enough down the section to
    // clear the nav even with no scroll padding at all, which is why asserting on them proved
    // nothing. Checked by setting `scroll-padding-top: 0` and watching this fail.
    const heading = await page.locator('#install h2').boundingBox();
    expect(nav).not.toBeNull();
    expect(heading).not.toBeNull();
    // `html { scroll-padding-top: 64px }` is what makes this pass; it is easy to lose.
    expect(heading!.y).toBeGreaterThanOrEqual(nav!.y + nav!.height);
  });
});
