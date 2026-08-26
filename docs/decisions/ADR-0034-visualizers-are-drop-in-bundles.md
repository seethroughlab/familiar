# ADR-0034: Visualizers Are Drop-In Bundles

Status: accepted — points 1 and 3 superseded by
[ADR-0087](ADR-0087-a-visualizer-is-a-document-not-a-component.md), point 4's two-source model by
[ADR-0089](ADR-0089-the-app-bundle-seeds-the-folder-and-is-not-a-source.md)

Date: 2026-08-06

Extends [ADR-0033](ADR-0033-the-embed-bridge-gains-a-return-channel.md).

## Implementation

Points 1–4 and 6–9 shipped together; point 5 remains deferred by design.

**In `familiar`:** `services/visualizerPlugins.ts` holds the manifest shape and every refusal rule,
pure and with no three.js in it; `services/visualizerPluginHost.ts` installs `window.Familiar`,
fetches what the host lists, and evaluates the survivors with `new Function`. `renderVisualizer`
loads plugins before the first render — after the built-in visualizers are registered, because their
ids are what a plugin is refused for colliding with. `stores/visualizerPluginStore.ts` records the
outcomes; `VisualizerPicker` shows the refusals; `AudioVisualizer` marks a crash and now falls back
to the album art rather than an error, which is point 8 as written. 33 tests.

**In `familiar-apple`:** `VisualizerPlugins.swift` finds folders, validates that each manifest parses,
resolves `main` inside its own directory, and builds `plugins/index.json`. `VisualizerSchemeHandler`
grew from one response to three. `VisualizerCatalog.swift` decodes what the page reports it can draw.
`VisualizerSettingsSection` reveals the folder. 34 tests.

Verified against the real artifacts rather than only fixtures: `familiar-plugin-lyric-pulse` and
`familiar-plugin-non-places` load from their actual built `dist/index.js` and register, and
`familiar-plugin-timeline` is refused as a browser. Both suites stay green — 1,016 in `familiar`,
893 in `familiar-apple` — and both apps build.

Four things were decided here that the ADR left open:

1. **A local bundle wins a collision with a shipped one**, and the shipped one is listed as
   `shadowed` rather than vanishing — resolving the tradeoff below. Overriding is what a drop-in
   directory is for; a shipped bundle sits inside a code-signed app the user cannot edit, so if
   shipped won there would be no way to replace one.
2. **A plugin claiming a built-in id is refused, not allowed to shadow it.** `registerVisualizer`
   overwrites by id and the registry has no removal, so the built-in would be unrecoverable short of
   deleting the file.
3. **The native menu had to learn about plugins**, which the ADR did not notice. It was
   `VisualizerChoice.allCases`, a fixed four, so a plugin could load perfectly and be unreachable —
   an affordance missing rather than a destination. The page now publishes a catalog the app reads
   with `evaluateJavaScript`, over the channel that already probes for the analysis sink. **No
   `WKScriptMessageHandler` was added**: the visualizer surface still says nothing unprompted, and
   this is the host asking.
4. **`Documents/Visualizers` on iOS**, per point 4's amendment — Application Support is invisible to
   the Files app.

The page-side and native-side rules are deliberately *not* symmetrical. The native side finds files
and checks nothing but the filesystem; every acceptance rule lives in the page, because the page is
what would have to run the bundle. Two copies of that rule in two languages is how the picker comes
to disagree with what actually loaded.

## Context

The ask is that someone could drop a three.js project into the app and have it become a visualizer
option. **That system was built, and then shelved.** Recording which is the point of this section,
because the alternative is re-deriving a decision that already has a history.

`dbdef05`, on 2026-03-06, removed 2,114 lines: `services/pluginLoader.ts` (301),
`services/__tests__/pluginLoader.test.ts` (268), `api/plugins.ts` (100),
`components/Settings/PluginsSettings.tsx` (378), `backend/app/api/routes/plugins.py` (355),
`backend/app/services/plugins.py` (480), `backend/app/db/models/plugins.py` (72), and a migration
dropping the `plugins` table. It was a scope cut, made the same afternoon as `ceeb926`, which
shelved listening sessions.

