# ADR-0103: The Visualizer Contract Is Published, With a Gallery

Status: proposed

Date: 2026-08-31

Supersedes [ADR-0063](ADR-0063-the-visualizer-api-is-published-for-outside-authors.md), whose
intent was right and whose foundations moved under it.

Extends [ADR-0087](ADR-0087-a-visualizer-is-a-document-not-a-component.md), which decided what a
visualizer *is* now, and [ADR-0089](ADR-0089-the-app-bundle-seeds-the-folder-and-is-not-a-source.md),
which decided where the shipped ones come from.

## Context

`ADR-0033` stated the ambition: someone outside this project should be able to write a visualizer.
Nothing has published the contract that would let them, and `ADR-0063` was written to fix that on
2026-08-17. It should not be implemented as written.

### What moved under ADR-0063

It opens by saying of `ADR-0034` that *"that format, its two sources and its refusal rules all
stand."* Neither half is true any more:

- **`ADR-0034` points 1 and 3 are superseded by `ADR-0087`.** A visualizer stopped being a component
  the host supplies React to, and became **a folder containing an `index.html`**, sandboxed at an
  opaque origin and driven by `postMessage`. `ADR-0063`'s point 3 anchors its gallery on "the
  `Visualizers/` directory of `0034` point 4" — a model that no longer describes anything.
- **`ADR-0034` point 4's two-source model is superseded by `ADR-0089`.** The app bundle seeds five
  visualizers into the drop-in folder once; it is not a second source.
- **`ADR-0091` and `ADR-0092`** moved visualizers and the document build out of this repository
  entirely. The server no longer serves them.
- It **depends on `ADR-0069`** for rendering — a static site generator that is still `proposed` and
  whose case has not improved. Making a gallery wait on a build-tool decision is a dependency worth
  removing rather than honouring.

None of that makes the idea wrong. It makes the ADR unimplementable as a set of instructions, which
is what an ADR is for.

### What is already true, and changes the work

**`docs/VISUALIZER_API.md` exists and is correct.** 9.3 KB, and it documents the current shape: the
folder, `"main": "index.html"`, the four events (`familiar:ready`, `:track`, `:state`, `:audio`),
`familiar.apiVersion`, and three named gotchas including the classic-script-not-module trap.
`ADR-0063`'s point 2 — "it is corrected before it is published" — has been done by other work in the
intervening two weeks. **The contract is written. It is simply not published.**

**There are five worked examples, and they are not on the site.** `beat-tiles`, `lyric-storm`,
`lyrics`, `reactive-terrain` and `spectrum` ship in `App/Shared/Visualizers.bundle/`, each with a
`familiar-plugin.json` carrying a name, description, author, icon and `apiVersion`. Nobody outside
the repository can see that they exist, what they look like, or that `spectrum` is "one file, no
build step, no libraries" — which is the single most persuasive fact about the format.

**The site has no generator and does not need one.** It is three hand-written HTML files plus one
JavaScript file, and `ADR-0095` deliberately kept it that way. `site/scripts/check-claims.py` audits
it, and since `ADR-0097` it fetches the deployed page rather than the working tree — because the live
site served an April build for four months while every check passed.

## Decision

1. **`docs/VISUALIZER_API.md` is published as a page on the site, and the file stays the source.**
   It is rendered into `site/visualizers.html` rather than rewritten there, so there is one contract
   and not two copies that drift. No static site generator: a small build step in the existing site
   tooling is enough, and `ADR-0069` is not a prerequisite for anything here.

2. **The gallery leads with the five visualizers Familiar ships.** This is where `ADR-0063` was
   wrong by omission: its gallery listed only third-party submissions, so it would have launched
   empty and stayed empty until strangers arrived. The shipped set is the worked-example set, it
   exists today, and `spectrum` — one file, no build step, no libraries — is the most convincing
   argument the format has.

