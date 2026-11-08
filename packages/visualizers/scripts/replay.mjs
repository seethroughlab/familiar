#!/usr/bin/env node
/**
 * Replay a probe recording from a device into a built visualizer, and set the harness's frames
 * beside the device's.
 *
 *   node scripts/replay.mjs <document> <probe.jsonl> <out-dir> [--engine webkit|chromium] [--cover file]
 *
 * <document> is a folder name under this package (`beat-tiles`), built to `dist/`. The recording
 * is what `familiar-apple`'s visualizer probe writes (see `familiar`'s
 * `packages/frontend/src/services/visualizerProbe.ts`): every `familiar:audio` payload the device
 * posted, its `familiar:frame` captures, and its stats.
 *
 * **Why it exists.** Beat Tiles was tuned twice against renders driven by a made-up beat, on
 * another engine, and the phone showed something else both times. This sends the document the
 * same payloads at the same times as the device did, captures the harness's own frame at each
 * moment the device captured one, and writes `report.json` with mean luminance and the share of
 * near-white pixels for both. Where the two disagree, the harness is not to be trusted for that
 * question, and the device frames are the answer.
 *
 * The cover comes from the recording's `artworkUrl` (artwork needs no token), or `--cover`.
 */
import { webkit, chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const args = process.argv.slice(2);
const flag = (name) => { const i = args.indexOf(name); return i >= 0 ? args.splice(i, 2)[1] : undefined; };
const engineName = flag('--engine') ?? 'webkit';
const coverFile = flag('--cover');
const [documentId, recordingPath, outDir] = args;
if (!documentId || !recordingPath || !outDir) {
  console.error('usage: replay.mjs <document> <probe.jsonl> <out-dir> [--engine webkit|chromium] [--cover file]');
  process.exit(2);
}

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const dist = path.join(ROOT, documentId, 'dist');
if (!fs.existsSync(path.join(dist, 'index.html'))) {
  console.error(`${documentId} is not built: run pnpm --filter @familiar/visualizers build`);
  process.exit(2);
}
const recordingDir = path.dirname(path.resolve(recordingPath));
const records = fs.readFileSync(recordingPath, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
const audio = records.filter((r) => r.kind === 'audio');
const frames = records.filter((r) => r.kind === 'frame');
const track = records.filter((r) => r.kind === 'track').at(-1)?.payload ?? null;
const pageInfo = records.find((r) => r.kind === 'page') ?? { width: 390, height: 844, devicePixelRatio: 3 };
if (audio.length === 0) { console.error('the recording has no audio payloads'); process.exit(1); }
fs.mkdirSync(outDir, { recursive: true });

// Cover: the recorded URL, fetched here, or a file.
let cover = null;
if (coverFile) cover = { body: fs.readFileSync(coverFile), type: coverFile.endsWith('.png') ? 'image/png' : 'image/jpeg' };
else if (track?.artworkUrl) {
  try {
    const res = await fetch(track.artworkUrl);
    if (res.ok) cover = { body: Buffer.from(await res.arrayBuffer()), type: res.headers.get('content-type') ?? 'image/jpeg' };
  } catch { /* drawn without a cover, and the report says so */ }
}

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.glb': 'model/gltf-binary', '.jpg': 'image/jpeg', '.png': 'image/png', '.hdr': 'application/octet-stream' };
const engine = engineName === 'chromium' ? chromium : webkit;
const browser = await engine.launch(engineName === 'chromium' ? { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] } : {});
const page = await browser.newPage({ viewport: { width: pageInfo.width, height: pageInfo.height } });
await page.route('http://familiar.test/**', (route) => {
  const p = new URL(route.request().url()).pathname;
  if (p === '/cover') return cover
    ? route.fulfill({ status: 200, contentType: cover.type, body: cover.body, headers: { 'access-control-allow-origin': '*' } })
    : route.fulfill({ status: 404 });
  if (p.startsWith('/v/')) {
    const f = path.join(dist, p.slice(3));
    return fs.existsSync(f)
      // The app's scheme handler answers every plugin file with ACAO * (the document has an
      // opaque origin), so a texture or model the document loads must get it here too.
      ? route.fulfill({ status: 200, contentType: TYPES[path.extname(f)] ?? 'application/octet-stream', body: fs.readFileSync(f), headers: { 'access-control-allow-origin': '*' } })
      : route.fulfill({ status: 404 });
  }
  return route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html>' });
});
await page.goto('http://familiar.test/');
await page.setContent(`<!doctype html><style>html,body{margin:0;height:100%;background:#000}iframe{position:absolute;inset:0;width:100%;height:100%;border:0}</style>
<iframe id="f" sandbox="allow-scripts" src="/v/index.html"></iframe><script>
window.__ready = false; window.__frames = [];
addEventListener('message', (e) => {
  if (!e.data) return;
  if (e.data.type === 'familiar:ready') window.__ready = true;
  if (e.data.type === 'familiar:frame') window.__frames.push(e.data.payload);
});
window.send = (m) => document.getElementById('f').contentWindow.postMessage({ apiVersion: 1, ...m }, '*');
</script>`);
await page.waitForFunction(() => window.__ready, null, { timeout: 30000 });
await page.evaluate((t) => {
  send({ type: 'familiar:track', payload: { ...(t ?? {}), lyrics: null, artworkUrl: 'http://familiar.test/cover' } });
  send({ type: 'familiar:state', payload: { isPlaying: true, currentTime: 0 } });
}, track);
await page.waitForTimeout(1500); // the cover loads

// Replay in real time, from the first audio payload; capture the harness's own frame each time the
// device captured one, by asking the document exactly as the device's host did.
const t0 = audio[0].t;
const end = audio.at(-1).t;
const deviceFrames = frames.filter((f) => f.t >= t0 && f.t <= end);
const report = { document: documentId, engine: engineName, cover: Boolean(cover), page: pageInfo, seconds: (end - t0) / 1000, pairs: [] };
const startedAt = Date.now();
let ai = 0;
for (const df of deviceFrames) {
  // Feed everything up to this moment, keeping the device's timing.
  while (ai < audio.length && audio[ai].t <= df.t) {
    const wait = audio[ai].t - t0 - (Date.now() - startedAt);
    if (wait > 0) await page.waitForTimeout(wait);
    await page.evaluate((p) => send({ type: 'familiar:audio', payload: p }), audio[ai].payload);
    ai++;
  }
  const before = await page.evaluate(() => window.__frames.length);
  await page.evaluate(() => send({ type: 'familiar:capture' }));
  await page.waitForFunction((n) => window.__frames.length > n, before, { timeout: 5000 }).catch(() => {});
  const harness = await page.evaluate(() => window.__frames.at(-1)?.image ?? null);
  const name = `t${String(Math.round((df.t - t0) / 100) / 10).replace('.', '_')}s`;
  const deviceImage = df.file ? fs.readFileSync(path.join(recordingDir, df.file)) : decode(df.payload?.image);
  if (deviceImage) fs.writeFileSync(path.join(outDir, `${name}-device.jpg`), deviceImage);
  if (harness) fs.writeFileSync(path.join(outDir, `${name}-${engineName}.jpg`), decode(harness));
  report.pairs.push({
    at: (df.t - t0) / 1000,
    deviceStats: df.payload?.stats ?? null,
    device: deviceImage ? await luminance(page, deviceImage) : null,
    harness: harness ? await luminance(page, decode(harness)) : null,
  });
}
await browser.close();
fs.writeFileSync(path.join(outDir, 'report.json'), JSON.stringify(report, null, 2));
for (const p of report.pairs) {
  const f = (x) => (x ? `mean ${x.mean.toFixed(2)}, near-white ${(x.nearWhite * 100).toFixed(1)}%` : 'none');
  console.log(`${p.at.toFixed(1)}s  device: ${f(p.device)}  |  ${engineName}: ${f(p.harness)}  |  bloom ${JSON.stringify(p.deviceStats)}`);
}
console.log(`wrote ${report.pairs.length} pairs to ${outDir}`);

function decode(dataUrl) {
  if (!dataUrl) return null;
  return Buffer.from(dataUrl.slice(dataUrl.indexOf(',') + 1), 'base64');
}

/** Mean luminance (0–1) and the share of pixels above 0.92, measured in the browser. */
async function luminance(pg, jpeg) {
  return pg.evaluate(async (b64) => {
    const img = new Image();
    img.src = `data:image/jpeg;base64,${b64}`;
    await img.decode();
    const c = document.createElement('canvas');
    c.width = img.width; c.height = img.height;
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, c.width, c.height).data;
    let sum = 0; let white = 0; const n = d.length / 4;
    for (let i = 0; i < d.length; i += 4) {
      const l = (0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2]) / 255;
      sum += l; if (l > 0.92) white++;
    }
    return { mean: sum / n, nearWhite: white / n };
  }, jpeg.toString('base64'));
}
