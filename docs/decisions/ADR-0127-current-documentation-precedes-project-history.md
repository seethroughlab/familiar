# ADR-0127: Current Documentation Precedes Project History

Status: proposed

Date: 2026-09-17

## Context

Familiar records decisions thoroughly. There are more than one hundred ADRs, long implementation notes in
accepted records, an audit backlog that describes deleted player and offline code, and source comments that
often preserve the sequence by which a file reached its current form. This is valuable evidence for a
maintainer who already knows the system.

For a newcomer, the same material reverses the order of learning. They encounter why old architecture was
removed before they can see what owns a request today. Some current guides disagree at the edges: the
architecture overview says the app has no service worker (`docs/ARCHITECTURE.md:16`) while
`packages/web/public/sw.js` deliberately remains as a tombstone, and the root `package.json` still
advertises `build:cap` (line 7), a Capacitor build command for an app deleted on 2026-08-11. Neither is
difficult to explain, but both teach the reader that every statement may require an archaeological check.

ADRs should retain history; deleting or rewriting accepted records would make them unreliable. The missing
artifact is a small, tested current-state path that points into history only when the reason matters.

## Decision

1. **`docs/START-HERE.md` is the canonical first document for a developer.** It states what Familiar is
   now, what this repository owns, how the running pieces connect and which repository owns native clients.

2. **The guide contains one current architecture map and one traced vertical slice.** The slice follows a
   representative operation from web feature hook through generated client, route, application operation,
   service and persistence/background work. Every named file exists and is checked in CI.

3. **Five common changes have golden paths:** add an endpoint, add a persisted field, add background work,
   add an admin section and add a visualizer. Each path names the contract, test and documentation work
   required, not only the first source file to edit.

4. **One command diagnoses setup and one command reproduces required checks.** `make doctor` reports
   runtime versions, service reachability, database identity, migration state and generated-contract drift
   without mutating data. `make check` runs the safe local equivalents of required CI checks.

5. **Current-state documents are assertions, not journals.** README, START-HERE, ARCHITECTURE,
   CONTRIBUTING and AGENTS describe only the present unless a historical fact is necessary to prevent a
   known mistake. History belongs in ADRs, changelogs and an archive.

6. **ADRs gain an index by subsystem and status.** A reader can find active decisions for Web Admin, API,
   Analysis, Playback, Visualizers, Operations and Security without reading them in number order.
   Superseded and rejected records remain searchable but are not presented as current instructions.

7. **The audit backlog becomes a current health register or is archived.** Completed work and references
   to deleted files do not remain in the active backlog. Current debt names an owner boundary, evidence and
   a condition for closure rather than carrying a chronological implementation diary.

8. **Source comments state the invariant and the evidence that makes it load-bearing** — the measured
   number, the crash, the report — and link the owning ADR for the rest. They do not narrate the sequence
   of prior implementations: "it was a `@StateObject`, then a `static weak var`, then…" belongs in the
   record; "build 33 crashed here" and "thirty-four publishes a second" stay at the point of edit, because
   that is where the next person is standing when they need them. This applies to new comments; existing
   ones are not retrofitted.

9. **Commands and file references in current guides are tested.** CI checks that referenced repository
   paths exist and that documented package scripts or Make targets resolve. Deliberate failing convenience
   targets are labelled as redirects and are not presented as available builds.

10. **Security posture is visible on the first path.** START-HERE identifies ADR-0045's current incomplete
    state: a token capability exists, but enforcement is not yet on by default. It does not imply that a
    published port is protected merely because the feature exists.

## Alternatives Considered

**Shorten the ADRs.** Rejected as a remedy. Existing records are evidence and many implementation notes
capture measured behavior that belongs nowhere else. The problem is routing, not simply length.

**Rewrite accepted ADRs to match current code.** Rejected. An ADR records the decision at a point in time;
silently making it timeless destroys the history it exists to preserve. Superseding records and status
annotations are the correct mechanism.

**Use the README as the only entry point.** Rejected. The README serves operators and prospective users as
well as contributors; a developer architecture guide should not compete with installation and product
material.

**Generate all documentation from source.** Rejected. Paths and command existence can be checked
mechanically, but ownership and design intent still require prose and review.

## Consequences

- **Positive:** a contributor can learn the current system without knowing the sequence that produced it.
- **Positive:** stale commands and file references fail automatically.
- **Positive:** ADR detail remains intact and becomes easier to discover by subject.
- **Tradeoff:** current-state guides require maintenance whenever ownership or workflows move.
- **Tradeoff:** the history a comment no longer narrates is only as findable as point 6's index makes
  it; the index is a prerequisite of point 8, not a nicety.
- **Follow-up:** after acceptance, review CLAUDE.md and AGENTS.md together; two exhaustive agent guides that
  disagree are worse than one shared current source included by both.

