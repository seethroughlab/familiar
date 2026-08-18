# ADR-0078: The Schema Copy Is Verified, Not Trusted

Status: proposed

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

**The backend lint already knows, and names the fix.** `scripts/lint_openapi.py:44-58` keeps a
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

1. **CI verifies the two schema copies are identical.** The `familiar` workflow checks out
   `familiar-apple` alongside itself and fails if `backend/openapi.json` and
   `Sources/FamiliarAPI/openapi.json` differ by so much as a byte. Byte equality, not semantic
   equality: `dump_openapi.py` already renders deterministically with sorted keys, so anything else
   is drift.

2. **The copy is made by a target, never by hand.** `make vendor-schema` writes the Apple repo's
   copy from `backend/openapi.json`, and `make vendor-schema-check` is the CI form. Copying by hand
   is what produced a four-path gap that nobody noticed.

3. **The tag cross-check runs in CI.** With the sibling repo checked out, the comparison between
   `VENDORED_TAGS` and the generator config's `filter.tags` — which
   `lint_openapi.py` documents as never running — runs on every build. This is the check that makes
   `ADR-0014` point 4's "updated in the same change" enforceable rather than aspirational.

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

**Make the Apple repo consume the schema as a package or submodule** instead of a copy. Genuinely
tidier, and rejected as too large a change to ride along with a restructure: it changes how the
SwiftPM build resolves the file, affects offline and CI builds, and would need its own ADR. The
copy is not the problem; the *unchecked* copy is.

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
- **Tradeoff** — `familiar` CI gains a dependency on `familiar-apple` being checked out. That is a
  second checkout on every backend job, needing credentials the workflow does not have today, and it
  couples one repository's build to another's availability.
- **Tradeoff** — point 2 makes the Apple repo's copy a generated file that a `familiar` target
  writes, which means a change in one repo produces a commit in the other. That is already true in
  practice; it becomes true on purpose.
- **Follow-up** — the schema copy check tells you the copies differ, not which side is right. It
  assumes `backend/openapi.json` is authoritative, which `ADR-0007` already established.
- **Follow-up** — if the second checkout proves too awkward, the fallback is a scheduled job rather
  than a per-build one. Slower to catch drift, but still not nothing, which is the current state.
