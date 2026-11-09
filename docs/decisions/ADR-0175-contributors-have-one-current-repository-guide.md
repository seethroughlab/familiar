# ADR-0175: Contributor Documentation Has One Current Repository Guide

Status: accepted

Date: 2026-11-08

Extends [ADR-0127](ADR-0127-current-documentation-precedes-project-history.md)

## Context

Current documentation is a project strength. `docs/START-HERE.md` explains the system,
`docs/HEALTH.md` names current debt, and the ADR index makes the decision history navigable.

`AGENTS.md` and `CLAUDE.md` remain two exhaustive repository guides, however. Shared architecture,
commands, and guardrails can drift. A newcomer also needs to understand that database-free
`make check` is not the full backend suite and that Apple listening clients live elsewhere.

## Decision

1. `AGENTS.md` is the tool-neutral repository guide and single source for architecture, directory
   ownership, workflows, quality commands, and guardrails.
2. `CLAUDE.md` contains only tool-specific behavior and links to `AGENTS.md`. If its tooling
   supports inclusion, it includes the shared file rather than copying it.
3. `docs/START-HERE.md` remains the human orientation and code map. It links to operational
   documents and ADRs without duplicating command-by-command agent instructions.
4. `docs/HEALTH.md` remains the live debt register. Audit findings are removed only when their ADR
   exit conditions are met.
5. Quality guidance names both tiers: `make check` and `cd backend && make test`.
6. Documentation checks validate internal links, the ADR index, named commands, and references to
   retired browser-playback architecture.
7. After the preceding audit phases, a developer unfamiliar with the project performs a
   clean-machine onboarding pass. Missing prerequisites and ambiguous ownership are fixed before
   this ADR is complete.

## Phased Delivery

1. **Deduplicate:** reduce `CLAUDE.md` to tool-specific material and one shared reference.
2. **Validate:** extend checks for commands, links, and retired architecture.
3. **Exercise:** conduct the clean-machine pass and repair observed gaps.

**Exit condition:** shared contributor guidance exists in one file, checks cover its critical
references, and an unfamiliar developer reaches database-free checks without an undocumented step.

## Alternatives Considered

**Keep both guides synchronized by convention.** Rejected because duplication creates the review
burden and gives no reliable signal when only one changes.

**Make `START-HERE.md` the only guide.** Rejected because human orientation and tool-facing
operations serve different readers.

**Generate both from a template.** Rejected for now because one shared file plus a small wrapper is
simpler and readable without generation.

## Consequences

- **Positive:** newcomers and coding tools receive the same current guardrails.
- **Positive:** checks catch stale commands and references earlier.
- **Tradeoff:** tool-specific files are no longer completely standalone.
- **Tradeoff:** a real onboarding exercise consumes another developer's time, which is the evidence
  this decision needs.
