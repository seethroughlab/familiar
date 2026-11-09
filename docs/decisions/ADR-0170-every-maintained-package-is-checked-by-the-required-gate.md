# ADR-0170: CI Type-Checks Every Maintained Package

Status: accepted

Date: 2026-11-08

Extends [ADR-0127](ADR-0127-current-documentation-precedes-project-history.md) and
[ADR-0129](ADR-0129-the-web-client-is-generated-from-the-openapi-contract.md)

## Context

`@familiar/frontend` currently fails TypeScript checking: `LibraryDiscoverResponse` names an
undefined `RediscoverySuggestion`, the audio contract test names the retired
`FamiliarAudioPlugin`, and its fake engine omits declared capabilities. Vite still builds because
it transpiles without semantic checking. The package has no `typecheck` script, and neither root
`make check` nor CI invokes one.

The generated API package is checked, so a green build misleadingly suggests that the entire
frontend contract compiles. The audit also found that bundle verification rewrites tracked
performance reports; ordinary verification should not dirty the worktree.

## Decision

1. Every maintained TypeScript workspace package exposes a `typecheck` script using its committed
   configuration. A package with no TypeScript source may declare that explicitly.
2. Fix the current errors without weakening `AudioEngine`, adding `any`, or excluding the failing
   test from compilation.
3. Root `make check` and required CI run frontend type checking next to lint, boundaries, unit
   tests, and generated-client checks.
4. The Vite build remains separate; compilation and bundling answer different questions.
5. A workspace check fails when a maintained TypeScript package has neither a `typecheck` command
   nor an explicit source-free declaration.
6. Database-free checks do not modify tracked files. Artifact updates use a separately named
   command or an ignored temporary output.
7. Contributor docs name both quality tiers: `make check` and `cd backend && make test`.

## Phased Delivery

1. **Repair:** fix current errors and add the package command.
2. **Enforce:** add it to local and CI gates; prove a deliberate error fails both.
3. **Cover:** inventory workspace packages and make verification leave a clean worktree.

**Exit condition:** every maintained TypeScript package is covered, the current failures are fixed,
a deliberate regression fails locally and in CI, and `make check` leaves the worktree unchanged.

## Alternatives Considered

**Rely on Vite.** Rejected because Vite deliberately does not perform full type checking.

**Run TypeScript only in CI.** Rejected because `make check` is the documented local equivalent.

**Check only generated code.** Rejected because generated types can be valid while handwritten
application code misuses or duplicates them.

## Consequences

- **Positive:** green means generated and handwritten TypeScript compile.
- **Positive:** contract drift is caught in the change that creates it.
- **Tradeoff:** stricter gates initially expose failures older builds ignored.
- **Tradeoff:** local checks and CI take slightly longer.
