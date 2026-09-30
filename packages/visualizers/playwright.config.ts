import { defineConfig } from '@playwright/test';

/**
 * No `webServer` and no `baseURL`: the spec fulfils every request itself from each visualizer's
 * `dist/`, the way `familiar-apple`'s contract spec serves the shipped bundle. Build first:
 * `pnpm --filter @familiar/visualizers build`.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  reporter: 'line',
  use: {
    // Headless Chromium has no GPU; three.js needs *a* WebGL context, and SwiftShader is one.
    launchOptions: { args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] },
  },
});
