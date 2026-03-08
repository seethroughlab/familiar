# Frontend Organization & Best Practices Audit Plan

This document is the roadmap and progress record for the full 6-phase frontend audit effort.

## Progress Summary
- [x] Phase 1: Architecture & Boundaries Audit
- [x] Phase 2: Data/API Layer Audit
- [x] Phase 3: UI/Component Audit
- [x] Phase 4: Playback/Offline Critical-Path Audit
- [x] Phase 5: Testing & Quality Gates Audit
- [x] Phase 6: Performance & Bundle Audit

## Artifact Index (Use With This Roadmap)
- [frontend-architecture-phase1-audit.md](/Users/jeff/Developer/familiar/docs/frontend-architecture-phase1-audit.md): Phase 1 evidence report (ownership map, dependency findings, registration pattern audit, reproducibility notes).
- [frontend-architecture-boundary-rules.md](/Users/jeff/Developer/familiar/docs/frontend-architecture-boundary-rules.md): Canonical boundary/layer rules and concrete current violations.
- [frontend-architecture-issue-backlog.md](/Users/jeff/Developer/familiar/docs/frontend-architecture-issue-backlog.md): Prioritized top-10 issue list with severity/effort/blast radius plus Batch A/B/C execution groups.
- [frontend-ci-boundary-guardrails-proposal.md](/Users/jeff/Developer/familiar/docs/frontend-ci-boundary-guardrails-proposal.md): CI/static-enforcement proposal for dependency boundaries, cycles, and module budgets.
- [frontend-data-api-layer-audit-phase2.md](/Users/jeff/Developer/familiar/docs/frontend-data-api-layer-audit-phase2.md): Phase 2 item 1 report on API boundaries, query-key consistency, and invalidation patterns.
- [frontend-error-retry-offline-audit-phase2-item2.md](/Users/jeff/Developer/familiar/docs/frontend-error-retry-offline-audit-phase2-item2.md): Phase 2 item 2 report on error normalization, retry policy drift, offline/reachability consistency, and test gaps.
- [frontend-contract-typing-http-bypass-audit-phase2-item3.md](/Users/jeff/Developer/familiar/docs/frontend-contract-typing-http-bypass-audit-phase2-item3.md): Phase 2 item 3 report on API contract typing gaps and direct HTTP bypass inventory.
- [frontend-ui-component-audit-phase3-item1.md](/Users/jeff/Developer/familiar/docs/frontend-ui-component-audit-phase3-item1.md): Phase 3 item 1 report on component size/complexity/cohesion with prioritized extraction batches.
- [frontend-ui-state-propdrilling-audit-phase3-item2.md](/Users/jeff/Developer/familiar/docs/frontend-ui-state-propdrilling-audit-phase3-item2.md): Phase 3 item 2 report on duplicated UI state logic, prop-drilling hotspots, and remediation batches.
- [frontend-ui-extraction-targets-phase3-item3.md](/Users/jeff/Developer/familiar/docs/frontend-ui-extraction-targets-phase3-item3.md): Phase 3 item 3 decision-ready reusable module extraction targets, contracts, and migration batches.
- [frontend-playback-offline-criticalpath-audit-phase4-item1.md](/Users/jeff/Developer/familiar/docs/frontend-playback-offline-criticalpath-audit-phase4-item1.md): Phase 4 item 1 audit of queue/playback/offline interaction paths with severity-ranked critical-path risks.
- [frontend-webaudio-capacitor-regressionrisk-audit-phase4-item2.md](/Users/jeff/Developer/familiar/docs/frontend-webaudio-capacitor-regressionrisk-audit-phase4-item2.md): Phase 4 item 2 regression-risk comparison across WebAudio and Capacitor playback paths with parity gaps, severity rankings, and guardrail batches.
- [frontend-playback-offline-guardrails-phase4-item3.md](/Users/jeff/Developer/familiar/docs/frontend-playback-offline-guardrails-phase4-item3.md): Phase 4 item 3 decision-complete guardrail proposal for no-service handling, offline invariants, lock-screen behavior, CI gates, and release criteria.
- [frontend-testing-quality-gates-audit-phase5-item1.md](/Users/jeff/Developer/familiar/docs/frontend-testing-quality-gates-audit-phase5-item1.md): Phase 5 item 1 risk-to-coverage map of frontend testing gaps across unit/integration/e2e layers and CI execution.
- [frontend-testing-quality-gates-audit-phase5-item2.md](/Users/jeff/Developer/familiar/docs/frontend-testing-quality-gates-audit-phase5-item2.md): Phase 5 item 2 flaky-test and weak-CI-gate audit with severity-ranked findings and remediation batches.
- [frontend-testing-quality-gates-audit-phase5-item3.md](/Users/jeff/Developer/familiar/docs/frontend-testing-quality-gates-audit-phase5-item3.md): Phase 5 item 3 minimum quality gate matrix by risk category (P0-P3), with CI/branch-protection/release gate recommendations.
- [frontend-performance-bundle-audit-phase6-item1.md](/Users/jeff/Developer/familiar/docs/frontend-performance-bundle-audit-phase6-item1.md): Phase 6 item 1 bundle composition and code-splitting audit with measured build output and split-priority batches.
- [frontend-rerender-virtualization-audit-phase6-item2.md](/Users/jeff/Developer/familiar/docs/frontend-rerender-virtualization-audit-phase6-item2.md): Phase 6 item 2 rerender hotspot and virtualization-consistency audit with prioritized remediation batches.
- [frontend-performance-budgets-tracking-phase6-item3.md](/Users/jeff/Developer/familiar/docs/frontend-performance-budgets-tracking-phase6-item3.md): Phase 6 item 3 measurable performance budget matrix and tracking/CI gate specification.

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
- Status: Complete
- Deliverables:
  - [frontend-data-api-layer-audit-phase2.md](/Users/jeff/Developer/familiar/docs/frontend-data-api-layer-audit-phase2.md)
  - [frontend-error-retry-offline-audit-phase2-item2.md](/Users/jeff/Developer/familiar/docs/frontend-error-retry-offline-audit-phase2-item2.md)
  - [frontend-contract-typing-http-bypass-audit-phase2-item3.md](/Users/jeff/Developer/familiar/docs/frontend-contract-typing-http-bypass-audit-phase2-item3.md)
