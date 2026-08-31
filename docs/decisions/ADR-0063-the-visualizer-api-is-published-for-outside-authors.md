# ADR-0063: The Visualizer API Is Published for Outside Authors

Status: superseded by
[ADR-0103](ADR-0103-the-visualizer-contract-is-published-with-a-gallery.md)

Date: 2026-08-17

Extends [ADR-0034](ADR-0034-visualizers-are-drop-in-bundles.md), which decided what a visualizer
*is* and how a client loads one. That format, its two sources and its refusal rules all stand. This
decides who the contract is written for and where it is read, which `0034` did not address.
Depends on [ADR-0069](ADR-0069-the-site-adopts-a-static-site-generator.md) for the rendering.

## Context

[ADR-0033](ADR-0033-the-embed-bridge-gains-a-return-channel.md) stated the ambition plainly: the
visualizer is *"the one place in Familiar where someone outside this repository can add
something"*, and its argument for embedding rather than rebuilding natively was that otherwise
*"the reward for writing one is that it runs in the place nobody listens"*. `ADR-0034` then built
the loader, and it shipped in both repositories.

**So the machinery exists and the invitation does not.** `0034` verified the fact that makes this
worth doing rather than assumed it: *"No third party has written one, and there is no ecosystem to
strand."* The three sample plugins on disk — `familiar-plugin-lyric-pulse`,
`familiar-plugin-non-places`, `familiar-plugin-timeline` — are this project's own, all declaring an
`author.url` pointing at an unrelated account. Two years of plugin machinery has zero outside
authors, and the reason is not that the API is bad. It is that nobody outside this repository has
been told it exists.

**The contract is already written, is already shared, and is already wrong in three checkable
ways.** `docs/VISUALIZER_API.md` is 719 lines, and `0034` point 6 made it the contract for every
client rather than a web-app document. Audited against the repository on 2026-08-17:

- Its "Existing Visualizers" table lists seven components, of which **six do not exist**:
  `CosmicOrb`, `FrequencyBars`, `AlbumKaleidoscope`, `ColorFlow`, `LyricPulse` and
  `TypographyWave`. Only `LyricStorm` is real. The registry actually holds five ids —
  `reactive-terrain`, `beat-tiles`, `lyrics`, `music-video` and `lyric-storm`, registered in
  `components/Visualizer/visualizers/index.ts`.
- It describes `useAudioAnalyser` as reading a Web Audio `AnalyserNode`. Under `ADR-0033` that is
  one of three sources, the other two being native frames and nothing at all. `0034` recorded this
  as a follow-up and it is still open.
- All three sample plugins' READMEs instruct the reader to *"Go to Settings > Plugins"*, a screen
  deleted in `dbdef05` on 2026-03-06. `0034` flagged this as an unresolved tradeoff and predicted
  it would otherwise become another instance of an affordance pointing at a destination that is not
  mounted. It has been one for eleven days.

The first of these is the dangerous one. A stale table inside a repository is a nuisance; the same
table published as the invitation to write a visualizer sends every new author looking for six
components that were deleted, and the API's first impression is that nobody maintains it.

**Distribution is where this could go wrong, and `0034` already drew the lines.** Point 5 deferred
install-from-URL — *"a `plugins` table, a server route, a download path and a trust question about
arbitrary JavaScript from a URL"* — and its Alternatives separately rejected serving bundles from
the Familiar server, on the grounds that it is install-from-URL with the URL fixed. `ADR-0038`
point 7 refuses growth into a service. A gallery that *hosts bundles* would walk into all three at
once. A gallery that *lists and links* walks into none of them, and that is the difference this ADR
turns on.

## Decision

1. **`docs/VISUALIZER_API.md` becomes a published, versioned contract, rendered as a section of the
   site under `ADR-0069`.** It is already the shared contract for every client per `0034` point 6.
   Publishing changes who it is addressed to, not what it says, and the document stays in `docs/`
   as its single source — `0069` point 2 renders it in place rather than copying it.

2. **It is corrected before it is published, and the correction is part of this work rather than a
   follow-up.** All three defects in the Context: the six absent components, `useAudioAnalyser`'s
   three sources, and the sample READMEs' dead install instructions. This is `ADR-0055` point 2's
   rule applied one directory over — a claim nobody re-reads becomes a lie by attrition, and the
   moment a document is published, the number of people who cannot check it goes up sharply.

3. **A gallery page lists submitted visualizers and links to their repositories. The site hosts no
   bundles.** Discovery is the problem being solved; installation is unchanged and remains the
   `Visualizers/` directory of `0034` point 4. This is what keeps a gallery clear of `0034` point
   5's deferred trust question, clear of its rejected server-served-bundles alternative, and clear
   of `ADR-0038` point 7. **Familiar links to third-party code; it does not distribute it.**

4. **Submission is a pull request against a data file in `site/`, and curation is review of that
   pull request.** No accounts, no upload endpoint, no submission form, no moderation queue — each
   of those is the service `ADR-0038` point 7 refuses, and a project with zero third-party
   visualizers does not need a workflow. A pull request also means every listing arrives with an
   author who has a GitHub identity, which is the whole of the trust model and is stated as such.

5. **A listing states what can be checked, and is checked.** An entry carries an author, a
   repository URL, a licence and a declared `familiar.apiVersion`; an entry whose repository has no
   `familiar-plugin.json` with `"type": "visualizer"` is not listed. This is mechanical on purpose.
   `ADR-0055` point 2 found that a comparison table audited only against its own author's
   repository drifts toward flattering its author, and a curated gallery has the same failure mode
   with someone else's work.

