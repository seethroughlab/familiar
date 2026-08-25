# ADR-0091: Visualizers Leave the Server Repo

Status: proposed

Date: 2026-08-25

Extends [ADR-0087](ADR-0087-a-visualizer-is-a-document-not-a-component.md) and supersedes
[ADR-0088](ADR-0088-every-visualizer-ships-as-a-document.md) point 2's choice of *where* the shipped
set lives. It does not touch [ADR-0064](ADR-0064-visualizers-declare-affinity-and-the-server-ranks-them.md).

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

**A contradicted premise, recorded so it is not re-derived.** ADR-0088 put the shipped set in the
web repo because that is where the build was, and at the time the browser still rendered
visualizers. The second half stopped being true when the player was deleted; only the build
remained, and a build is a reason to keep a *toolchain* somewhere, not a source of truth.

**What the server legitimately keeps.** `POST /tracks/{id}/visualizers/rank` and
`services/visualizer_affinity.py` stay exactly as they are. ADR-0064's shape is that *the client
sends its candidates and the server ranks them* — the server scores declarations against a track's
analysis and is never told which visualizers a device holds. That is analysis work that happens to
mention visualizers, not visualizer hosting.

## Decision

1. **`familiar-apple` owns the shipped visualizer set.** `App/Shared/Visualizers.bundle/` becomes
   the source of truth rather than a vendored copy, and `scripts/vendor-visualizers.sh` is deleted
   along with `packages/web/public/visualizers/`.

2. **The build moves with the sources it builds.** `vite.visualizer.config.ts`,
   `scripts/inline-visualizer.mjs` and `scripts/build-visualizer.sh` move to `familiar-apple`, which
   gains a `package.json` used only to produce `VisualizerBundle.html` and the plugin folders. Xcode
   still must not require a build step — the artifacts stay committed, as ADR-0087 point 6 requires.

3. **The server stops serving visualizer content.** `/visualizer`, the `/visualizers` mount and the
   `visualizers/` entry in `NON_SPA_PREFIXES` are removed from `backend/app/main.py`, along with
   `serve_visualizer`.

4. **The document contract test moves too.** `visualizer-document-contract.spec.ts` follows the
   documents into `familiar-apple`. It is the only check that the ADR-0087 handshake still works,
   and ADR-0087's own note that *"nothing else tests it"* is the reason it must not simply be
   deleted with the mount it depends on.

5. **`ADR-0064`'s ranking endpoint is untouched.** The server keeps scoring affinity declarations
   against analysis. Point 3 removes content, not ranking.

## Alternatives Considered

**Leave it as it is.** Costs nothing today, and the vendoring works. Rejected because it already
misleads: this session resolved a merge conflict in `VisualizerBundle.html` by re-running a
generator in a *different repository*, and added a server mount whose only consumer is a test. Both
are symptoms of the source of truth being in the wrong place, and both will recur.

**Move the visualizers to their own repository.** The precedent exists —
`familiar-plugin-lyric-pulse` and `familiar-plugin-non-places` are real repositories. Rejected for
the shipped set specifically: a third repository has to be checked out, released and versioned in
step with the app that embeds it, and ADR-0087 point 6 already forbids the app requiring another
checkout to build. Drop-in plugins authored elsewhere keep working exactly as they do now — that is
what the folder in the user's directory is for.

**Keep the build in `familiar` and vendor only.** The status quo with the mount deleted. Rejected
because it leaves the awkward half in place: `familiar-apple` would still be unable to change a
visualizer without a commit in another repository and a script run, which is the friction this ADR
exists to remove.

**Delete `/visualizer` but keep `/visualizers`.** Tempting, because the mount is three weeks old and
fixes a real bug. Rejected: keeping a static mount alive for a test is the shape ADR-0077 names, and
point 4 moves the test rather than stranding it.

## Consequences

- **Positive.** A visualizer change is one commit in one repository, with no cross-repo script run
  and no chance of the two copies disagreeing.
- **Positive.** The server loses two surfaces with no callers, and `main.py`'s static-serving block
  gets smaller rather than continuing to accumulate special cases.
- **Positive.** ADR-0087's contract test ends up beside the documents it tests, where a change to
  either is visible in one diff.
- **Tradeoff.** `familiar-apple` gains a Node toolchain it did not have. It is build-time only and
  never required by Xcode, but it is a second ecosystem in a Swift repository.
- **Tradeoff.** The web repo's `visualizerPlugins.ts`, `visualizerCatalog.ts` and the three
  visualizer stores become unreferenced once the documents leave. Deciding their fate is deliberately
  **not** part of this ADR — they are the host side of a page that no longer has a home in the
  browser, and that is a separate question.
- **Follow-up.** `packages/web/dist-visualizer` is listed in `.gitignore` and was tracked anyway
  until `git rm -r --cached` on 2026-08-08. Whatever moves should not bring that back.
- **Follow-up.** Neither `familiar-plugin-lyric-pulse` nor `familiar-plugin-non-places` has been
  ported to a document — both are still `"main": "dist/index.js"` components from ADR-0034. If the
  worked examples ADR-0065 asks for are still wanted, porting them belongs after this move, in the
  repository that will then own them.
