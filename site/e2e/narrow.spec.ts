import { test, expect } from '@playwright/test';

/**
 * The page must not scroll sideways on a phone (ADR-0055's Follow-up).
 *
 * That follow-up recorded the nav's Install button and the body copy being cut off at 420px. It was
 * fixed somewhere in the intervening work and nothing was watching, so it could regress the same
 * way — a wide `<pre>`, a table, or an unbreakable string in a code block are all one edit away.
 *
 * 420px because that is where it was found, and it is narrower than the iPhone widths in the
 * responsive sweep.
 */
test('no horizontal overflow at 420px', async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 900 });
  await page.goto('index.html');

  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));

  // One pixel of slack for sub-pixel rounding; anything more is a real overflow.
  expect(scrollWidth, `page scrolls ${scrollWidth - innerWidth}px sideways`).toBeLessThanOrEqual(innerWidth + 1);
});
