# ADR-0065: The App Seeds the Drop-In Folder With Worked Examples

Status: superseded by [ADR-0089](ADR-0089-the-app-bundle-seeds-the-folder-and-is-not-a-source.md)

Date: 2026-08-18

Superseded 2026-08-29. **The idea shipped; this ADR's version of it did not, and should not.**

`ADR-0089` decided the same thing in a stronger form two days after this was written, and points 1
through 4 of it are built: `App/Shared/Visualizers.bundle/` ships **five** visualizers as real
folders — `beat-tiles`, `lyric-storm`, `lyrics`, `reactive-terrain`, `spectrum` — and
`VisualizerPlugins.seed(marker:)` copies them into the drop-in folder once, with `restore` beside
it. This ADR is not discarded so much as absorbed: `VisualizerPlugins.swift:167` cites **"`ADR-0065`
point 2's reasoning, inherited"** for seeding once, ever. That point was right and is why the code
reads the way it does.

What did not survive is the *shape*, and it could not have. `ADR-0087` had already redefined a
visualizer as **a folder with an `index.html`**, sandboxed at an opaque origin and driven by
`postMessage`. Both examples here are the form that replaced: `"main": "dist/index.js"`, built from
JSX, requiring the host to supply `React` and a `jsx`/`jsxs` shim. **There is no host-provided React
in a document.** So point 6's vendoring of `non-places`, point 4's choice of which two examples, and
point 5's `affinity` corrections are all answers to a question `0087` stopped asking.

The implementation branch `adr/ship-example-visualizers` (`familiar-apple`, PR #129, closed
2026-08-25) is two commits of dead code carrying `ExampleVisualizer-non-places.js`/`.json` as flat
pairs reconstructed at runtime, plus a second "Restore" button duplicating `0089`'s. **It should be
deleted along with its worktree at `/Users/jeff/Developer/familiar-apple-examples`.**

The lesson worth keeping: this sat `proposed` for eleven days while the ground moved under it twice
(`0087`, then `0088`/`0089`). A proposal that is not executed promptly is not held in amber — and
nothing flagged the conflict. The PR review caught it, which is late but not too late.

Extends [ADR-0034](ADR-0034-visualizers-are-drop-in-bundles.md) and supersedes the last sentence of
its point 4 — "There is no third source in this ADR." There still is not: what follows is not a new
place bundles are loaded from, it is the app putting something in a place that already existed. The
rest of point 4, including which directory each platform uses, stands unchanged.

## Context

**The drop-in path has never run on a real install.** `VisualizerPlugins.shippedDirectory()` looks
for a `Visualizers` folder in the app bundle and the built app contains none, so it returns nil;
the local folder — `~/Library/Application Support/Familiar/Visualizers` on this machine, created
2026-08-11 — is empty. Every plugin verdict this project has produced has come from a test fixture
or from a sibling directory pointed at by hand.

**An empty folder behind a button reads as broken**, and that is what prompted this: Settings
reveals the folder, the folder contains nothing, and the five visualizers in the menu are compiled
into the page rather than files. Nothing about that is wrong and nothing explains it either. It is
the same shape this surface keeps producing — `ADR-0034` point 3 called it an affordance whose
destination is not mounted — arriving one layer further out, in a directory rather than a menu.

**Three samples exist as sibling directories, and they are not equivalent.** Checked rather than
remembered, on 2026-08-18:

| | `type` | `apiVersion` | version control | `dist/` |
|---|---|---|---|---|
| `familiar-plugin-lyric-pulse` | `visualizer` | 1 | public repo | 8 KB |
| `familiar-plugin-non-places` | `visualizer` | 1 | **none, anywhere** | 16 KB |
| `familiar-plugin-timeline` | `browser` | 1 | public repo | 12 KB |

