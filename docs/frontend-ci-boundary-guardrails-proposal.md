# Frontend CI Boundary Guardrails Proposal (Phase 1)

## Current State
- CI runs frontend lint and web build (`.github/workflows/ci.yml`).
- ESLint config exists (`packages/frontend/eslint.config.js`) but has no architectural boundary rules.
- No automated cycle detection in CI.

## Proposed Guardrails

### 1) Dependency boundary checks (new)
Tooling:
- Add `dependency-cruiser` in `packages/frontend` devDependencies.
- Add config file `packages/frontend/dependency-cruiser.cjs` (or `.js`) with explicit layer zones.

Rules (fail on error):
- Block `service/api` -> `store/state`.
- Block `store/state` -> `feature`.
- Block `shared-utils` -> non-`shared-utils`.
- Block `player/engine` -> `feature`.
- Block any `@capacitor/*` import under `packages/frontend/src/**`.
- Detect and fail on circular dependencies.

Suggested scripts:
- `pnpm --filter @familiar/frontend dep:check`
- `pnpm --filter @familiar/frontend dep:graph`

### 2) God-module budget check (new)
Use a lightweight script (`scripts/check-module-budgets.mjs`) to fail when thresholds are exceeded for newly changed files:
- LOC > 600
- imports > 20
- exports > 15

Policy:
- Existing oversized modules are allowlisted initially.
- New violations fail CI.

### 3) Boundary lint checks (optional ESLint complement)
- Add `eslint-plugin-boundaries` (optional if dependency-cruiser is adopted).
- Enforce import path restrictions by directory conventions.

## CI Integration Plan

### Step 1 (Non-blocking: 1-2 PRs)
- Add dependency check workflow job in warning mode (`continue-on-error: true`).
- Publish dependency report artifact.

### Step 2 (Blocking)
- Turn on fail mode for cycles and forbidden-layer imports.
- Keep god-module budget check as blocking for non-allowlisted files.

### Step 3 (Tightening)
- Shrink allowlist as refactor batches complete.
- Add PR comment summary with new violations and suggested owners.

## Fail Criteria
CI fails when any condition is true:
- A forbidden dependency edge is introduced.
- A circular dependency exists.
- A new or modified non-allowlisted file breaches module budgets.

## Reproducibility Commands
Run from repo root:

```bash
# 1) Identify large modules
find packages/frontend/src packages/web/src packages/ios/src -type f \( -name '*.ts' -o -name '*.tsx' \) -print0 | xargs -0 wc -l | sort -nr | head -n 40

# 2) Identify import-heavy modules
rg -n "^import " packages/frontend/src packages/web/src packages/ios/src -g"*.ts" -g"*.tsx" | awk -F: '{print $1}' | sort | uniq -c | sort -nr | head -n 40

# 3) Identify export-heavy modules
rg -n "^export " packages/frontend/src packages/web/src packages/ios/src -g"*.ts" -g"*.tsx" | awk -F: '{print $1}' | sort | uniq -c | sort -nr | head -n 40

# 4) Detect a known cycle (api/base <-> profileService) using project script once added
pnpm --filter @familiar/frontend dep:check
```
