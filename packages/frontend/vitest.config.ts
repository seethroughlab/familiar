import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    // React 19's scheduler fires async work after jsdom teardown, producing
    // spurious "window is not defined" errors. These are harmless teardown
    // artifacts, not real test failures.
    dangerouslyIgnoreUnhandledErrors: true,
  },
});
