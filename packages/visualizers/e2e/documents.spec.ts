/**
 * Every first-party visualizer document against the same recorded host events (ADR-0125 point 4).
 *
 * `familiar-apple`'s `visualizer-document-contract.spec.ts` proves the vanilla document — the
 * dependency-free path — handshakes, receives and draws. This is the SDK path's equivalent, run
 * over each built document in turn: the handshake with the protocol version, the recorded events
 * and the malformed ones the bridge must survive, a canvas on the page, and `familiar:stats`
 * frames arriving — the render loop is alive and the fps reporter `announceReady` starts is
 * running. Pixels are not read: these draw with WebGL, and a software context's output is not
 * the thing under test.
 *
 * The whole origin is served from `dist/`; `familiar.test` is reserved by RFC 6761 and never
 * leaves the process.
 */
import { test, expect } from '@playwright/test';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const ORIGIN = 'http://familiar.test';
const DOCUMENTS = ['beat-tiles', 'lyric-storm', 'lyrics', 'reactive-terrain'] as const;

const TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.glb': 'model/gltf-binary',
};

/** The recorded events, as `@familiar/visualizer-sdk/src/fixtures/events.ts` holds them. */
const FEED = `
  const w = document.getElementById('f').contentWindow;
  w.postMessage({ type: 'familiar:track', apiVersion: 1,
    payload: { id: 'abc', title: 'A Song', artist: 'An Artist', duration: 100, artworkUrl: null, features: { energy: 0.7, valence: 0.6 }, lyrics: [{ time: 0, text: 'hello' }, { time: 2, text: 'world' }] } }, '*');
  w.postMessage({ type: 'familiar:state', apiVersion: 1, payload: { isPlaying: true, currentTime: 3 } }, '*');
  w.postMessage({ type: 'familiar:audio', apiVersion: 1, payload: {
    bass: 0.8, mid: 0.5, treble: 0.3, averageFrequency: 120, beat: 0.9, onset: true,
    frequencyData: Array.from({ length: 64 }, (_, i) => 40 + (i * 3) % 200) } }, '*');
  // What a bridge must survive (the SDK's malformed fixtures).
  w.postMessage('familiar:audio', '*');
  w.postMessage({ type: 'familiar:audio', apiVersion: 1 }, '*');
  w.postMessage({ type: 'familiar:audio', apiVersion: 1, payload: { bass: 'loud', frequencyData: 'nope' } }, '*');
  w.postMessage({ type: 'familiar:track', apiVersion: 1, payload: 42 }, '*');
  w.postMessage({ type: 'familiar:audio', apiVersion: 2, payload: { bass: 1 } }, '*');
  w.postMessage({ type: 'familiar:track', apiVersion: 1, payload: null }, '*');
  w.postMessage({ type: 'familiar:track', apiVersion: 1,
    payload: { id: 'abc', title: 'A Song', artist: 'An Artist', duration: 100 } }, '*');
`;

for (const id of DOCUMENTS) {
  test(`${id}: handshakes, survives the recorded events, and keeps rendering`, async ({ page }) => {
    const dist = path.join(ROOT, id, 'dist');
    test.skip(!fs.existsSync(path.join(dist, 'index.html')), `${id} is not built — run pnpm --filter @familiar/visualizers build`);

    const HARNESS_SERVICE_WORKER_ERROR = /Failed to read the 'serviceWorker' property from 'Navigator'/;
    const errors: string[] = [];
    page.on('pageerror', (e) => {
      if (HARNESS_SERVICE_WORKER_ERROR.test(String(e))) return;
      errors.push(String(e));
    });
    const consoleErrors: string[] = [];
    page.on('console', (m) => {
      if (m.type() === 'error') consoleErrors.push(m.text());
    });

    await page.route(`${ORIGIN}/**`, (route) => {
      const { pathname } = new URL(route.request().url());
      const prefix = `/visualizers/${id}/`;
      if (pathname.startsWith(prefix)) {
        const file = path.join(dist, pathname.slice(prefix.length));
        if (fs.existsSync(file)) {
          return route.fulfill({ status: 200, contentType: TYPES[path.extname(file)] ?? 'application/octet-stream', body: fs.readFileSync(file) });
        }
        return route.fulfill({ status: 404, body: '' });
      }
      return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: '<!doctype html>' });
    });

    await page.goto(`${ORIGIN}/`);
    await page.setContent(`<!doctype html><meta charset="utf-8">
<style>html,body{margin:0;height:100%}iframe{width:640px;height:360px;border:0}</style>
<iframe id="f" sandbox="allow-scripts" src="/visualizers/${id}/index.html"></iframe>
<script>
  window.__ready = null; window.__stats = [];
  window.addEventListener('message', (e) => {
    if (e.source !== document.getElementById('f').contentWindow) return;
    if (e.data && e.data.type === 'familiar:ready') window.__ready = e.data;
    if (e.data && e.data.type === 'familiar:stats') window.__stats.push(e.data);
  });
  window.feed = () => { ${FEED} };
</script>`);

    await expect.poll(() => page.evaluate(() => (window as unknown as { __ready: unknown }).__ready), {
      timeout: 15_000,
    }).toEqual({ type: 'familiar:ready', apiVersion: 1 });

    await page.evaluate(() => (window as unknown as { feed: () => void }).feed());

    const frame = page.frames().find((f) => f.url().includes(`/visualizers/${id}/`));
    expect(frame, 'the plugin document should be loaded in a frame').toBeTruthy();
    await expect.poll(() => frame!.evaluate(() => document.querySelectorAll('canvas').length)).toBeGreaterThan(0);

    // The fps reporter posts once a second while the loop runs; two frames means it kept running
    // after the events, malformed ones included.
    await expect.poll(
      () => page.evaluate(() => (window as unknown as { __stats: unknown[] }).__stats.length),
      { timeout: 10_000 },
    ).toBeGreaterThanOrEqual(2);

    expect(errors, 'uncaught errors in the document').toEqual([]);
    // A version-2 message is warned about once, never logged as an error.
    expect(consoleErrors.filter((t) => /familiar/.test(t)), 'bridge errors').toEqual([]);
  });
}
