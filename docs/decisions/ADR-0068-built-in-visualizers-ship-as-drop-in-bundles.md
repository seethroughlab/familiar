# ADR-0068: Built-In Visualizers Ship as Drop-In Bundles

Status: proposed

Date: 2026-08-18

Supersedes [ADR-0034](ADR-0034-visualizers-are-drop-in-bundles.md) point 2 of its Implementation
block — "a plugin claiming a built-in id is refused, not allowed to shadow it". The rest of `0034`
stands. Depends on
[ADR-0067](ADR-0067-the-plugin-api-exposes-what-a-first-party-visualizer-uses.md), and reads better
after [ADR-0066](ADR-0066-music-video-is-a-player-mode-not-a-visualizer.md) has removed the entry
that could not be converted.

## Context

**The ask is that every visualizer be readable and editable on disk**, not only the ones somebody
dropped in. Today the drop-in folder holds what
[ADR-0065](ADR-0065-the-app-seeds-the-drop-in-folder-with-worked-examples.md) seeds — two sample
plugins — while the visualizers people actually watch are React components compiled into
`VisualizerBundle.html`. Opening the folder shows two things and the menu shows six, and the four
that are missing are the good ones.

**Two constraints shape every answer, and neither is negotiable.**

*The browser has no drop-in **folder** — but that is not the same as having no plugins, and the
first version of this ADR conflated the two.* `discover()` fetches `plugins/index.json` with
`new URL(path, window.location.href)`, which is **the document's own origin**. On the Apple clients
that is the app bundle, served by `VisualizerSchemeHandler` — whose own comment says it serves "the
visualizer document out of the app bundle, and the drop-in plugins beside it". In a browser it is
the web app's origin, where nothing is published, so the fetch 404s and `discover()` returns null.

That is a missing *file*, not a missing capability. If the web build emits the same bundles as
static assets, discovery works in the browser with **no code change at all**. `ADR-0034` point 4
already names the two sources this needs — shipped and local — and the browser simply has the first
and not the second.

**The rejected premise mattered**, because it is what the first version of this ADR used to justify
keeping a compiled copy of every visualizer alongside the drop-in one. That would have meant each
visualizer shipping twice, built two ways, with nothing checking the two stayed in step.

*Shadowing is currently refused, for a reason that still holds.* `ADR-0034`'s Implementation records
it: `registerVisualizer` overwrites by id and `visualizerRegistry` has no removal, so a plugin
claiming `lyrics` would make the built-in unrecoverable short of deleting the file. That is a fact
about the registry, not about the desirability of shadowing — and it is fixable.

**Together they point at one shape.** The built-ins stay compiled in, so every client always has
them; a local copy with the same id *replaces* the compiled one while it is present, and removing
the folder gets the original back. Editing `reactive-terrain` on disk then really does change what
draws, which is what "editable sources" has to mean to be worth anything.

**`music-video` is not among the four.** `ADR-0066` moves it out of the visualizer set, which is
convenient here and was decided on its own grounds: it would have been the one conversion requiring
playback state and network access in a public plugin API.

## Decision

1. **The four built-ins are also built as standalone IIFE bundles and shipped as examples**, in the
   format `ADR-0034` point 1 defines and against the globals `ADR-0067` exposes. They are the same
   source, built a second way — not a copy maintained by hand, which would diverge within a month.

2. **A local plugin may claim a built-in id, and wins while it is there.** This reverses `ADR-0034`'s
   refusal. The registry gains removal, or registration is ordered so the compile-time set is
   re-registered when a local copy disappears; either way the invariant is that **deleting the
   folder restores the original**, and that is what makes the reversal safe where it was not before.

3. **Each visualizer is built once and shipped once.** There is no compiled copy kept alongside the
   drop-in one: the IIFE bundle is the artefact, and the platforms differ only in how it is
   delivered — from the app bundle over the custom scheme on the Apple clients, and as a static
   asset on the web app's own origin in a browser. Both are the `shipped` source `ADR-0034` point 4
   already defines.

   **This is the point of the exercise.** Two builds of one visualizer would drift, and nothing in
   CI could see it: the app would quietly draw last week's scene while the source said otherwise.

4. **A shadowed built-in is visible as shadowed.** The picker already has the vocabulary:
   `ADR-0034`'s Implementation made a shipped bundle losing to a local one report as `shadowed`
   rather than vanish. The same wording applies here, so someone who edited `lyrics` on disk and
   broke it can see why the menu changed.

5. **Seeding follows `ADR-0065`.** These land in the same folder, by the same once-only copy, and
   "Restore Example Visualizers" restores them too. A built-in restored from Settings is byte-identical
   to the compiled one, which makes restore the way out of a broken edit.

