# ADR-0174: Admin Workflows Show Actions Before Diagnostics

Status: accepted

Date: 2026-11-08

Implementation:

- **Phase 1, 2026-11-09. Point 1's premise did not hold for playlists.** The playlist spec could not
  seed its way to passing, because the web app has no playlist screen to drive: ADR-0058 made it an
  administration tool, `app/routes.ts` has no playlist section, `navigateToTab('Playlists')` did
  nothing ("visible by default"), and no component creates, renames or deletes a playlist. Its four
  tests could only skip; CI reported 15 passed and 5 skipped of 20. `playlists.spec.ts` is deleted,
  and playlist behaviour is tested at the operation and REST level instead
  (`tests/test_playlist_operations.py`, `tests/test_api_playlists.py`, ADR-0173). The other skips
  were state, not missing UI: `profiles.spec.ts` now seeds the profile it selects through the API
  (and deletes it) and asserts the selector a fresh context always shows; `library-sync.spec.ts`
  cancels any running sync, then requires the button's click to start one (the server answers
  `started`) and the panel to show Cancel. Waiting the setup's sync out instead was tried first and
  was flaky: on a cold CI runner it was still running after five minutes. No `test.skip` remains in
  `e2e/`. `packages/web/scripts/check-e2e-skips.mjs` runs after the suite in CI and fails on any
  skipped test unless it names a capability from its `CAPABILITIES` list (empty today), which it
  reports on a line of its own (point 2).
- **Phases 2 and 3, 2026-11-09.** `backend/app/services/failure_report.py` gives each task failure
  a stable `kind` (point 3): the analysis reasons ADR-0172 already classifies (`undecodable`,
  `file_missing`, `worker_crashed`, `timeout`, `error`) plus `database` and `network`, told apart
  first because their messages also say "timeout" and "connection". Each kind has a plain summary
  and a next action. `_record_task_failure` stores the kind and a **redacted** message: DSN
  passwords, `X-Familiar-Token`, bearer tokens, `api_key=`/`token=`/`password=` values and
  `sk-`/`AKIA` key shapes become `***` before anything is kept or sent (point 5).
  `/health/workers` gains `failure_groups` (kind, task, summary, next action, count, distinct tracks
  affected, last occurrence, up to five redacted examples), most frequent first; `recent_failures`
  stays, redacted and with `kind`, and records from before this are classified and redacted on
  read. Analysis → Status shows the groups (`screens/analysis/FailureGroups.tsx`) with the raw
  messages behind a closed `<details>` and a copy button; the Overview's attention item names the
  top group and its next action instead of a raw count (point 4). Contract stays v1 (additive).
- **Phase 4, 2026-11-09.** `packages/web/e2e/accessibility.spec.ts` runs axe-core (WCAG 2.1 A and
  AA, and best-practice) on Overview, Library, Analysis and Server at 1280 and 390 wide, and on
  Analysis in a seeded error state (grouped failures and failed tracks); a violation fails CI, and
  its `EXCEPTIONS` list (owner and removal condition, point 7) is empty. The WCAG-only scan was
  clean at first; adding best-practice found the two real problems, both fixed: **no page had an
  `<h1>`** (the TopBar's "Familiar" is the `<h1>` now, shown from `sm` and screen-reader-only
  below, so destinations stay `<h2>` and sections `<h3>`), and **white text on the cyan-400 accent
  measured 1.82:1** in five places (Overview, Artwork, Organiser, Duplicates, the alphabet popup);
  dark text is about 11:1. The scan was checked against deliberately injected violations
  (`button-name`, `image-alt`) before its clean result was trusted. Manual keyboard and VoiceOver
  checks are in `docs/RELEASE-CHECKLIST.md` (point 8).
- **Exit condition met:** playlist and profile tests fail rather than skip when their workflow is
  unavailable; analysis failures have grouped, actionable summaries with redacted detail behind a
  disclosure; and the four destinations pass the accessibility gate.

Extends [ADR-0126](ADR-0126-the-admin-ui-is-organized-around-operator-workflows.md)

## Context

ADR-0126 materially improved the administration UI. Overview, Library, Analysis, and Server now
express recognizable workflows on desktop and mobile. The audit found three remaining confidence
gaps:

- Playlist end-to-end tests skip when fixture playlists or controls are absent. A run can pass
  without exercising the workflow named by the suite.
- Analysis prints raw backend exceptions as its primary failure presentation. Operators receive
  repeated ORM or driver details without grouping, impact, or a next action.
- No automated browser accessibility gate covers the dense administration screens.

An administration surface retains full diagnostics, but its first answer is what failed, how much
is affected, and what the operator can do.

## Decision

1. E2E setup creates the playlists and tracks each test needs. Missing data or controls fail the
   test; they do not call `test.skip`.
2. Environment skips are allowed only for a capability declared before the suite starts. CI reports
   and budgets them separately from passed tests.
3. Analysis failures expose a stable kind, affected resource when safe, occurrence count, and
   timestamp in addition to raw detail.
4. The default view groups failures by kind and task and shows a plain-language summary, affected
   count, last occurrence, and an appropriate next action.
5. Raw exceptions and identifiers remain in an expandable diagnostic view with a copy action.
   Secrets and usable authorization material are redacted before reaching the browser.
6. Browser accessibility checks cover Overview, Library, Analysis, and Server at desktop and mobile
   sizes, including a populated error state.
7. Automated checks block CI after the baseline is fixed. A temporary exception names its owner and
   removal condition; there is no permanent global allowlist.
8. The release checklist includes keyboard and screen-reader smoke tests because automation cannot
   establish full accessibility.

## Phased Delivery

1. **Deterministic E2E:** seed fixtures and remove conditional workflow skips.
2. **Structured failures:** add stable fields and grouped operator summaries.
3. **Progressive diagnostics:** keep redacted detail behind disclosure and copy actions.
4. **Accessibility:** fix the baseline, add browser checks, and document manual smoke testing.

**Exit condition:** playlist tests fail when workflows are unavailable, common analysis failures
have actionable summaries with diagnostics behind disclosure, and representative routes pass the
accessibility gate.

## Alternatives Considered

**Keep conditional skips for flexible fixtures.** Rejected because missing fixtures and broken
selectors become indistinguishable from an unsupported environment.

**Keep raw errors prominent for technical operators.** Rejected as the default, not as available
detail. Operators still need impact, grouping, and remediation first.

**Use only manual accessibility review.** Rejected because basic naming, landmark, contrast, and
focus regressions are inexpensive to catch continuously.

## Consequences

- **Positive:** green E2E means named workflows actually ran.
- **Positive:** operators can act without losing detailed diagnostics.
- **Positive:** common accessibility regressions are caught immediately.
- **Tradeoff:** deterministic fixtures require more maintenance.
- **Tradeoff:** structured failure kinds become a stable API contract.
- **Tradeoff:** automated checks add CI time and still require manual review.
