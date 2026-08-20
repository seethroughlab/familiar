# ADR-0087: A Visualizer Is a Document, Not a Component

Status: accepted

Date: 2026-08-20

Supersedes [ADR-0034](ADR-0034-visualizers-are-drop-in-bundles.md) points 1 and 3. Reframes
[ADR-0067](ADR-0067-the-plugin-api-exposes-what-a-first-party-visualizer-uses.md) and redirects
[ADR-0068](ADR-0068-built-in-visualizers-ship-as-drop-in-bundles.md), both still `proposed`. Must be
settled before [ADR-0063](ADR-0063-the-visualizer-api-is-published-for-outside-authors.md) publishes
the contract to outside authors.

## Implementation

**Point 6 landed first**, on `familiar-apple` `feature/visualizer-documents`: the scheme handler
serves any file inside a plugin's folder, with content types by extension and containment enforced
in two places — the router refuses an empty, `.` or `..` component, and `resolve(relativePath:in:)`
standardises the URL before comparing against the plugin's own directory with a trailing separator.
Nine tests cover both layers independently. One existing test changed meaning rather than being
deleted: `testAnythingElseUnderPluginsIsTheDocumentRatherThanAFileRead` had encoded `ADR-0034`'s "no
request carries a path", which is exactly what this ADR reverses.

**The isolation question was spiked before anything was built on it.** Point 1 says "its own
browsing context" and the host embeds the plugin in an `<iframe>`; whether that iframe could be
`sandbox="allow-scripts"` — opaque origin, no ambient authority — was unknown, because a custom
scheme plus an opaque origin is where a surprise would hide. A standalone `WKWebView` harness ran
both cases:

| | `sandbox="allow-scripts"` | no sandbox |
|---|---|---|
| subresources fetched over the scheme | `index.html`, `style.css`, `app.js` — all | all |
| script ran, stylesheet applied | yes | yes |
| `window.origin` | **`null`** | `familiar-visualizer://plugin` |
| reaches the host's DOM | no | no |
| `postMessage` both directions | yes | yes |

So the strong form works and is what ships. Two mechanisms stack rather than one doing the work:
**distinct host components** (`//host` and `//plugin`) already make the plugin a separate origin —
the control run could not reach the host's DOM either — and **the sandbox attribute** makes it an
opaque one on top.

**One residual, recorded rather than assumed away.** `allow-scripts` without `allow-same-origin`
denies cookies, `localStorage` and same-origin access, but **it does not restrict network access**.
A plugin can still `fetch()` anywhere it likes. The handler serves the plugin document, so it is in
a position to attach a `Content-Security-Policy` that confines it — that is the next thing to
decide, not something this ADR has already solved.

## Context

A visualizer today is a pre-built IIFE, evaluated with `new Function` **inside the host page**,
which reads `window.Familiar` for `React`, `THREE`, `ReactThreeFiber` and `Drei`, and registers a
React component. So the contract is: *a visualizer is a React component, and here are our four
library versions.*

**`ADR-0034` point 1 records that this shape was inherited rather than chosen:**

> "The format is **adopted, not designed** — but adopted because it costs nothing and two working
> samples already build to it, not because there is an ecosystem that a different choice would
> strand. **There is not.**"

That was a reasonable call when the samples were the only consumers. It stops being reasonable at
the moment `ADR-0063` publishes the contract outward, because four library versions in a public API
are very hard to retract.

**The failure that prompted this.** `ADR-0065` seeds the drop-in folder with worked examples, and
one of them — `lyric-pulse` — crashed the first time it ever ran, on a freshly built app. Its bundle
ends `})(window.Familiar.React)` and renders with `jsxRuntime.jsxs(...)`, but **React does not export
`jsxs`**; the automatic JSX runtime lives in a different module. Verified against the installed
React 19.2.4:

```
React.jsxs          undefined
React.createElement function
jsx-runtime.jsxs    function
```

Lyric Pulse draws **divs with a glow**. It is not 3D, it does not touch THREE, and it needs no
renderer. It was broken by framework plumbing that the contract obliged it to use and that it never
wanted. That is the shape of the problem, not an unlucky bug: the cost of the component contract is
paid by every plugin, including the ones with nothing to gain from it.

