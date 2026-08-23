import { test, expect } from '@playwright/test';

/**
 * ADR-0087: a visualizer is a document that receives events.
 *
 * This exercises the contract itself rather than any particular visualizer — the handshake, the
 * three inbound events, and the isolation. It is the check that would catch the contract quietly
 * breaking, which matters more than usual here: the surface it belongs to is rendered inside a
 * `WKWebView` on the Mac and the phone, and **nothing else tests it**.
 *
 * The harness is written inline rather than shipped in `public/`, so the assertions and the thing
 * they assert against cannot drift apart.
 */
const PLUGIN = '/visualizers/spectrum/index.html';

const HARNESS = `<!doctype html><meta charset="utf-8">
<style>html,body{margin:0;height:100%}iframe{width:640px;height:360px;border:0}</style>
<iframe id="f" sandbox="allow-scripts" src="${PLUGIN}"></iframe>
<script>
  window.__ready = null;
  window.addEventListener('message', (e) => {
    if (e.source !== document.getElementById('f').contentWindow) return;
    if (e.data && e.data.type === 'familiar:ready') window.__ready = e.data;
  });
  window.feed = () => {
    const w = document.getElementById('f').contentWindow;
    w.postMessage({ type: 'familiar:track', apiVersion: 1,
      payload: { id: 'abc', title: 'A Song', artist: 'An Artist', duration: 100 } }, '*');
    w.postMessage({ type: 'familiar:state', apiVersion: 1,
      payload: { isPlaying: true, currentTime: 3 } }, '*');
    w.postMessage({ type: 'familiar:audio', apiVersion: 1, payload: {
      bass: 0.8, mid: 0.5, treble: 0.3, averageFrequency: 120,
      frequencyData: Array.from({ length: 64 }, (_, i) => 40 + (i * 3) % 200) } }, '*');
  };
</script>`;

test.describe('the visualizer document contract (ADR-0087)', () => {
  test('a plugin document handshakes, receives events, and draws — sandboxed', async ({ page, baseURL }) => {
    /**
     * One error here is the harness, not the subject, and it is thrown *because* the isolation
     * asserted at the bottom of this test works.
     *
     * `serviceWorkers: 'block'` in `playwright.config.ts` installs an init script into every frame,
     * and that script reads `navigator.serviceWorker`. In a frame sandboxed without
     * `allow-same-origin` the origin is opaque, and reading that property is a `SecurityError` —
     * so Playwright's own instrumentation throws inside the plugin document. Confirmed by flipping
     * the option: with `serviceWorkers: 'allow'` the error does not appear, and nothing about the
     * app or the plugin changes.
     *
     * Filtered by exact cause rather than relaxed to a count, so a real uncaught error in a
     * visualizer still fails this test.
     */
    const HARNESS_SERVICE_WORKER_ERROR = /Failed to read the 'serviceWorker' property from 'Navigator'/;

    const errors: string[] = [];
    page.on('pageerror', (e) => {
      if (HARNESS_SERVICE_WORKER_ERROR.test(String(e))) return;
      errors.push(String(e));
    });

    await page.goto(`${baseURL}/`);
    await page.setContent(HARNESS);

    // The handshake. Without it the host would post into a document that is not listening, and the
    // first track of a session would silently never arrive.
    await expect.poll(() => page.evaluate(() => window.__ready)).toEqual({
      type: 'familiar:ready',
      apiVersion: 1,
    });

    await page.evaluate(() => window.feed());

    const frame = page.frames().find((f) => f.url().includes('spectrum'));
    expect(frame, 'the plugin document should be loaded in a frame').toBeTruthy();

    await expect.poll(async () => frame!.evaluate(() => {
      const canvas = document.getElementById('c') as HTMLCanvasElement;
      const context = canvas.getContext('2d')!;
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
      let lit = 0;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i] + pixels[i + 1] + pixels[i + 2] > 40) lit++;
      }
      return lit;
    }), 'familiar:audio should be driving the canvas').toBeGreaterThan(500);

    // familiar:track arrived and was rendered.
    await expect.poll(async () =>
      frame!.evaluate(() => document.getElementById('title')?.textContent ?? '')
    ).toContain('A Song');

    // **The isolation ADR-0087 point 5 rests on.** `allow-scripts` without `allow-same-origin`
    // gives the document an opaque origin — this is the assertion that would fail if someone
    // added `allow-same-origin` to make something else easier.
    expect(await frame!.evaluate(() => String(window.origin))).toBe('null');
    expect(await frame!.evaluate(() => {
      try { return !!parent.document; } catch { return false; }
    })).toBe(false);

    expect(errors).toEqual([]);
  });
});