6. **`familiar.apiVersion` is the compatibility promise, and publishing creates an obligation
   `0034` did not have.** The host implements version 1 (`VISUALIZER_API_VERSION` in
   `services/visualizerPlugins.ts`), and `0034` point 7 refuses any manifest declaring a version the
   host does not implement — including, as implemented, a manifest declaring none. Until now that
   only ever refused first-party samples. Once outside authors exist, a bump breaks strangers'
   work, so a bump requires the host to keep accepting the previous version for a stated period, and
   the gallery to record which entries are affected.

7. **The published starting point is a template repository an author clones, not a directory inside
   this one.** `visualizers/_template/` holds a 166-line `ExampleVisualizer.tsx` and a 271-line
   README, and it is good; but it lives inside the frontend package, cannot be cloned, and builds
   nothing. An author needs a manifest, a rollup config producing an IIFE, and a `dist/` — which is
   what the three sample plugins have and what `_template/` does not. `familiar-plugin-lyric-pulse`
   is the working reference for that shape.

8. **Install-from-URL stays deferred.** Restated here so that a gallery is not read as having
   settled it. `0034` point 5's reasoning is untouched by anything in this ADR: a list of links is
   not a download path, and the trust question it names still deserves its own argument.

9. **Library-browser plugins stay out of scope**, per `0034` point 9. `familiar-plugin-timeline`
   declares `"type": "browser"` and is refused by the loader; the gallery lists visualizers, so it
   is not listed either. Publishing an invitation is exactly the moment this boundary would blur.

## Alternatives Considered

- **Revive install-from-URL alongside the gallery, so a listed visualizer installs in one click.**
  It is what all three sample READMEs already tell people to do, and the shelved implementation is
  the starting point — `backend/app/services/plugins.py` (480 lines), `api/plugins.ts` (100) and
  `PluginsSettings.tsx` (378), all removed in `dbdef05`. Rejected for the reason `0034` point 5
  gave and did not retract: downloading and executing JavaScript from a URL the user supplied is a
  trust decision, and it should be argued on its own rather than arriving as the convenience half
  of a documentation change.

- **Host the bundles on the site so installation is a single download.** Removes the worst friction
  in the whole feature, and the files are small. Rejected because it makes Familiar the distributor
  of third-party code — the point at which a listing stops being a link and starts being an
  endorsement backed by nothing, and the point `ADR-0038` point 7 draws.

- **Publish the docs and skip the gallery; let GitHub topics and search do discovery.** Cheaper,
  self-maintaining, and it is how most projects this size handle it. Rejected because discovery by
  search requires something to find: with zero third-party visualizers, a topic tag returns the
  three first-party samples and nothing else. A curated list is the invitation, and it can be
  retired once it is no longer the only way to find anything.

- **Put the documentation in the web app as a `/docs` route.** The bundle already serves three
  documents and the routing exists. Rejected against `ADR-0058` point 2's three destinations, and
  because documentation that requires a running Familiar server is unreachable by exactly the
  person who has not installed one yet.

- **Write a new authoring guide rather than publishing the existing document.** The existing one is
  719 lines aimed at someone reading the repository. Rejected because two documents describing one
  contract is the drift `0069` point 2 refuses, and because the existing document's problem is that
  three specific things in it are wrong, not that it is the wrong document.

## Consequences

- **Positive:** The plugin surface that `ADR-0033` called the one place outsiders can contribute
  becomes reachable by an outsider, which is the first time that has been true since the loader
  shipped.
- **Positive:** Three known-stale artefacts get corrected under point 2, including one — the sample
  READMEs — that `0034` predicted would rot and which has.
- **Positive:** The gallery is a data file and a page. If nobody submits anything, the cost is a
  page that lists the first-party samples, which is still better than today.
- **Tradeoff:** Point 6 turns `apiVersion` from an internal check into a promise to strangers.
  Version 1 is now expensive to leave, and it was designed without anyone outside this repository
  in mind.
- **Tradeoff:** Curation is a person, and that person is one person. A submission queue with no
  reviewer is worse than no queue, and this ADR creates the queue without creating a second
  reviewer.
- **Tradeoff:** The site gains two audiences. `ADR-0055` point 1 says it exists *"to get one kind of
  person to run one command"*, and an author looking for a plugin API is a second kind. The
  documentation and gallery are their own pages, so `0055` point 4's budget of six claims and 700
  words in `<main>` is untouched — but the nav is where the two audiences meet, and a developer link
  there is the first thing on that page that is not aimed at the installer.
- **Tradeoff:** Point 3 means installation stays manual — find a repository, download a build, drop
  a folder in a directory a Settings button reveals. That is real friction on the exact path this
  ADR is trying to open, and point 8 declines to fix it.
- **Tradeoff:** A published contract makes `ADR-0034` point 3's unenforceable rule — that a bundle
  must not carry its own React or three.js — a support burden rather than a note. Nothing checks
  it, and now the people breaking it will not be in this repository.
- **Follow-up:** Install-from-URL, per point 8 and `0034` point 5. This ADR raises its value
  without changing its argument.
- **Follow-up:** `visualizers/_template/` is superseded as the published starting point by point 7,
  but still exists and still documents the component API accurately. Decide whether it stays as an
  in-repo reference or is folded into the template repository.
- **Follow-up:** The gallery's per-entry checks in point 5 are described but not automated. Until
  they are, they are a reviewer's checklist — which `ADR-0055` point 2 observed is the form of audit
  that has already expired.