**How much of the framework is actually earned.** Of the five built-ins, three are
`@react-three/fiber` scene graphs — `ReactiveTerrain`, `BeatTiles`, `LyricWordField` — where
declarative THREE genuinely pays for itself. The other two, `ScrollingLyrics` and `MusicVideo`, are
plain DOM and use React only because everything around them does. `vendor-three` is **2.4 MB
(764 KB gzipped)**, vendored into the app inside `VisualizerBundle.html`.

**The objection that would sink an event model does not hold here.** The natural worry is that
real-time audio cannot cross a document boundary fast enough. It already crosses a *process*
boundary: `player/audio/nativeAnalysisBuffers.ts:20` records that frames "from a native host arrive
at **10 Hz** against a 60 Hz render loop — macOS clamps `installTap`", and line 26 that the host
"sends the envelope instead: ~43 Hz of onset resolution inside a 10 Hz channel". The page already
reconstructs a 60 Hz animation from a 10 Hz feed. A `postMessage` hop into a child document is noise
against that.

**What the host already serves.** `VisualizerSchemeHandler` routes three kinds of request over a
custom scheme: the host document, a JSON index of plugins, and a plugin's single `dist/index.js` as
`text/javascript`. The machinery for serving plugin files from a per-platform folder — Application
Support on macOS, `Documents/Visualizers` on iOS (`ADR-0034` point 4) — exists and is tested.

## Decision

1. **A visualizer is a folder containing an `index.html`.** The host loads that document in its own
   browsing context. Whatever is inside it — canvas, WebGL, shaders, p5, three.js, a `<video>`, or
   plain DOM — is the plugin's business.

2. **The host sends data and lends nothing.** There is no `window.Familiar` library surface: no
   React, no THREE, no `@react-three/fiber`, no `Drei`. The whole API is three inbound events and
   one outbound handshake:

   | | |
   |---|---|
   | `familiar:track` | the track changed — id, title, artist, album, artwork URL, features, lyrics |
   | `familiar:audio` | an analysis frame — the `AudioData` shape `ADR-0034` point 6 already defines |
   | `familiar:state` | playing or paused, and the playhead |
   | `familiar:ready` (out) | the document is listening, so the host knows a blank frame is loading rather than broken |

   What `ADR-0034` point 6 defined as `VisualizerProps` and `AudioData` survives as the *payload*.
   Only the delivery changes. **A visualizer that ignores every event and draws nothing is still a
   valid visualizer** — the contract obliges a plugin to receive, never to implement.

3. **`ADR-0034` point 3 is superseded outright.** "The host provides four libraries and a bundle
   must not carry its own" was the source of the coupling, of the version contract `ADR-0063` was
   about to publish, and of the Lyric Pulse failure. A plugin brings what it needs.

4. **`ADR-0034` point 2 is unchanged and better served.** Interpreted code the app did not ship is
   evaluated only inside WebKit, never in the app's process. A document satisfies that more plainly
   than `new Function` does.

5. **Isolation is a feature, not a side effect.** A plugin that throws takes down its own document
   and nothing else. The error boundary in `AudioVisualizer` exists because plugins currently share
   the host's page — `ADR-0034` point 8's "unload a visualizer that throws" becomes structural
   rather than defensive.

6. **The scheme handler serves a folder, not a file.** `.bundle(source, id)` becomes a path within
   the plugin's directory, with MIME types by extension and **containment checks**, since a folder
   is a traversal surface that a single known filename was not. This is the one place the change
   adds risk rather than removing it, and it is named here so it is designed rather than discovered.

7. **There is no sharing mechanism at all, and the existing visualizers are not a constraint on
   this.** Every visualizer is a document that carries what it needs. No injected globals, no
   host-vendored library served by URL, no externals in a plugin's build config.

   **This is the point where the decision was made deliberately against the current set.** The
   simplest contract and the survival of three `@react-three/fiber` scene graphs are in tension: a
   sharing mechanism exists only to spare them each bundling THREE. Asked directly, the answer was
   that a solid, simple contract matters more than any particular visualizer. So the hatch is not
   built, and the three r3f built-ins are rewritten as self-contained documents, demoted to
   optional drop-ins, or dropped — a question for whoever does the work, not a constraint on the
   contract.

