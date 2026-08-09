#!/usr/bin/env node
/**
 * Folds the visualizer build's JS and CSS into its HTML, producing one self-contained document.
 *
 * Vite inlines *assets* but still emits the entry script and stylesheet as separate files and links
 * to them. For a document that will be read out of an app bundle over a custom URL scheme, one file
 * is much simpler than teaching the scheme handler to resolve relative paths — and it makes the
 * artifact something you can copy with `cp` and reason about by looking at it.
 */
import fs from 'node:fs';
import path from 'node:path';

const dist = path.resolve(process.argv[2] ?? 'dist-visualizer');
const htmlPath = path.join(dist, 'visualizer.html');

if (!fs.existsSync(htmlPath)) {
  console.error(`[inline-visualizer] No build at ${htmlPath}. Run the visualizer build first.`);
  process.exit(1);
}

let html = fs.readFileSync(htmlPath, 'utf8');

// Scripts: <script type="module" crossorigin src="/assets/x.js"></script>
html = html.replace(/<script[^>]*src="([^"]+)"[^>]*><\/script>/g, (whole, src) => {
  const file = path.join(dist, src.replace(/^\//, ''));
  if (!fs.existsSync(file)) return whole;
  const code = fs.readFileSync(file, 'utf8');
  // `type="module"` is kept: the bundle uses module semantics (strict mode, top-level scope).
  return `<script type="module">\n${code}\n</script>`;
});

// Stylesheets: <link rel="stylesheet" crossorigin href="/assets/x.css">
html = html.replace(/<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>/g, (whole, href) => {
  const file = path.join(dist, href.replace(/^\//, ''));
  if (!fs.existsSync(file)) return whole;
  return `<style>\n${fs.readFileSync(file, 'utf8')}\n</style>`;
});

// Preload hints point at files that no longer exist independently.
html = html.replace(/<link[^>]*rel="modulepreload"[^>]*>\s*/g, '');

const out = path.join(dist, 'visualizer.inlined.html');
fs.writeFileSync(out, html);

const remaining = html.match(/(src|href)="\/assets\//g);
if (remaining) {
  console.error(`[inline-visualizer] ${remaining.length} unresolved asset reference(s) remain.`);
  process.exit(1);
}

console.log(`[inline-visualizer] Wrote ${out} (${(Buffer.byteLength(html) / 1024).toFixed(0)} kB)`);
