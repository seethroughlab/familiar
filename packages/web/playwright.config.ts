import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  // Use serial execution to avoid race conditions with shared database/audio
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [['html'], ['json', { outputFile: 'playwright-report/results.json' }]],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:4400',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    // CI builds the app and serves `dist/` from the backend, so the PWA service worker is
    // registered — locally these run against the dev server, where it is not. `page.route` does not
    // intercept requests a service worker handles, and Workbox's runtime caching handles **GET**s,
    // so a mocked GET silently reached the real backend while a mocked POST did not.
    //
    // That asymmetry hid itself until a GET started mattering: the chat specs' `/chat/status` mock
    // had never applied in CI, and nobody noticed while the chat toggle was unconditional. Once the
    // toggle depended on that endpoint, CI's provider-less backend answered "not configured", the
    // toggle correctly disappeared, and seven specs failed against an app that was behaving exactly
    // as designed.
    serviceWorkers: 'block',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          args: ['--autoplay-policy=no-user-gesture-required'],
        },
      },
    },
  ],
  // Run local dev server before tests if needed
  // webServer: {
  //   command: 'npm run dev',
  //   url: 'http://localhost:5173',
  //   reuseExistingServer: !process.env.CI,
  // },
});
