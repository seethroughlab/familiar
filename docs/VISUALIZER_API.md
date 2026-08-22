# Visualizer API

A visualizer is **a folder with an `index.html`**. Familiar loads it in its own sandboxed frame and
posts it events. That is the whole contract.

It lends you nothing — no React, no three.js, no globals. Whatever you build the document from is
your business: a canvas, WebGL, shaders, p5, a `<video>`, or plain HTML.

> This replaces the previous contract, in which a visualizer was a React component registered onto
> `window.Familiar` and evaluated inside the host page. See
> [ADR-0087](decisions/ADR-0087-a-visualizer-is-a-document-not-a-component.md) for why it changed and
> what it cost.

## The smallest visualizer that works

```html
<!doctype html>
<meta charset="utf-8">
<style>html,body{margin:0;height:100%;background:#000}canvas{display:block;width:100%;height:100%}</style>
<canvas id="c"></canvas>
<script>
  const ctx = document.getElementById('c').getContext('2d');
  let level = 0;

  window.addEventListener('message', (event) => {
    const message = event.data;
    if (message?.type === 'familiar:audio') level = message.payload.bass;
  });

  (function draw() {
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, 10000, 10000);
    ctx.fillStyle = '#0af';
    ctx.fillRect(0, 0, 10000, level * 400);
    requestAnimationFrame(draw);
  })();

  // Last, once you are listening.
  parent.postMessage({ type: 'familiar:ready', apiVersion: 1 }, '*');
</script>
```

No build step, no dependencies, no imports. Drop that in a folder with a manifest and it is a
visualizer.

## The folder

```
my-visualizer/
  familiar-plugin.json    required
  index.html              required — the entry point
  …anything else          your JS, CSS, models, shaders, images
```

```json
{
  "name": "My Visualizer",
  "id": "my-visualizer",
  "version": "1.0.0",
  "type": "visualizer",
  "description": "One line, shown in the picker.",
  "author": { "name": "You" },
  "main": "index.html",
  "familiar": { "apiVersion": 1 },
  "icon": "Sparkles",
  "affinity": { "tags": [], "ranges": [] }
}
```

`id` must be lowercase letters, digits and hyphens — it goes in a URL. `apiVersion` is the version of
*this event contract*; a manifest declaring one the host does not implement is refused with a reason
shown in the picker rather than loaded and left to fail.

## The events

Three come in. One goes out.

### `familiar:ready` — you → Familiar

Send it once, **after** you have attached your `message` listener. Familiar does not post anything
until it arrives, so a visualizer that sends it too early misses the first track, and one that never
sends it receives nothing at all.

```js
parent.postMessage({ type: 'familiar:ready', apiVersion: 1 }, '*');
```

### `familiar:track` — the track changed

```ts
{
  type: 'familiar:track',
  apiVersion: 1,
  payload: {
    id: string | null,
    title: string | null,
    artist: string | null,
    album: string | null,
    artworkUrl: string | null,   // load it directly; it is a normal URL
    duration: number,            // seconds
    features: {                  // null when the track has not been analysed
      bpm?: number, key?: string, energy?: number, valence?: number,
      danceability?: number, acousticness?: number, /* … */
    } | null,
    lyrics: Array<{ text: string, startTime: number, endTime?: number }> | null,
  }
}
```

### `familiar:state` — transport

```ts
{ type: 'familiar:state', apiVersion: 1, payload: { isPlaying: boolean, currentTime: number } }
```

`currentTime` is seconds, and it is the playhead you should sync to.

### `familiar:audio` — an analysis frame

Sent on the host's animation loop while something is playing.

```ts
{
  type: 'familiar:audio',
  apiVersion: 1,
  payload: {
    bass: number,             // 0..1
    mid: number,              // 0..1
    treble: number,           // 0..1
    averageFrequency: number, // 0..255
    frequencyData: number[],  // 0..255 per bin
    beat: number,             // 0..1 — spikes on an onset, then decays
    onset: boolean,           // true only on the frame a transient is detected
  }
}
```

**`beat` and `onset` are what you want for anything rhythmic.** `bass` follows the low end
continuously, which is not the same thing: a track with a sustained bass note holds `bass` high and
produces no beats at all. `beat` is an envelope that spikes and falls, so it reads as pulse; `onset`
is a single-frame flag, which is what you spawn a ripple or flip a tile on.