3. **Third-party visualizers are listed alongside, and the site hosts no bundles.** `ADR-0063`
   point 3's rule is kept intact because it was right: **Familiar links to third-party code, it does
   not distribute it.** That keeps the gallery clear of `ADR-0034` point 5's deferred trust question
   and of the rejected server-served-bundles alternative.

4. **Submission is a pull request against a data file in `site/`.** Curation is reviewing that pull
   request. No submission form, no database, no moderation queue — the same mechanism the install
   panels use, and one that fails safe when nobody is looking at it.

5. **A listing states only what can be checked, and `check-claims.py` checks it.** Name, author,
   `apiVersion`, a link that resolves. Not "works great with electronic music". `ADR-0097`'s lesson
   is that a claim nobody re-reads becomes a lie by attrition, and the moment a page is published the
   number of people who cannot check it goes up sharply.

6. **`familiar.apiVersion` becomes a promise on publication, and the page says which version it
   documents.** `ADR-0087` point 9 made it version the *event contract*, which is a far smaller and
   more stable surface than the component API it used to version. Publishing turns it from an
   internal number into something outside authors depend on.

7. **Install-from-URL stays deferred**, restated from `ADR-0063` point 8 so that a gallery is not
   read as having settled it. A listing links to a repository; installation remains dropping a folder
   into `Visualizers/`.

8. **Library-browser plugins stay out of scope**, per `ADR-0034` point 9 and unchanged by `ADR-0087`.

## Alternatives Considered

- **Implement `ADR-0063` as written.** Cheapest in ceremony. Rejected because three of its
  load-bearing citations point at superseded decisions and one dependency is on an ADR that should
  probably be withdrawn — a reader following its instructions would build against a format that no
  longer exists.

- **Amend `ADR-0063` in place.** It is still `proposed`, so its Decision may be edited without a
  supersession. Rejected because the changes are not corrections but a change of shape: the gallery's
  contents change, its anchor changes, and a dependency is removed. `ADR-0063`'s own record — that
  its foundations moved within two weeks — is worth keeping legible rather than editing away.

- **Ship only the built-in gallery and defer third-party listings.** Genuinely tempting: it is useful
  on day one, needs no submissions, and needs no contract published. Rejected as the *decision*
  because it answers the smaller question — the point of `ADR-0033`'s ambition is people outside this
  project, and a gallery with no route in is a screenshot page. Point 2 sequences it first regardless,
  so nothing is lost by deciding both now.

- **Withdraw the idea until someone outside asks.** Defensible: nobody has requested this. Rejected
  because the causation runs the other way — nobody can ask for a contract they cannot read, and the
  contract is already written and correct. The cost of publishing what exists is a page.

- **Host submitted bundles on the site.** Would make installation one click instead of a folder copy.
  Rejected for the reason `ADR-0034` point 5 and `ADR-0063` point 3 both gave: distributing
  third-party executable code is a trust and review obligation this project has not decided to take
  on, and a gallery must not smuggle it in.

## Consequences

- **Positive** — the five shipped visualizers become visible to people who have not installed the
  app, which is the cheapest available argument that the format is simple.
- **Positive** — the contract stops being a file only contributors can find. It is already written
  and already correct, so the work is rendering rather than authoring.
- **Positive** — one source for the contract, so the site cannot drift from `docs/`. `ADR-0097` is
  the reason to care: the failure mode here is a published page nobody re-reads.
- **Tradeoff** — publishing `familiar.apiVersion` turns it into a compatibility promise. `ADR-0087`
  point 9 made that surface much smaller — an event contract rather than a component API — but it is
  a promise either way.
- **Tradeoff** — a gallery invites submissions, and reviewing them is ongoing work with no owner
  named here. Point 4 keeps the cost as low as it can be by making it a pull request rather than a
  system.
- **Follow-up** — screenshots. A gallery of visualizers without images is a list of names, and
  capturing them is a manual step the way `mac-*.png` already is (`ADR-0058`). Whether that is worth
  automating is undecided.
- **Follow-up** — `ADR-0069` should be resolved on its own merits rather than left proposed as a
  phantom dependency. Nothing in this ADR needs it.