**What survived the cut is the whole authoring contract.** `components/Visualizer/types.ts` still
defines `VisualizerProps`, `VisualizerMetadata`, `visualizerRegistry` and `registerVisualizer`;
`docs/VISUALIZER_API.md` still documents them; `visualizers/_template/` still holds an
`ExampleVisualizer.tsx` and a 271-line README; and `visualizers/community/` is still there, empty
but for a `.gitkeep`. The API is designed, documented and in use by the four built-in visualizers.
Only the loader is gone.

**Three plugins built against it still exist as sibling directories on disk — but "three existing
plugin repositories" was wrong, and the count it implies is what point 1's argument rested on.**
Checked rather than remembered:

- `familiar-plugin-lyric-pulse` is a git repository, public at
  `github.com/seethroughlab/familiar-plugin-lyric-pulse` since 2026-01-15, and declares
  `"type": "visualizer"`. **It is the only one of the three that is all of those things.**
- `familiar-plugin-timeline` is also a public repository under the same account and the same date,
  but declares `"type": "browser"` and its bundle calls `registerBrowser`, not
  `registerVisualizer`. Point 9 puts it out of scope, so it is not a plugin this format has to keep
  working.
- `familiar-plugin-non-places` — the three.js one, and the one that actually exercises the shared
  globals — has **no `.git` directory at all** and is published nowhere. It is a working plugin and
  not a repository.

All three declare `"author": {"name": "Familiar", "url": "https://github.com/jeffweisbein"}`, an
account unrelated to this project. They are this project's own samples, written to demonstrate the
API. **No third party has written one, and there is no ecosystem to strand** — which is a reason to
adopt the existing format for cheapness, not a reason that adopting it is forced.

Each has a rollup config, a `dist/`, a README instructing the reader to *"Go to Settings >
Plugins"*, and a manifest of a settled shape:

```json
{
  "name": "Non-Places",
  "id": "non-places",
  "version": "0.1.0-alpha.1",
  "type": "visualizer",
  "main": "dist/index.js",
  "familiar": { "apiVersion": 1 },
  "icon": "Building2"
}
```

The shelved loader's own header describes how it worked, and it is the part worth keeping:

> Handles loading external plugins (visualizers and library browsers) from pre-built JavaScript
> bundles. Exposes a global `window.Familiar` API that plugins use to access React, Three.js,
> hooks, and registration functions.

React, `three`, `@react-three/fiber` and `@react-three/drei` were handed to the plugin as shared
globals rather than bundled by it. That is not a convenience: two copies of React in one document
do not work, and two copies of three.js in one WebGL context is 600 kB of duplicate for nothing.

**The bundles are IIFEs, not ES modules**, which is the one part of the format that decides how the
host loads them. All three rollup configs say `format: 'iife'`, every `dist/index.js` ends in
`})();`, and the shelved loader ran them with `new Function(bundleCode)` — not an import. A global
read at module scope is also the only thing that *can* work under a plain `Function` call, and
`window.Familiar` is read at the top of each bundle. Whichever way this is described in the
decision, it has to be the way they are actually built, or the format is being redesigned while
claiming to be adopted.

The externalisation is also less uniform than a single sentence would suggest. Only
`familiar-plugin-non-places` externalises `three`, `@react-three/fiber` and `@react-three/drei` —
and it deliberately *bundles* `three/examples/jsm/*`, with a comment saying so. The other two
externalise `react` and `react/jsx-runtime` and nothing else, because neither uses three.js.

**The App Store is why this is a decision and not a detail.** A shipped `.app` bundle is
code-signed and cannot be written to, so "drop it into the application bundle" resolves three ways
— ship it with the app, put it in a user directory, or fetch it — and only one of them is
straightforwardly permitted. App Review's position on downloaded interpreted code is that it is
allowed when it runs in the system's WebKit framework and does not change the app's primary
purpose. A visualizer bundle executing inside the `WKWebView` that
[ADR-0033](ADR-0033-the-embed-bridge-gains-a-return-channel.md) introduces satisfies both. The same
bundle evaluated in native JavaScriptCore would not, and a native plugin format would not even be
arguable.

So ADR-0033 is not merely the source of the audio data. It is the thing that makes this feature
permissible at all.

## Decision