8. **The shipped set is deliberately small, and elaborate visualizers are drop-ins.** Point 7's cost
   is paid in the app bundle if the shipped set is large — three self-contained r3f documents is
   several copies of a 2.4 MB library. The answer is not a sharing mechanism but fewer shipped
   visualizers: one or two cheap ones that prove the contract and give a fresh install something to
   look at. Anything heavier is something a listener installs, which is what `ADR-0034` point 4's
   two sources were for.

9. **`familiar.apiVersion` (`ADR-0034` point 7) now versions the event contract**, which is a much
   smaller thing to keep compatible than four libraries.

## Alternatives Considered

**Keep the component contract and add `jsxRuntime` to the globals.** This is a two-line fix for the
actual bug, and it should be applied regardless if this ADR is rejected. Rejected as the decision
because it treats the symptom: the next author writing a DOM-only visualizer still has to satisfy a
React contract, and `ADR-0063` still publishes four library versions.

**Keep evaluating in the host page, but stop providing libraries.** Removes the version contract
while avoiding a document boundary. Rejected because it keeps the worst property — a plugin's crash
is the host's crash — while giving up the only thing the shared page bought, which was not having to
ship your own React.

**One document per plugin, but keep injecting React into it.** A half-measure that preserves the
familiar authoring experience with isolation added. Rejected because injecting a framework into a
document that could simply `<script src>` it is strictly worse than letting it choose: same version
contract, more machinery.

**Keep one sharing mechanism — let a plugin load a host-vendored THREE by URL.** This is what
point 7 said in the first draft, and it exists solely to spare the three r3f built-ins from each
bundling a 2.4 MB library. Rejected on the explicit steer that a solid, simple contract matters more
than any particular visualizer: a sharing mechanism is a version contract wearing a different hat,
and the first plugin that loads a *different* THREE alongside it finds out the hard way. Point 8
answers the bundle-size worry by shipping fewer visualizers instead.

**Convert plugins to documents but leave the built-ins as components in the host page.** Cheapest
path, and it is what the code would do if nobody decided otherwise. Rejected under point 7:
`ADR-0068` was written precisely to stop built-ins and drop-ins being two different things that
drift, and that argument survives this ADR even though its chosen format does not.

**Render visualizers natively instead.** Out of scope and against `ADR-0016` point 1's test —
these are large, moving, and expressed in web technology; `ADR-0034` point 2's App Store constraint
also applies only because they are interpreted, which native rendering would not fix so much as
sidestep by deleting the feature's premise.

## Consequences

- **Positive** — the public contract shrinks from "a React component plus four library versions" to
  "an HTML document that receives events". That is the thing `ADR-0063` publishes, and it is one a
  newcomer can hold in their head.
- **Positive** — a plugin can be written in anything, including a single file of vanilla canvas with
  no build step. Today the minimum viable plugin is a rollup config that externalises four packages.
- **Positive** — Lyric Pulse's failure mode becomes unrepresentable.
- **Positive** — crash isolation stops depending on an error boundary in shared memory.
- **Tradeoff** — every plugin ships its own libraries, so folders get bigger. On disk that is cheap.
  In the *app bundle* it is not, which is why point 8 shrinks the shipped set rather than adding a
  sharing mechanism to preserve it.
- **Tradeoff** — **the current visualizers are not preserved by this decision, and that was chosen
  rather than overlooked.** The three r3f scene graphs are rewritten, demoted to drop-ins, or
  dropped. Anyone reading this later should not treat their loss as a regression to be fixed by
  reintroducing shared libraries.
- **Tradeoff** — **`ADR-0067` and `ADR-0068` were aimed at the wrong contract.** 0067 shrinks to
  almost nothing, which is a good outcome reached by an unwelcome route; 0068's conversion work is
  redirected rather than executed. Both are `proposed`, so nothing shipped is being unwound, but
  effort was spent.
- **Tradeoff** — the event contract has to be designed. `VisualizerProps` to events is not purely
  mechanical: props are pull, events are push, and the 10 Hz feed means the plugin now owns the
  interpolation the host does today.
- **Tradeoff** — point 6 introduces path traversal as a concern the current handler does not have.
- **Follow-up** — `docs/VISUALIZER_API.md` is rewritten rather than amended, and it is the document
  `ADR-0063` publishes.
- **Follow-up** — `lyric-pulse` is fixed or reseeded either way. A seeded example that crashes on
  first run is worse than shipping no examples at all.
