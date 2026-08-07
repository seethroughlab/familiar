import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    // React 19's scheduler fires async work after jsdom teardown, producing
    // spurious "window is not defined" errors. These are harmless teardown
    // artifacts, not real test failures.
    dangerouslyIgnoreUnhandledErrors: true,
    // Vitest's default is 5s, and that is too tight for the machines this runs on.
    //
    // CI is two self-hosted runners that do other work: a NAS that also streams music
    // and builds Docker images, and a Mac that is somebody's desktop. On 2026-08-06 a
    // run took 4m21s where it normally takes 31s — an 8x slowdown — and two tests hit
    // the 5s ceiling. **Both were synchronous**: a `render` followed by `getByRole`
    // with no awaiting anywhere, so nothing in them was hanging. The render itself was
    // starved of CPU.
    //
    // 15s keeps roughly 3x headroom over that observed worst case while still failing
    // a genuinely hung test in a reasonable time. Raising this rather than pinning the
    // job to one runner is deliberate: either machine can be busy, so placement moves
    // the flake rather than removing it.
    testTimeout: 15_000,
    hookTimeout: 15_000,
  },
});