- Checklist:
  - [x] Audit API client boundaries and query-layer consistency.
  - [x] Verify error-shape handling and retry/offline behavior consistency.
  - [x] Identify contract typing gaps and direct HTTP usage bypassing API modules.

## Phase 3: UI/Component Audit
- Status: Complete
- Deliverables:
  - [frontend-ui-component-audit-phase3-item1.md](/Users/jeff/Developer/familiar/docs/frontend-ui-component-audit-phase3-item1.md)
  - [frontend-ui-state-propdrilling-audit-phase3-item2.md](/Users/jeff/Developer/familiar/docs/frontend-ui-state-propdrilling-audit-phase3-item2.md)
  - [frontend-ui-extraction-targets-phase3-item3.md](/Users/jeff/Developer/familiar/docs/frontend-ui-extraction-targets-phase3-item3.md)
- Checklist:
  - [x] Audit component size, complexity, and cohesion.
  - [x] Identify duplicated UI state logic and prop-drilling hotspots.
  - [x] Propose extraction targets for reusable feature modules.

## Phase 4: Playback/Offline Critical-Path Audit
- Status: Complete
- Deliverables:
  - [frontend-playback-offline-criticalpath-audit-phase4-item1.md](/Users/jeff/Developer/familiar/docs/frontend-playback-offline-criticalpath-audit-phase4-item1.md)
  - [frontend-webaudio-capacitor-regressionrisk-audit-phase4-item2.md](/Users/jeff/Developer/familiar/docs/frontend-webaudio-capacitor-regressionrisk-audit-phase4-item2.md)
  - [frontend-playback-offline-guardrails-phase4-item3.md](/Users/jeff/Developer/familiar/docs/frontend-playback-offline-guardrails-phase4-item3.md)
- Checklist:
  - [x] Audit queue + playback + offline state interactions.
  - [x] Identify regressions risks across WebAudio/Capacitor paths.
  - [x] Propose guardrails for no-service, offline invariants, and lock-screen behavior.

## Phase 5: Testing & Quality Gates Audit
- Status: Complete
- Deliverables:
  - [frontend-testing-quality-gates-audit-phase5-item1.md](/Users/jeff/Developer/familiar/docs/frontend-testing-quality-gates-audit-phase5-item1.md)
  - [frontend-testing-quality-gates-audit-phase5-item2.md](/Users/jeff/Developer/familiar/docs/frontend-testing-quality-gates-audit-phase5-item2.md)
  - [frontend-testing-quality-gates-audit-phase5-item3.md](/Users/jeff/Developer/familiar/docs/frontend-testing-quality-gates-audit-phase5-item3.md)
- Checklist:
  - [x] Map risk areas to missing unit/integration/e2e coverage.
  - [x] Identify flaky tests and weak CI gates.
  - [x] Propose minimum quality gates by risk category.

## Phase 6: Performance & Bundle Audit
- Status: Complete
- Deliverables:
  - [frontend-performance-bundle-audit-phase6-item1.md](/Users/jeff/Developer/familiar/docs/frontend-performance-bundle-audit-phase6-item1.md)
  - [frontend-rerender-virtualization-audit-phase6-item2.md](/Users/jeff/Developer/familiar/docs/frontend-rerender-virtualization-audit-phase6-item2.md)
  - [frontend-performance-budgets-tracking-phase6-item3.md](/Users/jeff/Developer/familiar/docs/frontend-performance-budgets-tracking-phase6-item3.md)
- Checklist:
  - [x] Audit bundle composition and code-splitting strategy.
  - [x] Identify rerender hotspots and list virtualization inconsistencies.
  - [x] Propose measurable performance budgets and tracking.
