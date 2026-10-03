import { test, expect } from '@playwright/test';

/**
 * The marketing site's install choosers (ADR-0095, then ADR-0143): where the server runs, and
 * where you listen.
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
// ADR-0143 point 2: the Mac first, the NAS choices equal to it.
const PLATFORMS = ['Mac', 'Synology', 'OpenMediaVault', 'Linux & NAS', 'Windows'];
const SERVER_PANELS = ['#p-macos', '#p-synology', '#p-omv', '#p-linux', '#p-windows'];

test.describe('install platform chooser', () => {
  test('shows one platform at a time, and the pills switch it', async ({ page }) => {
    await page.goto('index.html');

    await expect(page.locator('#platforms .platform-panel')).toHaveCount(PLATFORMS.length);
    await expect(page.locator('#platforms .platform-panel:visible')).toHaveCount(1);
    await expect(page.locator('#p-macos')).toBeVisible();

    await page.getByRole('tab', { name: 'Synology' }).click();
    await expect(page.locator('#p-synology')).toBeVisible();
    await expect(page.locator('#p-macos')).toBeHidden();
    await expect(page.locator('#platforms .platform-panel:visible')).toHaveCount(1);

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

    await expect(page.locator('#platforms .platform-panel:visible')).toHaveCount(PLATFORMS.length);
    for (const name of PLATFORMS) {
      await expect(page.locator('#platforms .platform-heading', { hasText: name })).toBeVisible();
    }
    // Both players too, and the line that is true for one server only, with its "If" wording.
    await expect(page.locator('#clients .platform-panel:visible')).toHaveCount(2);
    await expect(page.locator('.when-server[data-server="mac"]')).toBeVisible();
    await expect(page.locator('.when-server[data-server="mac"]')).toContainText('If your server is Familiar Server');
    // And no pill strip, because nothing could act on it (ADR-0095 point 6).
    await expect(page.locator('.platform-tabs:visible')).toHaveCount(0);

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

  test('the Windows panel names the override an install actually needs', async ({ page }) => {
    // This asserted an "Untested" caveat until 2026-08-30, when the install was run end to end on
    // Windows 11 and the caveat was earned out. What replaced it is the load-bearing claim:
    // `docker-compose.desktop.yml` is not optional there. `journald` is Linux-only and Docker
    // Desktop's VM rejects it — measured at exit 125 — so a panel that stops mentioning the
    // override ships a Windows install that fails.
    await page.goto('index.html');
    await page.getByRole('tab', { name: 'Windows' }).click();
    await expect(page.locator('#p-windows')).toContainText('docker-compose.desktop.yml');
    await expect(page.locator('#p-windows .platform-caveat')).toHaveCount(0);
  });

  test('every server path ends signed in', async ({ page }) => {
    // ADR-0143 point 4. Since ADR-0141 a new server answers its API with 401 until signed in, so
    // a path that stops at "open it in a browser" stops one step short of working.
    await page.goto('index.html');
    await expect(page.locator('#p-macos')).toContainText('Open Admin');
    for (const panel of ['#p-synology', '#p-omv', '#p-linux', '#p-windows']) {
      await expect(page.locator(panel)).toContainText('#token=');
    }
    await expect(page.locator('#install')).not.toContainText('needs no account');
  });

  test('the Mac path is Familiar Server, with no Docker and no command', async ({ page }) => {
    // ADR-0143 point 3. Docker on a Mac is in docs/INSTALLATION.md, not on the page.
    await page.goto('index.html');
    await expect(page.locator('#p-macos')).toContainText('Familiar Server');
    await expect(page.locator('#p-macos')).not.toContainText('Docker Desktop');
    await expect(page.locator('#p-macos pre')).toHaveCount(0);
    // The memory note is for Docker machines; Familiar Server has no such switch.
    await expect(page.locator('.unless-server[data-server="mac"]')).toBeHidden();
    await page.getByRole('tab', { name: 'Linux & NAS' }).click();
    await expect(page.locator('.unless-server[data-server="mac"]')).toBeVisible();
  });

  test('the listening step follows the server chosen in the first', async ({ page }) => {
    // ADR-0143 point 5: "Open in Familiar" is true only when the server is Familiar Server on the
    // same Mac, so it must disappear when another server is chosen.
    await page.goto('index.html');
    await page.locator('[data-chooser="client"]').getByRole('tab', { name: 'Mac' }).click();
    await expect(page.locator('#c-mac')).toBeVisible();
    await expect(page.locator('#c-mac .when-server')).toBeVisible();

    await page.getByRole('tab', { name: 'Synology' }).click();
    await expect(page.locator('#c-mac .when-server')).toBeHidden();
    await expect(page.locator('#c-mac a[href*="platform=mac"]')).toBeVisible();
  });

  test('the chosen pair is in the link, and a link opens on it', async ({ page }) => {
    // ADR-0143 point 1: a coworker sent the link lands on their own path.
    await page.goto('index.html');
    await page.getByRole('tab', { name: 'OpenMediaVault' }).click();
    await page.getByRole('tab', { name: 'iPhone & iPad' }).click();
    expect(new URL(page.url()).hash).toBe('#install?server=omv&client=iphone');

    await page.goto('index.html#install?server=windows&client=mac');
    await expect(page.locator('#p-windows')).toBeVisible();
    await expect(page.locator('#c-mac')).toBeVisible();
    await expect(page.locator('#c-mac .when-server')).toBeHidden();
  });

  test('a link with a value the page does not know is not an error', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto('index.html#install?server=freebsd&client=watch');
    await expect(page.locator('#p-macos')).toBeVisible();
    await expect(page.locator('#c-iphone')).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('the analysis note makes no per-track promise', async ({ page }) => {
    // ADR-0143 point 7. "Roughly 1 second per track" was measured nowhere; on Familiar Server on
    // 2026-10-02 a track took minutes.
    await page.goto('index.html');
    await expect(page.locator('#install .note')).not.toContainText('per track');
  });

  test('the no-login paragraph is on the page', async ({ page }) => {
    await page.goto('index.html');
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