1. **A visualizer is a pre-built IIFE bundle plus a `familiar-plugin.json` manifest**, in the shape
   the existing sample plugins already use: the bundle reads `window.Familiar` at its top level and
   calls `registerVisualizer` as a side effect of being evaluated. The format is adopted, not
   designed — but adopted because it costs nothing and two working samples already build to it, not
   because there is an ecosystem that a different choice would strand. There is not; see the
   Context.

2. **Bundles are evaluated only inside the visualizer web view, never in the app's own process.**
   This is stated as a rule with its reason attached, because the reason is what makes the feature
   shippable: interpreted code the app did not ship is acceptable in WebKit and is not acceptable
   anywhere else in an App Store binary.

3. **The host provides React, three.js, `@react-three/fiber` and `@react-three/drei` on a global,
   and a bundle must not carry its own.** A manifest whose bundle duplicates them is loaded anyway
   — nothing can check — but the API contract says it, `_template/` demonstrates it, and the one
   sample that uses three.js already externalises all four in its rollup config. The other two
   externalise only React, which is not a counter-example: a plugin externalises what it imports.

4. **Two sources, and only two: shipped and local.**
   *(Superseded by [ADR-0089](ADR-0089-the-app-bundle-seeds-the-folder-and-is-not-a-source.md):
   there is one source, the folder, and the app bundle seeds it. The per-platform directory this
   point specifies is unaffected and still governs.)*
 Shipped bundles live in the app bundle's
   resources and are what a fresh install has. Local bundles live in a `Visualizers/` directory the
   user can open, which a button in Settings reveals in Finder or the Files app. There is no third
   source in this ADR.

   **Which directory is per-platform, and not a detail that can be waved through.** On macOS it is
   Application Support, which is what a Mac app should use and what `NSWorkspace` can reveal. On
   iOS, Application Support is *not reachable from the Files app at all* — only the app's
   `Documents/` directory is, and only when `UIFileSharingEnabled` declares it. So the phone uses
   `Documents/Visualizers`. Naming Application Support for both would have specified something the
   phone cannot do, and the failure would have been a Settings button that reveals a folder the
   user can never put a file into.

5. **Install-from-URL is deferred, not rejected.** It is what the shelved `plugins.py` and
   `PluginsSettings.tsx` did, and bringing it back means a `plugins` table, a server route, a
   download path and a trust question about arbitrary JavaScript from a URL. Each of those is a
   decision, and none of them is this one. Points 1–4 are useful without it and are what "drop a
   project in" literally asks for.

6. **The API is `VisualizerProps` and `AudioData` as `docs/VISUALIZER_API.md` already documents
   them**, sourced from ADR-0033's channel rather than from Web Audio. That document stops being a
   web-app document and becomes the contract for every client, which is what makes a plugin written
   once run in the browser, on the Mac and on the phone.

7. **`familiar.apiVersion` is enforced.** A manifest declaring a version the host does not
   implement is refused with a reason shown in the picker, rather than loaded and left to fail
   somewhere inside a render loop.

8. **A visualizer that throws is unloaded, not fatal.** `AudioVisualizer.tsx` already wraps
   visualizers in an `ErrorBoundary` and a `Suspense`; a third-party crash falls back to the
   album-art square the player shows when no visualizer is available, and the picker marks the
   plugin as failed.

9. **Visualizers only. Library browsers are out of scope.** The shelved loader also registered
   browsers, and `familiar-plugin-timeline` is one. A browser is a management surface with a play
   affordance, which on an embedded page means the null engine, the play interceptor and the
   bridge all have to hold for third-party code — a much larger claim than a visualizer makes, and
   one [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md) would have something to say
   about.

## Alternatives Considered

**Native visualizer plugins — SwiftUI, Metal or SceneKit.** Would look and perform better than a
web view, and would not need ADR-0033 at all. Rejected on two independent grounds: there is no safe
mechanism for loading third-party native code into an App Store app, and it would forfeit the four
built-in visualizers, the three sample plugins, the template and the documented API — every
artefact that exists today.

**Revive install-from-GitHub along with the loader, as it was before the shelving.** It is what all
three plugin READMEs tell people to do, so this ADR leaves them describing a
button that does not exist. Rejected for now rather than permanently: the server half is 907 lines
across three files and a table, and the trust question — an app that downloads and runs code from a
URL the user typed — deserves its own argument rather than riding along with a file format. Point 5
records this as deferred so it is not read as settled.