Two things follow. `timeline` is a library browser, which `ADR-0034` point 9 excludes and the loader
refuses — it is not an example of anything a person should copy. And `non-places` is the one sample
that exercises the shared three.js globals, which is to say the only evidence for the half of
`ADR-0034` point 3 that nothing enforces — and it exists in exactly one place, on one disk, with no
repository. `ADR-0034` recorded that as a tradeoff and it has been true for twelve days.

**None of the three declares `affinity`.** They were written before
[ADR-0064](ADR-0064-visualizers-declare-affinity-and-the-server-ranks-them.md), so seeded unchanged
they would teach the API as it was — an example that omits the newest part of a contract is worse
than no example, because it is read as the current shape.

**This is not what [ADR-0063](ADR-0063-the-visualizer-api-is-published-for-outside-authors.md) point
7 decided.** That names a template repository an author clones, and it stands: it is for someone who
has decided to write a visualizer and wants a project that builds. This is for someone who opened
the folder to find out what a plugin *is*. Different moment, different artefact, and the second one
has to be readable without a network or a decision.

## Decision

1. **The app ships worked examples in its bundle and copies them into the drop-in folder.** They
   become ordinary local plugins the moment they land — the loader cannot tell them from anything
   else the user put there, and nothing marks them as special afterwards.

2. **Seeded once, ever — automatically.** A marker records that seeding has happened; after that
   the folder belongs to the user. Deleting an example means the user meant to delete it, and it
   does not come back on its own. The alternative — re-seeding whatever is missing — makes an
   example impossible to remove and silently overwrites one that has been edited, which is the more
   likely use for it.

3. **Restoring is explicit, and lives in Settings beside the button that reveals the folder.**
   "Restore Example Visualizers" writes the examples again and resets the marker. This is what makes
   point 2 safe rather than a trap: automatic seeding happens once so it cannot overwrite anyone's
   work, and a deliberate action is available for the person who deleted an example and wants it
   back, or who edited one past repair.

   **It overwrites by id, and says so before it does.** A restore that silently replaced an edited
   example would be the destruction point 2 refuses, arriving by a different route — so the button
   names what it will overwrite, and anything in the folder that is not one of the shipped examples
   is left alone.

4. **The examples are the two visualizers, not the browser.** `timeline` is refused by the loader
   under `ADR-0034` point 9, and an example that cannot load teaches the wrong lesson in the wrong
   place. The refusal display has a real artefact to exercise whenever someone drops `timeline` in
   themselves; it does not need to ship broken to prove the point.

5. **The examples declare `affinity`, and are corrected to the current contract before shipping.**
   Neither sample declares one today — both were written before `ADR-0064` — so their manifests are
   edited as part of this, not shipped as found. An example is documentation that executes: shipping
   one that predates the current contract teaches the previous shape of the manifest to every author
   who reads it, which is the failure `ADR-0063` point 2 exists to prevent, arriving in the artefact
   rather than the document.

   The declarations have to be *true of the visualizer*, not decorative. `lyric-pulse` draws the
   current lyric, so it suits music with singing on it; `non-places` drifts models through fog, so
   it suits the calm and the spacious. An example whose affinity does not describe it teaches
   authors to fill the field in with anything.

6. **`non-places` is vendored into `familiar-apple`**, which is the first time it will exist under
   version control. This is a side effect of the decision and also the strongest argument for it:
   the only sample that exercises the shared three.js contract currently survives on one disk.

7. **A seeded example is not a supported artefact.** It is a starting point, and the app makes no
   promise to update it, migrate it, or keep it working across an `apiVersion` bump. When it stops
   loading, the picker says so with a reason like any other refused plugin — which is exactly the
   lesson an author needs.

## Alternatives Considered

- **Ship them as `shipped` plugins instead, in the app bundle's `Visualizers` directory.** The
  machinery already exists — `shippedDirectory()` is written, tested, and returns nil only because
  the directory is absent — so this is nearly free, and it puts working plugins in the menu without
  writing anything to the user's disk. Rejected because a shipped bundle is inside a code-signed app
  the user cannot open, so it can be run but not read or copied. The ask is for examples, and an
  example you cannot look at is not one.

