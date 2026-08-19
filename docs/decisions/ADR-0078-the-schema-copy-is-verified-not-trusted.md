# ADR-0078: The Schema Copy Is Verified, Not Trusted

Status: accepted

Date: 2026-08-18

Extends [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md), whose point 6 says regressions
must fail a build. This closes the gap between that rule and the one artefact it cannot see.

## Context

`ADR-0007` made the OpenAPI schema a contract and put real machinery behind it:
`scripts/dump_openapi.py` renders `backend/openapi.json` deterministically, `make openapi-check`
fails CI if it drifts from the app, and `scripts/lint_openapi.py` enforces operationId length,
uniqueness, declared error responses and media types. All of that guards **one** edge — the
FastAPI app against the committed schema in the same repository.

**The contract has a second copy, and nothing checks it.**
`familiar-apple/Sources/FamiliarAPI/openapi.json` is a verbatim hand-copy, and it is what the
swift-openapi-generator build plugin actually reads. Measured today:

| | |
|---|---|
| paths in `backend/openapi.json` | 228 |
| paths in the Apple copy | 224 |
| paths missing from the copy | `/artwork/coverage`, `/artwork/refetch-generated`, `/playback/artifacts/{request_id}`, `/tracks/{track_id}/visualizer-ranking` |
| schemas missing from the copy | 9, including `VisualizerRankingRequest`, `VisualizerRankingResponse`, `RankedVisualizer`, `ArtworkCoverageResponse` |

**The Apple side's CI does not catch it, and cannot.** Its check is
`test -f Sources/FamiliarAPI/openapi.json` followed by `swift build --target FamiliarAPI`
(`familiar-apple/.github/workflows/ci.yml:47-51`). That proves a client generates from whatever file
is present — a stale file generates a stale client perfectly well.

**The backend lint already knows, and proposes a fix this ADR does not take.**
`scripts/lint_openapi.py:44-58` keeps a
vendored copy of the generated surface, compares it against the real Swift config when the sibling
repo happens to be checked out, and states the limitation rather than leaving it to be discovered:

> *"the cross-check does not run in CI, because the Apple repo is not checked out there. It runs for
> anyone working with both repos side by side… **A second checkout in the workflow would close that
> gap.**"*

**Why this becomes urgent now rather than remaining a known wart.** A restructure that renames tags
and operation ids is exactly the change that a stale copy turns into a silent divergence: the backend
regenerates, the copy is forgotten, and `familiar-apple` keeps compiling against last week's contract
while both CIs stay green. A copy that drifts by four paths at rest will drift by forty during a
reshape.

**There is a third vendored artefact with no check at all.**
`familiar-apple/App/Shared/VisualizerBundle.html` is a committed build product of
`packages/web/visualizer.html`, produced by `familiar-apple/scripts/build-visualizer.sh`. It carries
inlined API paths and the whole Tailwind build of `packages/frontend/src/index.css`. Nothing records
which `familiar` revision it was built from, and nothing notices when it lags — which is how it has
already silently lost features more than once.

## Decision

1. **The consuming repository verifies its own copy, and does it by fetching rather than by
   checkout.** `familiar-apple`'s CI fetches `backend/openapi.json` from `familiar`'s default branch
   over the GitHub API and fails if its own `Sources/FamiliarAPI/openapi.json` differs by a byte.
   Byte equality, not semantic equality: `dump_openapi.py` already renders deterministically with
   sorted keys, so anything else is drift.

   **The check belongs on this side, and the reason is `ADR-0079`'s premise.** Putting it in
   `familiar`'s CI — the first draft of this decision — would fail a backend pull request because
   *another repository* had not been updated yet, which forces the two into the lockstep that
   `ADR-0079` establishes is impossible. A schema change must be able to merge on its own. Drift
   only causes harm when a client is generated from the stale copy, and that happens here.

2. **The copy is made by a target, never by hand.** A target in `familiar-apple` writes
   `Sources/FamiliarAPI/openapi.json` — from a sibling checkout when there is one, otherwise from the
   same fetch point 1 uses — with a `--check` form for CI. Copying by hand is what produced a
   four-path gap that nobody noticed.

3. **The tag cross-check runs on the same side, by the same means.** The comparison between
   `lint_openapi.py`'s `VENDORED_TAGS` and the generator config's `filter.tags` — which
   `lint_openapi.py` documents as never running — runs in `familiar-apple`'s CI, fetching the lint's
   vendored list alongside the schema. This is what makes `ADR-0014` point 4's "updated in the same
   change" enforceable rather than aspirational, and it is enforced against the repository that owns
   the config the surface is actually defined in.