**Keep compile-time registration and simply add more built-in visualizers.** Zero new machinery,
and it is how the four current ones work — `visualizers/index.ts` imports each for its side effect.
Rejected because it is precisely what the request is not: a visualizer would need a pull request
against the web app and a redeploy of both clients, which no one outside this repository will do.

**Load bundles from a folder the *server* serves, so one install reaches every client.** Attractive
for a self-hosted product, and it would put visualizers where the music already is. Rejected
because it makes the feature depend on the server for a screen that should work while offline
listening to downloaded tracks, and because it is install-from-URL with the URL fixed — the same
trust question with a friendlier surface.

**Sandbox each bundle in its own nested iframe.** Stronger isolation, and a crash could not reach
the host at all. Rejected as the wrong shape for this: the visualizer needs the shared WebGL
context, the shared three.js and the audio buffer, all of which an isolated frame would have to be
handed across another boundary — rebuilding ADR-0033's channel a second time, inside the page.

## Consequences

- **Positive:** The two sample visualizers that already exist become usable again, on the Mac and
  the phone as well as the browser they were written for. That is two, not three — the third is a
  library browser, which point 9 excludes.
- **Positive:** A visualizer is written once against a documented API and runs in the browser, on
  the Mac and on the phone, because point 6 makes the contract shared rather than per-client.
- **Positive:** The shelving is now recorded with its date and its scope, so the next person to
  find `visualizers/community/` empty knows why.
- **Tradeoff:** The app loads and executes code it did not ship. The blast radius is a web view
  with a null audio engine and no credentials beyond the server URL and profile it was given, but
  it is a genuine widening of what runs inside the app.
- **Tradeoff:** Point 3 is a contract nothing enforces. A plugin that bundles its own React will
  break in ways that look like a host bug, and the only defence is documentation.
- **Tradeoff:** Point 5 leaves all three plugin READMEs describing an installation route that does
  not exist. They should be corrected as part of this, or they become the fourth instance of an
  affordance pointing at a destination that is not mounted.
- **Tradeoff:** Shipped and local bundles can declare the same `id`. Which wins has to be decided
  in implementation, and whichever it is will surprise someone. *Decided: local wins, and the
  shipped one is listed as shadowed rather than disappearing. See Implementation.*
- **Tradeoff:** **Point 3 costs 1.59 MB on top of what drei already costs, measured.** Handing
  `@react-three/drei` to plugins means `import * as Drei`, and a namespace import cannot be
  tree-shaken: the inlined visualizer document is 1,782 kB without it and 3,375 kB with it.
  *Corrected from the first version of this line, which claimed nothing in the repo used drei.*
  `ScrollingLyrics` renders `LyricWordField`, which imports drei's `Text`, and `LyricStorm` renders
  the same field — so drei ships regardless. What the namespace import buys is the rest of the
  library, which point 3 promises plugins and which no first-party visualizer needs. It is also the
  one of the four a plugin could reasonably carry itself: two Reacts genuinely do not work and two
  three.js in one context is waste plus a shared-context problem, but a second drei is only bytes.
  The document is read from local disk rather than fetched, so the price is app-bundle size and
  parse time, not download time.
- **Tradeoff:** `familiar-plugin-non-places` is not under version control anywhere, and it is the
  only sample that exercises the shared three.js globals — which is to say the only one that would
  catch point 3 being broken. If that directory is lost, the evidence for the part of the contract
  nothing enforces goes with it.
- **Follow-up:** Install-from-URL, per point 5 — the shelved `plugins.py`, `api/plugins.ts` and
  `PluginsSettings.tsx` are the starting point, and the trust question is the actual decision.
- **Follow-up:** Library-browser plugins, per point 9. `familiar-plugin-timeline` is one and has
  nowhere to go until that is decided.
- **Follow-up:** `docs/VISUALIZER_API.md` documents `useAudioAnalyser` as reading a Web Audio
  `AnalyserNode`. Under ADR-0033 point 4 that is one of three sources, and the document should say
  so rather than describe the browser case as the only one.