6. **`docs/VISUALIZER_API.md` records the reversal, not just the new capability.** Its manifest
   table currently tells authors an id "must not be one of the built-ins", which point 2 makes
   false — and a document that forbids something the loader now permits is worse than one that is
   merely incomplete, because an author will believe it and pick a worse id. The reserved-id row
   changes, and the shadowing behaviour and its fallback are documented beside it.

7. **A broken local copy falls back to the shipped bundle of the same id.** `ADR-0034` point 8
   already unloads a visualizer that throws; the fallback here is the shipped copy rather than the
   album-art square, because one exists and is known good. That is what point 2's "delete the folder
   and get the original back" means in the case where the folder was not deleted but broken.

## Alternatives Considered

- **Ship the sources as read-only reference — the `.tsx` files, in the folder or beside it.** Much
  cheaper: no bundling, no shadowing, no registry change, and it answers "I want to see how this
  works" completely. Rejected because it does not answer "editable": a reader can change the file
  and nothing happens, which is a worse kind of confusion than an empty folder — it looks like it
  should work.

- **Keep a compiled copy of each visualizer alongside the drop-in one, as a floor.** This is what
  the first version of this ADR decided, on the belief that a browser could not load plugins at all.
  That belief was wrong — see the Context — and the cost was concrete: every visualizer built twice,
  by two toolchains, with nothing able to tell you they had diverged. Rejected once the premise was
  corrected. What it was protecting against is real but smaller than it looked, and point 3's
  tradeoff below states it plainly.

- **Move the built-ins out of the app entirely and load them only from the user's folder.** Distinct
  from point 3, which keeps them in the app bundle as the `shipped` source. Rejected because a fresh
  install would then depend on seeding having succeeded to have any visualizer at all, and
  `ADR-0065` deliberately seeds *once* — so a failed first launch would leave a permanently empty
  player with no way back except Settings.

- **Keep the reserved-id refusal and ship the copies under different ids** — `reactive-terrain-example`
  and so on. No registry change, no shadowing, no risk to the compiled set. Rejected because the
  menu would then list eight entries, four of them near-duplicates of the others, and editing the
  example still would not change what the original draws.

- **Let a local copy shadow, but only while a developer flag is set.** Confines the risk to people
  who asked for it. Rejected as a way of shipping a feature without deciding it: the flag would be
  the real interface, undocumented, and the failure mode is a user who edits a file and cannot work
  out why nothing changed.

## Consequences

- **Positive:** Every visualizer becomes readable and editable on disk, and editing one changes what
  draws. That is the request, met literally rather than approximately.
- **Positive:** The plugin path stops being a side entrance. The four visualizers people watch most
  would run through the same loader as a stranger's, which is the strongest guarantee that the
  loader keeps working — today it carries two samples nobody watches.
- **Positive:** The registry gains removal, which `ADR-0034` recorded as the reason shadowing was
  refused. That unblocks more than this ADR.
- **Tradeoff:** Each built-in needs a build config producing an IIFE against the shared globals, and
  a place in the app bundle. Four more artefacts to keep in step with their sources, and nothing
  fails loudly if one is stale — the app would simply run yesterday's `lyrics`.
- **Tradeoff:** Two ways to run the same visualizer, and the shadowing copy is the one users edit.
  A bug reproducible in one and not the other is a genuinely confusing report, and "delete the
  folder and try again" becomes a support answer.
- **Tradeoff:** Point 2 widens what third-party code can do: a dropped-in plugin can now replace a
  visualizer the user chose rather than only adding one. `ADR-0034` refused exactly this, and the
  mitigation is point 4's visibility rather than a restriction.
- **Positive:** The inlined visualizer document gets *smaller*, not larger. The four visualizers
  leave the page bundle and become separate artefacts fetched beside it, which is the opposite of
  what the first version of this ADR predicted.
- **Tradeoff:** **There is no longer a compiled floor.** If the shipped bundles cannot be read —
  a corrupt resource, a scheme handler that stops serving them — the player has no visualizers at
  all, where before it had four that could not fail independently of the app itself. The mitigation
  is that shipped bundles are read from the app bundle or the app's own origin, which is about as
  reliable as compiled code; the risk is not zero and is accepted deliberately.
- **Follow-up:** The web build has to emit `plugins/index.json` and the bundles as static assets, or
  the browser keeps 404ing and has no visualizers. Nothing in the page changes; this is a build
  output that does not exist yet, and it is the one piece of new machinery this decision needs.
- **Follow-up:** `ADR-0065` point 7 says a seeded example is not a supported artefact and may stop
  loading across an `apiVersion` bump. That is a comfortable thing to say about a sample and an
  uncomfortable one to say about `reactive-terrain`; point 3's compiled fallback is what makes it
  survivable, and the wording of both should be reconciled.
