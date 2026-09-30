# ADR-0125: First-Party Visualizers Share an Authoring SDK

Status: accepted

Date: 2026-09-17

Extends [ADR-0087](ADR-0087-a-visualizer-is-a-document-not-a-component.md). It does not reintroduce the
host-provided runtime rejected by that record: each built document remains self-contained.

Implementation:
- **2026-09-19, `familiar` — built.** With a premise in this record's Context corrected first: the
  four visualizers were **not** workspace packages. `pnpm-workspace.yaml` listed `packages/*`, which
  does not recurse, so each was installed standalone — which is why each had a lockfile — and their
  `vite.config.ts` wrote into `packages/web/public/visualizers/`, a directory ADR-0092 point 1
  deleted. A source change here had no path to the document `familiar-apple` ships. By point:
  1. `packages/visualizer-sdk` (`@familiar/visualizer-sdk`): the bridge (`familiar.ts`), the types,
     `FrameScheduler`, `usePalette`/`useArtworkPalette`, `AudioReactiveEffects`, and a `feature()`
     accessor. All six were used by all four documents; nothing else moved.
  2. A `workspace:*` dependency of each visualizer; each still builds an IIFE into its own `dist/`.
  3. `docs/VISUALIZER_API.md` gains an SDK section *after* the protocol, headed "one path, not the
     contract".
  4. `src/fixtures/events.ts` holds the recorded shapes (the ones `familiar-apple`'s contract spec
     posts, plus older/newer-host variants and nine malformed ones); `familiar.test.ts` drives the
     bridge with them; `packages/visualizers/e2e/documents.spec.ts` loads each built document in a
     sandboxed frame, feeds the same events, and requires the handshake, a canvas, live
     `familiar:stats` frames and no uncaught error. Both run in CI. The bridge now drops malformed
     messages instead of throwing inside the listener, and ignores — once, loudly — an `apiVersion`
     it does not speak.
  5. Scene code, `useLyricTiming`, `analysisMetrics` and every `.tsx` scene stayed local.
  6. `pnpm-workspace.yaml` adds `packages/visualizers/*`; the four lockfiles are deleted; `three` is
     one version across the workspace (`^0.182`, from `^0.180` in the visualizers — they had drifted
     from the frontend unnoticed).
  7. The two documents in `packages/visualizers/examples/` are untouched and named in the doc.
  Found by giving the packages a `tsc` for the first time: `reactive-terrain` imported a
  `TrackFeatures` type nothing exported, and `lyrics` imported `LyricLine` from `../../../api` — a
  path into `packages/frontend` that does not resolve. Vite strips type imports without looking, so
  both shipped. Each visualizer now has a `typecheck` script, run in CI.
  **`familiar-apple` half:** `scripts/build-visualizers.sh`, the counterpart of
  `build-visualizer.sh`, vendors each `dist/` into `App/Shared/Visualizers.bundle/<id>/`.

## Context

The four source-built visualizers under `packages/visualizers/` — `beat-tiles`, `lyric-storm`, `lyrics`
and `reactive-terrain` — are separate workspace packages, but each carries byte-identical copies of the
host bridge (`familiar.ts`), event types (`types.ts`), artwork palette extraction (`colorExtraction.ts`),
audio-reactive effects (`AudioReactiveEffects.tsx`), frame scheduling (`FrameScheduler.tsx`) and an artwork
hook (`useArtworkPalette.ts`). The six repeated files are 613 lines per package, about 2,450 across the
four. All four also carry their own `pnpm-lock.yaml` and overlapping dependency declarations.

Two dependency-free single-file visualizers already exist beside them in `packages/visualizers/examples/`
(`lyric-pulse`, `non-places`). They are the proof that a document needs nothing from the SDK, and this
record leaves them as they are.

Copying made the first document self-contained quickly. At four documents it creates a false public
contract: an author may copy whichever visualizer they find first, fixes must be applied four times, and a
partial update can make first-party documents interpret the same host event differently.

ADR-0087 rejected a runtime sharing mechanism because a visualizer must not depend on libraries lent by
the host. A source package used at build time is a different boundary: the resulting document still bundles
what it uses and can run independently in the sandbox.

## Decision

1. **A workspace package named `@familiar/visualizer-sdk` owns shared authoring code.** It contains the
   typed event bridge, payload types, frame scheduler and generally useful hooks/utilities proven by at
   least two visualizers.

2. **The SDK is a build-time dependency.** Every visualizer bundles the imported code into its own output.
   The host serves no shared JavaScript, injects no libraries and promises no package version at runtime.

3. **The event protocol remains the public contract.** The SDK is a convenience implementation of
   `familiar:track`, `familiar:audio`, `familiar:state` and `familiar:ready`, not the normative definition.
   A vanilla JavaScript document remains a complete supported visualizer.

4. **Protocol fixtures and compatibility tests live with the SDK.** Each first-party visualizer is tested
   against the same recorded event shapes, version negotiation and malformed-message behavior.

5. **Only demonstrated common behavior enters the package.** Scene components, visual style and helpers
   used by one document stay local. Similar-looking code is not generalized in anticipation of reuse.

6. **Package versions are pinned by the workspace lock.** Per-visualizer lockfiles leave unless a
   visualizer is intentionally published as an independently reproducible example, in which case its
   release process records how it tracks the SDK.

7. **External authors may use the SDK but are not required to.** Documentation starts with the protocol
   and offers the SDK as one authoring path.

## Alternatives Considered

**Keep copying so every source folder is standalone.** Rejected. Build output, not source duplication, is
the independence ADR-0087 requires.

**Load one SDK script from the host at runtime.** Rejected by ADR-0087. It recreates a host-version contract
and makes documents dependent on the application that embeds them.

**Publish only types.** Better than four copies of the payload interface, but rejected as the full answer:
the bridge and scheduling code are the largest repeated behavior and the easiest place for implementations
to diverge.

**Merge all visualizers into one application.** Rejected. Separate documents are the isolation and
distribution unit, not an incidental build arrangement.

## Consequences

- **Positive:** roughly 2,450 repeated source lines gain one implementation and one test surface.
- **Positive:** a new first-party visualizer begins with the protocol already handled.
- **Positive:** self-contained sandboxed output and framework independence remain unchanged.
- **Tradeoff:** source packages are coupled to a workspace dependency during development.
- **Tradeoff:** a breaking SDK refactor can require rebuilding all first-party visualizers even when the
  wire protocol did not change.
- **Follow-up:** the documentation shows both paths side by side: one of the four SDK-based visualizers and
  one of the two dependency-free examples in `packages/visualizers/examples/`. The second path needs no new
  code; it needs to be presented first.

