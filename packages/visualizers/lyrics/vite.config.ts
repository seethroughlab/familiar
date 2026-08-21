import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { copyFileSync, mkdirSync } from 'node:fs';

/**
 * A visualizer builds itself (ADR-0087 point 7). Nothing is external: three.js, React and
 * `@react-three/fiber` are bundled in, because the host provides none of them.
 *
 * **An IIFE, not an ES module, and that is not a style preference.** A plugin document is loaded
 * in a sandboxed iframe with an *opaque* origin, and module scripts are always fetched with CORS —
 * so `<script type="module" src="app.js">` arrives at the server as `Origin: null` and is refused
 * unless it answers with `Access-Control-Allow-Origin`. A classic script has no such check.
 *
 * Found the hard way: the first build of this plugin loaded nothing and logged a CORS error for
 * its own bundle, sitting in its own folder. Inline scripts hide it, which is why the earlier
 * one-file examples worked and this did not.
 */
export default defineConfig({
  plugins: [
    react(),
    {
      // index.html is authored, not processed: it must reference a classic script, which Vite's
      // HTML pipeline will not emit.
      name: 'copy-plugin-files',
      closeBundle() {
        mkdirSync(`../../web/public/visualizers/lyrics`, { recursive: true });
        for (const file of ['index.html', 'familiar-plugin.json']) {
          copyFileSync(file, `../../web/public/visualizers/lyrics/${file}`);
        }
      },
    },
  ],
  // React reads `process.env.NODE_ENV`, and a library build does not define it the way an app
  // build does — without this the bundle throws `process is not defined` on its first line, in a
  // sandboxed frame where the error is invisible unless you go looking.
  define: { 'process.env.NODE_ENV': '"production"' },
  build: {
    outDir: '../../web/public/visualizers/lyrics',
    emptyOutDir: true,
    lib: { entry: 'src/main.tsx', formats: ['iife'], name: 'ScrollingLyrics', fileName: () => 'app.js' },
  },
});
