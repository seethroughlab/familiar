# ADR-0091: Visualizers Leave the Server Repo

Status: accepted

Date: 2026-08-25

Extends [ADR-0087](ADR-0087-a-visualizer-is-a-document-not-a-component.md) and
[ADR-0088](ADR-0088-every-visualizer-ships-as-a-document.md). It does not touch
[ADR-0064](ADR-0064-visualizers-declare-affinity-and-the-server-ranks-them.md).

**It supersedes nothing, and that is the finding.** Neither ADR-0087 nor ADR-0088 ever decided where
the shipped set lives — checked 2026-08-25, and neither mentions `packages/web/public/visualizers`,
a source of truth, or a repository at all. ADR-0088's four points are about *what* ships and how it
is built, not where it sits. The location was never chosen; it followed the build, which was in the
web repo because the browser once rendered visualizers.

## Context

Visualizer documents are authored and built in `familiar`, in `packages/web/public/visualizers/`,
and vendored into `familiar-apple` by `scripts/vendor-visualizers.sh`. `VisualizerBundle.html` is
built there too, by `scripts/build-visualizer.sh`, from `vite.visualizer.config.ts`. The server also
serves them: `/visualizer` for the single-document surface and, since
[#192](https://github.com/seethroughlab/familiar/pull/192), a `/visualizers` static mount.

**Nothing fetches either one.** Checked 2026-08-25:

- **The web app has no visualizer surface at all.** `App.tsx` and `routes.ts` contain **zero**
  visualizer references — it left with the fallback player under ADR-0057 point 5 and ADR-0071.
- **The one production module that names those paths is not asking the server.**
  `services/visualizerCatalog.ts` requests `/visualizers/index.json` (line 80) and
  `/visualizers/{id}/{main}` (line 141) — but it runs *inside the visualizer document*, which the
  Apple clients load over a custom scheme, so those URLs resolve against the app bundle.
  `VisualizerSchemeHandler` answers all three shapes through `VisualizerPlugins.route(path:)`:
  `.document`, `.index` (built by `indexJSON`) and `.file`. Every other `/visualizers/...` string in
  `packages/frontend/src` is a fixture, in five `__tests__` files.
- **The Apple clients never ask the server.** `EmbeddedVisualizerView` registers a
  `familiar-visualizer://` scheme handler and reads the documents out of the app bundle. That is
  ADR-0033's own decision, and its reason still holds: a custom scheme is a real origin, so
  `localStorage` works and the chosen visualizer survives a relaunch. There is no code path in
  `familiar-apple` that requests `/visualizer` or `/visualizers` over HTTP.

So the server hosts a capability with no caller, which is exactly what
[ADR-0077](ADR-0077-a-surface-with-no-caller-is-deleted-not-documented.md) says to delete rather than
document. The `/visualizers` mount is a partial exception and worth stating plainly: it was added to
fix a real defect — the SPA catch-all was answering `200` with `index.html` for plugin documents —
and its only consumer is `packages/web/e2e/visualizer-document-contract.spec.ts`. It fixed the test,
and the test was the only thing that needed it.

**A contradicted premise, recorded so it is not re-derived.** It is tempting to say ADR-0088 put the
shipped set in the web repo; it did not, and no ADR did. The set is there because the *build* is
there, and the build is there because the browser once rendered visualizers. That second reason
stopped being true when the player was deleted, leaving only the build — and a build is a reason to
keep a *toolchain* somewhere, not a source of truth.

**What the server legitimately keeps.** `POST /tracks/{id}/visualizers/rank` and
`services/visualizer_affinity.py` stay exactly as they are. ADR-0064's shape is that *the client
sends its candidates and the server ranks them* — the server scores declarations against a track's
analysis and is never told which visualizers a device holds. That is analysis work that happens to
mention visualizers, not visualizer hosting.

## Decision

**Scope narrowed before merge.** The proposal bundled the server removal with moving the build and
the plugin folders into `familiar-apple`. Implementation showed those are not alike: the folders are
authored in place and cheap to move, but `VisualizerBundle.html` is a React app whose source reaches
through `renderVisualizer` into `EmbedVisualizer`, `visualizerSink`, `visualizerStore`, `api/base`,
`embedBridge`, `index.css` and Tailwind. Moving it means moving a subtree of `packages/frontend` —
which contradicted this ADR's own Tradeoff, where the fate of those modules was explicitly *not*
being decided. Both could not be true. The relocation is now
[ADR-0092](ADR-0092-the-visualizer-document-build-moves-to-the-app.md), where a React subtree can get
the alternatives it deserves. What is left here is the part that stands on its own.

1. **The server stops serving visualizer content.** `/visualizer`, the `/visualizers` mount and the
   `visualizers/` entry in `NON_SPA_PREFIXES` are removed from `backend/app/main.py`, along with
   `serve_visualizer`. This is the whole of the finding in Context: neither surface has a caller.

2. **The contract test loses its dependency on the server, and stays.** It is the only check that
   the ADR-0087 handshake works, and that ADR says so itself. Rather than being deleted with the
   mount, it serves the plugin document to the page directly. It moves to `familiar-apple` under
   ADR-0092, with the documents it tests.

3. **`ADR-0064`'s ranking endpoint is untouched.** The server keeps scoring affinity declarations
   against analysis. Point 1 removes content, not ranking.

## Alternatives Considered

**Leave both surfaces in place.** Costs nothing today. Rejected because it already misleads: the
`/visualizers` mount was added three weeks ago to fix a real defect and its only consumer turned out
to be a test, which is precisely the shape ADR-0077 names. A surface kept alive for its own test is
not a surface.

**Delete `/visualizer` but keep `/visualizers`.** Tempting, since the mount is new and fixed a real
bug. Rejected for the same reason: the bug it fixed was the SPA catch-all answering `200` with
`index.html`, and once nothing fetches plugin documents from the server there is nothing left to
answer wrongly.

**Delete the contract test along with the mount.** The cheapest option, and wrong. ADR-0087 says
outright that nothing else tests the handshake, and the surface it guards is rendered inside a
`WKWebView` on two platforms. Point 2 removes its dependency on the server instead, which is what
made deleting it look necessary.

**Move the folders and the build now, as first proposed.** Rejected on discovering the two halves
are not alike — see the note above the points. Deferred to ADR-0092 rather than abandoned.

## Consequences

- **Positive.** Two surfaces with no callers are gone, and `main.py`'s static-serving block stops
  accumulating special cases for content nothing requests.
- **Positive.** The contract test no longer needs a server to run, which is what lets it move
  repositories cleanly under ADR-0092.
- **Positive.** The server's remaining relationship to visualizers is exactly one thing — ranking,
  under ADR-0064 — and it is a pure function of analysis and posted candidates.
- **Tradeoff.** `packages/web/public/visualizers/` and `scripts/vendor-visualizers.sh` stay for now,
  so the web repo is still where a visualizer is edited. That friction is the thing ADR-0092
  removes; this ADR only stops the server serving them.
- **Follow-up.** ADR-0092 moves the folders, the build and the contract test. Until it lands, the
  vendoring script is still the way a change reaches the app.
- **Follow-up.** Neither `familiar-plugin-lyric-pulse` nor `familiar-plugin-non-places` has been
  ported to a document — both are still `"main": "dist/index.js"` components from ADR-0034. If the
  worked examples ADR-0065 asks for are still wanted, porting them belongs after the move, in the
  repository that will then own them.