4. **`VisualizerBundle.html` records the revision it was built from.** `inline-visualizer.mjs` emits
   the `familiar` commit into a `<meta>` tag, and a check in `familiar-apple` reports when the
   vendored bundle is behind the `familiar` revision the workspace has. A warning rather than a
   failure, because the two repos legitimately move independently.

5. **A vendored artefact without a freshness check is not added.** Three exist today and two were
   unguarded. Whatever the next one is — a schema, a bundle, a generated document — it ships with the
   check that detects staleness, in the same change that introduces it.

## Alternatives Considered

**Leave it and rely on the release checklist.** The status quo, and it has a measured failure rate:
four paths and nine schemas of drift, including the ADR-0064 ranking endpoint, with the discipline
nominally in force. `ADR-0007` point 6 already decided that regressions must fail a build rather than
be remembered.

**Run the check in `familiar`'s CI, with `familiar-apple` checked out beside it.** This was the first
draft, and it is what `lint_openapi.py:55-58` suggests when it says *"A second checkout in the
workflow would close that gap."* It has one genuine advantage: drift is caught at the moment of
divergence rather than at the next Apple build. Rejected because it makes every backend schema change
conditional on another repository already being current — a lockstep that contradicts `ADR-0079`,
whose whole premise is that these two version independently. It also produces the least
actionable failure message in the project: a backend pull request going red because of a file it does
not contain.

**Make the Apple repo consume the schema as a submodule** rather than a copy. This is the shape that
removes the problem instead of detecting it, and it gives pinning for free — the submodule SHA
records exactly which schema a build was made against. Rejected in both available forms.
Submoduling `familiar` whole means vendoring the backend, the frontend and the site to obtain one
918 KB file, and every clone needs `--recursive` or the Swift build fails confusingly. A
schema-only third repository is the clean version and is how this would be done across teams; for
two repositories and one maintainer it is a third thing to release into. A copy plus point 1's check
buys the same guarantee for roughly thirty lines of CI, and the copy already exists.

**Publish the schema as a SwiftPM package.** The same trade as the submodule with release ceremony
added: a tag and a version bump for every schema change, which is heavier than the change usually is.

**Fetch the schema from a URL at build time.** Rejected because it makes the Swift build depend on
network availability and on a server being current, trading a visible staleness problem for an
invisible availability one.

**Generate the Swift client in `familiar` and commit it.** This would collapse the two copies into
one artefact, and it reverses `ADR-0007`'s Implementation directly — *"no generated Swift is
committed and a backend change surfaces as a compile error"* — which is the property that makes the
contract useful. Rejected.

**Check semantic equivalence rather than byte equality**, so formatting differences do not fail
builds. Rejected because `dump_openapi.py` renders deterministically on purpose (`ADR-0007`'s
determinism finding), so any byte difference is a real difference, and a looser check is one more
thing that can be subtly wrong.

## Consequences

- **Positive** — the restructure that follows can be executed at all. Every coordinated phase in it
  assumes the copy is current, and until this lands that assumption is false.
- **Positive** — the cross-check `lint_openapi.py` has documented as not running since it was written
  starts running, which retroactively gives `ADR-0014` point 4 its enforcement.
- **Positive** — the four-path drift is repaired as a side effect of adding the check, and the
  ADR-0064 ranking endpoint reaches the Apple copy.
- **Positive** — backend schema changes stay independently mergeable. Point 1 deliberately does not
  gate `familiar` on `familiar-apple`, so this ADR does not quietly reintroduce the coupling
  `ADR-0079` exists to avoid.
- **Tradeoff** — **drift is detected later than it happens.** Between a backend schema change and the
  next `familiar-apple` build, the two copies disagree and nothing says so. That window is
  acceptable because a stale copy is inert until a client is generated from it, but it does mean the
  check reports an old problem rather than a new one.
- **Tradeoff** — `familiar-apple`'s CI gains a network dependency on the GitHub API and on
  `familiar`'s default branch being readable, so its build can now fail for a reason that has nothing
  to do with its own contents.
- **Tradeoff** — point 2 makes the copy a generated file, which means a schema change in one repo
  still produces a commit in the other. That is already true in practice; it becomes true on purpose,
  and the commit is now mechanical rather than remembered.
- **Follow-up** — the check tells you the copies differ, not which side is right. It assumes
  `backend/openapi.json` is authoritative, which `ADR-0007` already established.
- **Follow-up** — if the detection lag proves to matter, the addition is a scheduled job in
  `familiar-apple` that runs the same comparison daily, rather than moving the check back to the
  backend and taking the lockstep with it.
