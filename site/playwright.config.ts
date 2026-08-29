import { defineConfig, devices } from '@playwright/test';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';

/**
 * The marketing site's own test config (ADR-0095).
 *
 * Deliberately separate from `packages/web/playwright.config.ts`: that one has a `globalSetup`
 * which POSTs `/api/v1/library/sync` and a `baseURL` pointing at a running backend. `site/` is
 * static HTML over `file://` and needs neither — borrowing that config makes a document test fail
 * for want of a database.
 *
 * `baseURL` is resolved here rather than in the spec so the spec needs no `import.meta.url`, which
 * would make Playwright treat it as ESM and fail against this repository's CommonJS default.
 *
 *     npx playwright test --config=site/playwright.config.ts
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  reporter: 'line',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: pathToFileURL(join(__dirname, '/')).href,
  },
  projects: [{ name: 'chromium' }],
});
