import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

/**
 * Builds the embedded visualizer as **one self-contained HTML file**.
 *
 * Separate from `vite.config.ts` because the output is a different kind of artifact: the app's build
 * produces a site to be served, and this produces a single document to be embedded in the macOS and
 * iOS app bundles (ADR-0034 point 4 — "shipped bundles live in the app bundle's resources").
 *
 * **Why one file rather than a directory.** The Xcode project uses file-system synchronized groups,
 * which add files individually and flatten a directory's structure — so `assets/index-abc.js` would
 * land beside `index.html` and every relative path in it would break. Inlining sidesteps the whole
 * question: nothing to resolve, nothing to flatten, and one resource for the app to copy.
 *
 * The size that buys is real — three.js is ~1 MB — but this is read from local disk, not fetched,
 * so it costs bundle size and no load time.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@familiar/frontend': resolve(__dirname, '../frontend'),
    },
  },
  build: {
    outDir: 'dist-visualizer',
    emptyOutDir: true,
    // Everything in one chunk: the visualizers are `lazy()`, which would otherwise emit dynamic
    // chunks that a single document cannot reach.
    rollupOptions: {
      input: resolve(__dirname, 'visualizer.html'),
      output: { inlineDynamicImports: true },
    },
    // No separate CSS file, and no asset small enough to be left out.
    cssCodeSplit: false,
    assetsInlineLimit: Number.MAX_SAFE_INTEGER,
    // Sourcemaps would double the file and cannot be opened from inside an app bundle anyway.
    sourcemap: false,
  },
});