- **Re-seed anything missing on every launch.** No stored state, and the folder always contains
  working examples. Rejected on point 2's grounds, and answered by point 3: it makes deletion impossible and would overwrite
  an example the user had edited into their own plugin — destroying work in the one directory this
  feature invites people to work in.

- **Seed per bundle version, so an app update brings updated examples.** Genuinely attractive:
  point 5's concern is that examples go stale, and this is the mechanism that would fix it.
  Rejected because it resurrects deleted examples at every upgrade, which is the same failure as
  re-seeding, spread thinner and harder to attribute.

- **Leave the folder empty and explain it — a README in the folder, or a line in Settings.** The
  cheapest honest answer, and it removes the "reads as broken" problem without shipping anything.
  Rejected because it answers the question and does not serve the purpose: someone opening that
  folder wants to see the shape of a plugin, and a paragraph describing one is what
  `docs/VISUALIZER_API.md` already is.

- **Point at the template repository from `ADR-0063` point 7 instead.** No duplication, and the
  template is the thing that actually builds. Rejected as the wrong moment — it needs a network, a
  clone, and a decision to write one, and the folder is where somebody looks *before* any of that.

## Consequences

- **Positive:** The drop-in path runs on a real install for the first time. Every verdict this
  loader has produced so far came from a fixture or a directory pointed at by hand.
- **Positive:** `non-places` acquires version control, closing a tradeoff `ADR-0034` recorded and
  could not fix from where it stood.
- **Positive:** The folder explains itself. Opening it shows what a plugin is made of — a manifest
  and a built bundle — which is what the button revealing it implies.
- **Tradeoff:** **The folder is inside the app's sandbox container**, and its path is not the one
  anybody would guess. The Mac app declares `com.apple.security.app-sandbox`, so the Application
  Support directory `ADR-0034` point 4 names resolves to
  `~/Library/Containers/com.familiar.player/Data/Library/Application Support/Familiar/Visualizers`.
  A plain `~/Library/Application Support/Familiar/Visualizers` also exists on this machine, is
  empty, and is not the one the app reads — which is exactly how "I put a plugin in the folder and
  nothing happened" would arrive. Settings shows the real path and its button opens the real place,
  so the only way to be misled is to navigate there by hand, which is what happened while this was
  being written.

- **Tradeoff:** The app bundle grows by the examples. Measured today they are 24 KB of `dist/` plus
  two manifests, against a 3.3 MB visualizer document and a 72 MB app, so the cost is nil — but it
  is a cost that grows with every example added, and nothing is watching it.
- **Tradeoff:** Point 2's marker is stored state that has to be right. If it is written before the
  copy succeeds, a user who never got the examples never will — and point 3's restore is what keeps
  that from being permanent, which is a second reason it earns its place. A lost marker is the
  milder failure: the examples reappear, which is the outcome the button offers anyway.
- **Tradeoff:** Examples now need maintaining. Point 5 fixes them once, at a moment when the
  contract has just changed; nothing keeps them current afterwards, and a stale example is read as
  the current shape.
- **Tradeoff:** Point 3 puts a destructive action in Settings. It overwrites by id, and the ids it
  overwrites are the shipped ones — but a user who renamed an example's folder while keeping its id
  gets it replaced anyway, and no wording on a button fully prevents that.
- **Follow-up:** `familiar-plugin-lyric-pulse` and `familiar-plugin-timeline` remain public
  repositories whose READMEs describe a "Settings > Plugins" screen deleted on 2026-03-06.
  `ADR-0034` flagged this and `ADR-0063` point 2 requires it fixed before publication; vendoring a
  corrected copy does not correct the originals.
- **Follow-up:** Whether the iPhone seeds too. `ADR-0034` point 4 puts iOS in `Documents/Visualizers`
  precisely so the Files app can reach it, so the same argument applies — but the phone has no
  Settings row revealing the folder today, so nothing there reads as broken yet.