These two were missing from the first version of this contract while the host computed them all
along — so a visualizer keying off them rendered perfectly and never moved. If you are debugging a
plugin that looks frozen, log the payload before assuming your own maths is wrong.

**Already smoothed.** Frames reach the host from a native player at about 10 Hz — macOS clamps the
audio tap — and the host reconstructs a 60 Hz signal before sending. You do not need to interpolate
it again, and doing so will make you late.

## You are obliged to receive, never to implement

A visualizer that ignores every event and draws a still image is a valid visualizer. There is no
lifecycle to satisfy, nothing to return, and no function you must export. Listen for what you want
and ignore the rest.

## Three things that will bite you

These are not style advice. Each one produced a visualizer that loaded and drew nothing, and each
took real time to diagnose because the failure is invisible from outside the frame.

### 1. Use a classic script, not a module

```html
<script src="./app.js"></script>          <!-- yes -->
<script type="module" src="./app.js"></script>   <!-- no -->
```

Your document has an **opaque origin**, because it is sandboxed without `allow-same-origin`. Module
scripts are always fetched with CORS, so the request arrives as `Origin: null` and is refused —
including for a file sitting in your own folder. If you use a bundler, build to an IIFE.

An *inline* `<script>` has no such problem, which is why the smallest example above works and a
bundled one may not.

### 2. Anything you `fetch` needs CORS headers

Same cause, wider effect. `fetch`, `XMLHttpRequest`, and therefore any loader built on them —
`GLTFLoader`, a shader fetched at runtime, a JSON config — are CORS-checked and will fail against a
server that does not send `Access-Control-Allow-Origin`.

Familiar's own loader sends it for files in your folder, so a model beside your `index.html` loads
fine. A file from somewhere else depends on that host's headers.

`<script src>`, `<img>`, `<link rel="stylesheet">` and `<video>` are **not** CORS-checked. If you can
express a dependency as one of those, it will always work.

### 3. Bundlers and `process.env.NODE_ENV`

If you bundle a library that reads `process.env.NODE_ENV` — React does — a library-mode build will
not define it, and your bundle throws `process is not defined` on its first line. In Vite:

```ts
define: { 'process.env.NODE_ENV': '"production"' }
```

## Affinity — what your visualizer suits

Optional. Declares what a track should be like for the server to pick you when the listener has
"Match to the Music" on ([ADR-0064](decisions/ADR-0064-visualizers-declare-affinity-and-the-server-ranks-them.md)).

```json
"affinity": {
  "tags": ["danceable", "drums", "funk"],
  "ranges": [{ "feature": "danceability", "minimum": 0.5 }]
}
```

Declaring nothing scores neutral, which is the honest answer for a visualizer that suits anything —
not last place. A tag or feature the server does not recognise is ignored and reported in the picker
rather than failing the manifest.

## Installing

Put the folder in Familiar's `Visualizers` directory — Settings has a button that reveals it — and
reopen the visualizer. There is no install-from-URL
([ADR-0034](decisions/ADR-0034-visualizers-are-drop-in-bundles.md) point 5).

A folder with no manifest is ignored silently, because that directory accumulates `.DS_Store` and
half-unzipped archives. A folder *with* a manifest that cannot be used is reported in the picker,
with the reason.

## When it does not appear

- **Not in the picker at all** — no `familiar-plugin.json`, or it is not valid JSON.
- **Listed with a reason** — the manifest parsed but was refused; the reason says which part.
- **Listed but blank** — the document loaded and drew nothing. Almost always one of the three traps
  above. Open the folder's `index.html` directly in a browser: everything except the events works
  there, and the console will show you the CORS or `process` error.
- **Draws but never moves** — you are probably not sending `familiar:ready`, so no events follow.

## What Familiar guarantees, and what it does not

**Guaranteed:** your document is loaded from your folder, its files are served with CORS headers, and
the four events keep the shapes above for as long as `apiVersion` is 1.

**Not guaranteed:** anything about libraries. Familiar ships no THREE, no React, no drei for you to
borrow, and there is no shared folder to load them from
([ADR-0087](decisions/ADR-0087-a-visualizer-is-a-document-not-a-component.md) point 7). Bundle what
you need. The visualizers Familiar ships do exactly that, and are worth reading as worked examples —
`spectrum` is 106 lines of canvas with no build step at all; `beat-tiles` is a three.js scene that
carries its own copy.
