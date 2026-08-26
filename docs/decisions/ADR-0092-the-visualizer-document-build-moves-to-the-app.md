# ADR-0092: The Visualizer Document Build Moves to the App

Status: accepted

Date: 2026-08-25

Extends [ADR-0091](ADR-0091-visualizers-leave-the-server-repo.md), which stopped the server *serving*
visualizers and deferred moving them. Extends
[ADR-0087](ADR-0087-a-visualizer-is-a-document-not-a-component.md) and
[ADR-0088](ADR-0088-every-visualizer-ships-as-a-document.md) without superseding either — as ADR-0091
records, neither ever decided where the shipped set lives.

## Context

ADR-0091 was proposed as one move and narrowed on contact with the code. The reason is worth keeping,
because it is the whole of this decision: **the two things that live in `familiar` are not alike.**

**The plugin folders are authored in place.** `packages/web/public/visualizers/<id>/` holds
`index.html`, `app.js`, `style.css` and `familiar-plugin.json`, written by hand — `spectrum`'s own
manifest says "One file, no build step, no libraries". Nothing generates them. The only built thing
beside them is `index.json`, produced by `scripts/build-visualizer-index.mjs`, and it exists because
a browser cannot enumerate a directory. The Swift side does not even use it: `VisualizerPlugins`
builds its own listing with `indexJSON(folders)` from the real folders. Moving these is a `git mv`.

**`VisualizerBundle.html` is a React application.** `scripts/build-visualizer.sh` runs
`vite.visualizer.config.ts` over `packages/web/visualizer.html`, whose entry is
`packages/web/src/visualizer.tsx`, which imports `NullAudioEngine`, `registerEngineFactory` and
`renderVisualizer` — and `renderVisualizer` reaches `EmbedVisualizer`, `visualizerSink`,
`visualizerStore`, `api/base`, `embedBridge` and `index.css`, which is Tailwind. The output is
353 kB inlined into a single file by `scripts/inline-visualizer.mjs`.

So "move the build" means moving a subtree of `packages/frontend` and a Tailwind pipeline into a
Swift repository. ADR-0091's proposal said `familiar-apple` "gains a `package.json` used only to
produce `VisualizerBundle.html`" while its own Tradeoff said the fate of `visualizerPlugins.ts`,
`visualizerCatalog.ts` and the stores was **not** being decided. Both could not be true, and that
contradiction is why this is a separate ADR.

**What is genuinely shared.** `EmbedVisualizer` and the visualizer stores are reachable only from
`renderVisualizer`, but `api/base` and `embedBridge` are also used by `/embed`, which stays in the web
repo under ADR-0016 and ADR-0017. A move that takes them breaks Discover; a move that copies them
creates two of the thing ADR-0020 point 2 caps at two messages precisely to avoid.

## Decision

1. **The plugin folders move, and `familiar-apple` owns them.**
   `packages/web/public/visualizers/` and `scripts/build-visualizer-index.mjs` are deleted;
   `App/Shared/Visualizers.bundle/` becomes the source of truth rather than a vendored copy, and
   `scripts/vendor-visualizers.sh` goes with them.

2. **The host document's build stays in `familiar` for now, and the artifact keeps being vendored.**
   `scripts/build-visualizer.sh` continues to produce `VisualizerBundle.html` and copy it across.
   Moving a Tailwind React subtree that `/embed` still shares is a larger decision than this one, and
   doing it badly costs more than the friction it removes.

3. **The contract test moves with the folders.** `visualizer-document-contract.spec.ts` goes to
   `familiar-apple`, which gains Playwright for it. ADR-0091 point 2 already removed its dependency
   on a running server, so it moves as a file rather than as a rewrite.

4. **A plugin folder is never built.** Point 1 is a relocation, not a pipeline. If a visualizer ever
   needs a build step it brings its own, as the three `@react-three/fiber` scenes already do, and
   ADR-0088 point 2's acceptance of duplication stands.

## Alternatives Considered

**Move everything, including the host document build.** The original ADR-0091 proposal. Rejected for
now: it takes `api/base` and `embedBridge`, which `/embed` still uses, so it either breaks Discover
or duplicates the modules. Point 2 leaves the door open — this is "not yet", not "never".

**Move the host build and leave the folders.** The opposite split. Rejected because it is the wrong
half: the folders are what someone edits when they change a visualizer, and the friction ADR-0091
identified is having to commit in another repository to do it. The bundle is regenerated rarely and
by a script.

**Keep everything where it is and accept the vendoring.** Rejected on the evidence ADR-0091 already
gathered: a merge conflict in a generated file was resolved this month by running a generator in a
different repository, and the folders' only remaining consumer is an app that carries its own copy.

**Give the plugin folders their own repository.** Rejected for the same reason ADR-0091 rejected it
for the whole set: ADR-0087 point 6 forbids the app requiring another checkout to build, and a third
repository has to be released in step with the app that embeds it.

## Consequences

- **Positive.** Editing a shipped visualizer becomes one commit in the repository that ships it, with
  no script run and no second copy to drift.
- **Positive.** The contract test sits beside the documents it tests, so a change to either shows up
  in one diff.
- **Tradeoff.** `familiar-apple` gains Playwright, and therefore Node, for one test. That is a second
  ecosystem in a Swift repository, and it is the price of the test living where its subject does.
- **Tradeoff.** `VisualizerBundle.html` is still vendored, so one cross-repo artifact remains. It is
  the one that is regenerated by script rather than edited by hand, which is the better half to leave.
- **Follow-up.** Once the folders are gone, `visualizerCatalog.ts`'s `/visualizers/...` URLs are
  served only by `VisualizerSchemeHandler`. That is already true in production — ADR-0091 records it —
  but it becomes the only truth, and the web repo's copies of those modules should be revisited then.
- **Follow-up.** Whether the host document build ever follows is left open by point 2, and depends on
  what happens to `/embed`'s shared modules.
