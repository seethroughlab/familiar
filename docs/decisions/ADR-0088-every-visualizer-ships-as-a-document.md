# ADR-0088: Every Visualizer Ships as a Document

Status: accepted

Date: 2026-08-20

Supersedes [ADR-0087](ADR-0087-a-visualizer-is-a-document-not-a-component.md) point 8, and closes
the question its point 7 left open.

## Context

`ADR-0087` made a visualizer a folder with an `index.html` and removed every sharing mechanism, so
a plugin carries its own libraries. Two of its points then had to say what happens to the five that
exist today, and they said different amounts:

- **Point 7** left the disposition open — the r3f built-ins are "rewritten as self-contained
  documents, demoted to optional drop-ins, or dropped — a question for whoever does the work".
- **Point 8** answered the resulting bundle-size problem by shrinking the shipped set: "one or two
  cheap ones that prove the contract and give a fresh install something to look at. Anything
  heavier is something a listener installs."

Point 8 is the one that turns out to be wrong, and the reason is that it optimises the wrong thing.
It trades **what a fresh install can do** against megabytes, in an application that already ships a
3.2 MB visualizer document and whose library is measured in tens of gigabytes of audio. A listener
who opens the visualizer and finds one scene has lost something real; the disk it would have cost is
not something they were counting.

It also leaves the codebase with two categories — shipped and "demoted to a drop-in" — which is the
distinction `ADR-0068` was written to remove and which `ADR-0087` point 7's "one shape, not two" is
otherwise careful about.

## Decision

1. **Every visualizer is converted to a document and all of them ship.** Nothing is demoted to a
   drop-in and nothing is dropped.

   **That is four built-ins plus `spectrum`, and it does not include music video.** `ADR-0066`
   point 2 already removes `music-video` from the registry — *"Four built-ins remain:
   `reactive-terrain`, `beat-tiles`, `lyrics` and `lyric-storm`"* — and `ADR-0085` makes it a native
   Mac player mode instead. It is spelled out because the registry in the code still lists it, so
   anything counting the current state gets five and includes the one that is leaving.

2. **The duplication is accepted rather than engineered around.** Three of them are
   `@react-three/fiber` scenes, so three folders each carry their own THREE. That is the cost of
   `ADR-0087` point 7's refusal of a sharing mechanism, and paying it in disk is the point of having
   refused: a shared library is a version contract, and this is only bytes.

3. **A shipped visualizer is a plugin in every respect.** Same folder layout, same manifest, same
   events, loaded the same way. The only difference is where the folder comes from — the app bundle
   rather than the user's directory — which is `ADR-0034` point 4's existing distinction and needs
   nothing new.

   > **Superseded by [ADR-0089](ADR-0089-the-app-bundle-seeds-the-folder-and-is-not-a-source.md).**
   > "Needs nothing new" did not hold: keeping the app bundle as a *runtime source* broke the Xcode
   > build, stranded the user's drop-ins when the app was sandboxed, and left the picker showing
   > visualizers that are not in the folder the Settings panel names. The bundle now seeds the folder
   > and is read by nothing else, so points 1, 2 and 4 stand and this one is how they ship.

4. **Per-plugin builds are expected to tree-shake better than the shared bundle did**, since each
   visualizer imports the part of THREE it actually uses rather than sharing one build sized for all
   of them. This is a reason the cost may be smaller than three times the current figure, not a
   requirement — if it does not hold, point 2 still stands.

## Alternatives Considered

**Keep `ADR-0087` point 8 as written — ship one or two.** Smallest bundle, and it is what that ADR
decided a few hours earlier. Rejected because it makes a fresh install worse to look at in order to
save space nobody is short of, and because "which two" is a question with no good answer that does
not amount to deleting working visualizers.

**Ship one and seed the rest into the drop-in folder on first launch**, the way `ADR-0065` seeds
examples. This keeps the app bundle small while a fresh install still has five. Rejected as a
distinction without a difference that costs a mechanism: the bytes land on the same disk either way,
and it makes five visualizers editable-and-breakable by accident when the user never asked to edit
them.

**Reintroduce a shared THREE for shipped visualizers only.** The bundle-size problem disappears and
only first-party code depends on it. Rejected because it is `ADR-0087`'s rejected sharing hatch with
a smaller blast radius — the version contract comes back, and the first drop-in that wants a
different THREE finds out what "shipped visualizers are special" means.

## Consequences

- **Positive** — one shape, with no second category. A shipped visualizer and a drop-in differ only
  in which directory they were found in.
- **Positive** — nothing is lost. `ADR-0087` was explicitly willing to drop visualizers to get a
  clean contract; it turns out not to be necessary.
- **Tradeoff** — the app bundle grows by roughly the size of two extra copies of THREE, before
  tree-shaking. This is the cost `ADR-0087` point 8 was avoiding, now paid deliberately.
- **Tradeoff** — five conversions instead of one, three of them r3f scenes that need their own build
  configuration (`reactive-terrain`, `beat-tiles`, `lyric-storm`). That is the bulk of the work `ADR-0087` implies, and it now all has to happen
  before the registry can be deleted.
- **Follow-up** — measure the built folders. If tree-shaking does not materially help, point 4's
  optimism should be struck so the next reader does not repeat it.
