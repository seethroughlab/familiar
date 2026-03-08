# Frontend Organization & Best Practices Audit Plan

This document is the roadmap and progress record for the full 6-phase frontend audit effort.

## Progress Summary
- [x] Phase 1: Architecture & Boundaries Audit
- [ ] Phase 2: Data/API Layer Audit
- [ ] Phase 3: UI/Component Audit
- [ ] Phase 4: Playback/Offline Critical-Path Audit
- [ ] Phase 5: Testing & Quality Gates Audit
- [ ] Phase 6: Performance & Bundle Audit

## Artifact Index (Use With This Roadmap)
- [frontend-architecture-phase1-audit.md](/Users/jeff/Developer/familiar/docs/frontend-architecture-phase1-audit.md): Phase 1 evidence report (ownership map, dependency findings, registration pattern audit, reproducibility notes).
- [frontend-architecture-boundary-rules.md](/Users/jeff/Developer/familiar/docs/frontend-architecture-boundary-rules.md): Canonical boundary/layer rules and concrete current violations.
- [frontend-architecture-issue-backlog.md](/Users/jeff/Developer/familiar/docs/frontend-architecture-issue-backlog.md): Prioritized top-10 issue list with severity/effort/blast radius plus Batch A/B/C execution groups.
- [frontend-ci-boundary-guardrails-proposal.md](/Users/jeff/Developer/familiar/docs/frontend-ci-boundary-guardrails-proposal.md): CI/static-enforcement proposal for dependency boundaries, cycles, and module budgets.

## How To Use This Document
- Treat each phase section below as the execution checklist.
- Add links to new deliverables under the relevant phase when created.
- Mark a phase complete only when all checklist items in that phase are done and evidence is linked.

## Phase 1: Architecture & Boundaries Audit
- Status: Complete
- Deliverables:
  - [frontend-architecture-phase1-audit.md](/Users/jeff/Developer/familiar/docs/frontend-architecture-phase1-audit.md)
  - [frontend-architecture-boundary-rules.md](/Users/jeff/Developer/familiar/docs/frontend-architecture-boundary-rules.md)
  - [frontend-architecture-issue-backlog.md](/Users/jeff/Developer/familiar/docs/frontend-architecture-issue-backlog.md)
  - [frontend-ci-boundary-guardrails-proposal.md](/Users/jeff/Developer/familiar/docs/frontend-ci-boundary-guardrails-proposal.md)
- Checklist:
  - [x] Build module ownership map across `packages/frontend`, `packages/web`, and `packages/ios`.
  - [x] Classify layers (`platform-entry`, `app-shell`, `feature`, `store/state`, `service/api`, `player/engine`, `shared-utils`).
  - [x] Compare allowed dependency directions vs actual imports.
  - [x] Produce top structural issues, boundary rules, and CI guardrail proposal.

## Phase 2: Data/API Layer Audit
- Status: Not started
- Deliverables: (to be added)
- Checklist:
  - [ ] Audit API client boundaries and query-layer consistency.
  - [ ] Verify error-shape handling and retry/offline behavior consistency.
  - [ ] Identify contract typing gaps and direct HTTP usage bypassing API modules.

## Phase 3: UI/Component Audit
- Status: Not started
- Deliverables: (to be added)
- Checklist:
  - [ ] Audit component size, complexity, and cohesion.
  - [ ] Identify duplicated UI state logic and prop-drilling hotspots.
  - [ ] Propose extraction targets for reusable feature modules.

## Phase 4: Playback/Offline Critical-Path Audit
- Status: Not started
- Deliverables: (to be added)
- Checklist:
  - [ ] Audit queue + playback + offline state interactions.
  - [ ] Identify regressions risks across WebAudio/Capacitor paths.
  - [ ] Propose guardrails for no-service, offline invariants, and lock-screen behavior.

## Phase 5: Testing & Quality Gates Audit
- Status: Not started
- Deliverables: (to be added)
- Checklist:
  - [ ] Map risk areas to missing unit/integration/e2e coverage.
  - [ ] Identify flaky tests and weak CI gates.
  - [ ] Propose minimum quality gates by risk category.

## Phase 6: Performance & Bundle Audit
- Status: Not started
- Deliverables: (to be added)
- Checklist:
  - [ ] Audit bundle composition and code-splitting strategy.
  - [ ] Identify rerender hotspots and list virtualization inconsistencies.
  - [ ] Propose measurable performance budgets and tracking.
