import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * The four pages agree with each other and with the product (ADR-0146's cleanup, 2026-10-03).
 *
 * Each case here was a defect on the live site: three different navs, one with an "Ask" link to
 * the features section; a FAQ that linked the App Store review demo and said "One compose up"; a
 * privacy page naming a community-cache host the server stopped using; and a visualizer page
 * whose renderer split every sentence into its own paragraph and linked ADRs at paths that 404.
 */
const PAGES = ['index.html', 'faq.html', 'privacy.html', 'visualizers.html'];
const NAV = ['Features', 'Compare', 'FAQ', 'Install'];

test.describe('every page', () => {
  for (const name of PAGES) {
    test(`${name} has the shared nav and footer`, async ({ page }) => {
      await page.goto(name);
      await expect(page.locator('.topnav-links a')).toHaveText(NAV);
      // GitHub belongs to the footer now (ADR-0146 point 5), and "Ask" pointed at #features.
      await expect(page.locator('.topnav-links')).not.toContainText('GitHub');
      await expect(page.locator('.topnav-links')).not.toContainText('Ask');
      const footer = page.locator('footer');
      for (const link of ['GitHub', 'Docs', 'FAQ', 'Privacy', 'Report a bug']) {
        await expect(footer.getByRole('link', { name: link })).toHaveCount(1);
      }
    });
  }
});

test('the FAQ links no demo, says nothing of compose, and answers Windows and Android', async ({ page }) => {
  await page.goto('faq.html');
  const main = page.locator('main');
  // The demo exists for App Store review (ADR-0038); index.html removed its link on purpose.
  await expect(page.locator('a[href*="familiar-demo"]')).toHaveCount(0);
  await expect(main).not.toContainText('compose up');
  await expect(main).not.toContainText('AI playlists');
  const answer = page.locator('details', { hasText: 'Windows or Android' });
  await expect(answer.locator('a[href*="ADR-0147"]')).toHaveCount(1);
});

test('the privacy page names the community cache the server actually uses', async ({ page }) => {
  const source = readFileSync(join(__dirname, '..', '..', 'backend', 'app', 'services', 'community_cache.py'), 'utf8');
  const host = new URL(/DEFAULT_CACHE_URL = "([^"]+)"/.exec(source)![1]).host;
  await page.goto('privacy.html');
  await expect(page.locator('main')).toContainText(host);
  await expect(page.locator('main')).not.toContainText('familiar-demo');
});

test('the visualizer page renders the document as paragraphs and links that resolve', async ({ page }) => {
  await page.goto('visualizers.html');
  // ADR links were relative to docs/ in the repository and 404'd on the site.
  await expect(page.locator('main a[href^="decisions/"]')).toHaveCount(0);
  // Blockquote markers were printed as text.
  const prose = await page.locator('main p, main li').allTextContents();
  expect(prose.filter((t) => t.trim().startsWith('>'))).toEqual([]);
  // Every source line was its own <p>, so sentences broke mid-way: no paragraph should end
  // without finishing its sentence.
  const unfinished = (await page.locator('main > p').allTextContents())
    .map((t) => t.trim())
    .filter((t) => t.length > 40 && !/[.:!?)"'`—…]$/.test(t));
  expect(unfinished).toEqual([]);
});
