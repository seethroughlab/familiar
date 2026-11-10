/**
 * The administration destinations pass an automated accessibility check (ADR-0174 points 6 and 7).
 *
 * axe-core against WCAG 2.1 A and AA, on Overview, Library, Analysis and Server, at a desktop and a
 * phone width, plus Analysis in a populated error state (grouped failures, failed tracks), since an
 * error state is where a dense page is most likely to lose its labels.
 *
 * Blocking: a violation fails the test. A rule that cannot be fixed yet goes in `EXCEPTIONS` with
 * an owner and the condition that removes it (point 7); there is no global allowlist. Automation
 * cannot establish full accessibility, which is why `docs/RELEASE-CHECKLIST.md` keeps a keyboard
 * and screen-reader pass (point 8).
 */
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

import { ensureProfile } from './helpers';

/** `{ ruleId: 'owner — removed when …' }`. Empty: the baseline is fixed. */
const EXCEPTIONS: Record<string, string> = {};

const DESTINATIONS = [
  { path: '/', name: 'Overview' },
  { path: '/library', name: 'Library' },
  { path: '/analysis', name: 'Analysis' },
  { path: '/server', name: 'Server' },
] as const;

const VIEWPORTS = [
  { name: 'desktop', width: 1280, height: 800 },
  { name: 'phone', width: 390, height: 844 },
] as const;

async function violations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
    .disableRules(Object.keys(EXCEPTIONS))
    .analyze();
  return results.violations.map((v) => ({
    rule: v.id,
    impact: v.impact,
    help: v.help,
    targets: v.nodes.slice(0, 5).map((n) => n.target.join(' ')),
  }));
}

async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  // Spinners and "Loading…" are not the page; wait until they have gone.
  await expect(page.getByText(/^Loading/)).toHaveCount(0, { timeout: 10000 });
}

for (const viewport of VIEWPORTS) {
  test.describe(`accessibility · ${viewport.name}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    for (const destination of DESTINATIONS) {
      test(`${destination.name} has no accessibility violations`, async ({ page }) => {
        await page.goto('/');
        await ensureProfile(page);
        await page.goto(destination.path);
        await settle(page);
        expect(await violations(page)).toEqual([]);
      });
    }

    test('Analysis with failures has no accessibility violations', async ({ page }) => {
      // The populated error state (point 6), seeded by answering the two requests that carry it.
      await page.route('**/api/v1/health/workers', async (route) => {
        const response = await route.fetch();
        const body = await response.json();
        body.failure_groups = [
          {
            kind: 'undecodable',
            task: 'extract_features',
            summary: 'The audio file could not be decoded',
            next_action: 'Check the file plays elsewhere, then replace or re-rip it.',
            count: 3,
            affected: 2,
            last_at: '2026-11-09T10:00:00',
            examples: [{ error: 'could not decode /music/a.mp3', track: 'A - B', timestamp: '2026-11-09T10:00:00' }],
          },
        ];
        await route.fulfill({ response, json: body });
      });
      await page.route('**/api/v1/library/analysis/failures**', (route) =>
        route.fulfill({
          json: {
            total: 1,
            failures: [
              {
                track_id: '00000000-0000-0000-0000-000000000001',
                title: 'Paris & Rome',
                artist: 'Cranes',
                phase: 'embeddings',
                reason: 'undecodable',
                attempts: 1,
                final: true,
                failed_at: '2026-11-09T10:00:00',
                error: 'could not decode',
              },
            ],
          },
        }),
      );
      await page.goto('/');
      await ensureProfile(page);
      await page.goto('/analysis');
      await settle(page);
      // Both error views: the failed tracks (ADR-0172) and the grouped task failures (ADR-0174).
      await expect(page.getByRole('region', { name: 'Failed tracks' })).toBeVisible();
      await expect(page.getByText('The audio file could not be decoded')).toBeVisible();
      expect(await violations(page)).toEqual([]);
    });
  });
}
