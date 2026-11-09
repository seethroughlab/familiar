# ADR-0169: The Maintainability Audit Is Fixed in Risk Order

Status: accepted

Date: 2026-11-08

## Context

The 2026-11-08 audit found a codebase in substantially better shape than the previous audit.
`docs/START-HERE.md`, `docs/HEALTH.md`, the ADR index, disposable test database, generated
TypeScript client, boundary checks, and workflow-based administration navigation have removed real
onboarding and maintenance hazards.

The remaining risks are uneven. A remotely reachable tokenless server and a background queue that
does not converge affect running installations. A frontend package omitted from type checking makes
the quality signal unreliable. Handwritten API types and a service calling route functions are
important design debt, but are less urgent. UI diagnostics, browser fixtures, accessibility, and
duplicated contributor guidance affect confidence and onboarding after the gates tell the truth.

The findings are split so accepting one does not silently decide the others:

- [ADR-0170](ADR-0170-every-maintained-package-is-checked-by-the-required-gate.md): truthful gates.
- [ADR-0171](ADR-0171-a-remotely-reachable-server-is-protected-by-default.md): secure defaults.
- [ADR-0172](ADR-0172-analysis-work-converges-and-has-one-status-model.md): analysis convergence.
- [ADR-0173](ADR-0173-transports-share-operations-and-generated-contracts.md): shared boundaries.
- [ADR-0174](ADR-0174-admin-workflows-show-actions-before-diagnostics.md): admin UI quality.
- [ADR-0175](ADR-0175-contributors-have-one-current-repository-guide.md): newcomer guidance.

## Decision

1. **Phase 0 is ADR-0170.** Make quality signals truthful before relying on them for migrations.
2. **Phase 1 is ADR-0171.** Secure new remotely reachable installations.
3. **Phase 2 is ADR-0172.** Stop the analysis loop and establish one status model.
4. **Phase 3 is ADR-0173.** Extract shared operations and continue generated-client migration.
5. **Phase 4 is ADR-0174.** Make browser workflows deterministic and diagnostics accessible.
6. **Phase 5 is ADR-0175.** Consolidate guidance and perform a clean-machine onboarding pass.
7. Phase 0 blocks later implementation. After it, independent work may proceed in parallel when it
   does not alter authentication or analysis semantics.
8. `docs/HEALTH.md` remains the progress register. A finding is removed only when its focused ADR's
   exit condition is met.
9. This record is complete when ADR-0170 through ADR-0175 are accepted or explicitly rejected and
   every accepted record has met its exit condition.

## Alternatives Considered

**One comprehensive ADR.** Rejected because agreement on type checking should not implicitly approve
a media authorization design or analysis retry semantics.

**Treat every finding as an unrelated issue.** Rejected because order is part of the decision:
architectural cleanup must not displace a security default or operational loop, and migrations need
a trustworthy gate first.

**Fix the easiest items first.** Rejected because it favors local cleanup over failures that affect
running installations.

## Consequences

- **Positive:** each material decision can be reviewed and implemented on its own evidence.
- **Positive:** risk, rather than implementation convenience, determines order.
- **Positive:** the health register stays concise while focused ADRs explain the remedies.
- **Tradeoff:** six records create more review work than one checklist.
- **Tradeoff:** later cleanup can wait behind smaller but higher-risk operational work.
