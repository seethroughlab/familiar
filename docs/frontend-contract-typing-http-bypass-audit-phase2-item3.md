# Phase 2 Audit: Contract Typing Gaps + Direct HTTP Bypass Inventory

## Scope
This document covers Phase 2 checklist item 3:
- Identify contract typing gaps and direct HTTP usage bypassing API modules.

## Findings

### 1) Direct HTTP bypass of `api/*` modules is still widespread (`P1`)
Evidence:
- 32 direct `fetch(...)` call sites outside `packages/frontend/src/api/*`.
- 3 additional direct transport call sites (`XMLHttpRequest`/`EventSource`) outside `api/*`.
- High-impact bypass examples:
  - `packages/frontend/src/components/Chat/ChatPanel.tsx` (`/chat/status`, `/chat/stream`)
  - `packages/frontend/src/components/Settings/MissingTracksPanel.tsx` (`/library/missing*` CRUD)
  - `packages/frontend/src/components/Import/useImportSession.ts` and `packages/frontend/src/components/Import/ImportModal.tsx` (`/library/import/preview`, `/library/import/execute`)
  - `packages/frontend/src/components/Library/browsers/MusicMap.tsx` and `packages/frontend/src/components/Library/browsers/UMAPExplorer/UMAPExplorer.tsx` (SSE map streaming)
  - `packages/frontend/src/services/profileService.ts`, `packages/frontend/src/services/syncService.ts`, `packages/frontend/src/services/libraryCache.ts`, `packages/frontend/src/services/remoteLogService.ts`
  - `packages/frontend/src/stores/artworkStore.ts`

Impact:
- Transport behavior (error mapping, headers, retry/offline handling, observability) is inconsistent by call path.
- UI components remain coupled to endpoint details.

Recommendation:
- Move non-binary app API calls behind typed `api/*` modules.
- Keep direct transport only for documented exceptions (SSE/stream/binary transfer), wrapped by typed service adapters.

### 2) API coverage gaps force bypasses for active features (`P1`)
Evidence:
- No dedicated API modules for active endpoint families currently called directly:
  - chat status/stream
  - missing-tracks maintenance routes
  - remote frontend logs query/delete
  - library map streaming endpoints
  - import preview/execute workflow
- `artworkStore` directly calls `/artwork/queue/batch` and `/artwork/status/batch` while typed artwork API helpers exist in `packages/frontend/src/api/metadata.ts` (`artworkApi.queueBatch`), indicating split contract ownership.

Impact:
- Contract definitions are duplicated between stores/components and `api/*`.
- Runtime behavior can diverge silently when backend response shape changes.

Recommendation:
- Add missing domain clients (`chatApi`, `missingTracksApi`, `diagnosticsLogsApi`, `importSessionApi`, `mapStreamApi`).
- Rewire `artworkStore` to consume the existing artwork API surface (or promote a single canonical artwork client).

### 3) Contract typing is too permissive in core API models (`P1`)
Evidence:
- `packages/frontend/src/api/admin.ts` exposes large `Record<string, unknown>` blocks (`system_info`, `system_health`, `library_stats`, logs/failures/settings summary).
- `packages/frontend/src/api/backup.ts` uses `Promise<Record<string, unknown>>` for export payload.
- Multiple API domain models rely on `unknown` payload fields (`api/metadata.ts`, `api/playlists.ts`, `api/analysis.ts`).

Impact:
- TypeScript cannot protect consumers from schema drift.
- Consumers perform unsafe assertions and custom parsing.

Recommendation:
- Replace broad `Record<string, unknown>`/`unknown` with discriminated DTOs for top-used fields.
- Keep extensibility via typed `extra?: Record<string, unknown>` at edges, not as entire payloads.

### 4) Consumer-side ad hoc parsing/casting hides contract drift (`P1`)
Evidence:
- Chat stream handler switches on untyped `Record<string, unknown>` and casts fields per case in `packages/frontend/src/components/Chat/ChatPanel.tsx`.
- SSE handlers parse JSON directly without runtime guards in:
  - `packages/frontend/src/components/Library/browsers/MusicMap.tsx`
  - `packages/frontend/src/components/Library/browsers/UMAPExplorer/UMAPExplorer.tsx`
- Diagnostics rendering requires repeated consumer-side casts from unknown (`packages/frontend/src/components/Settings/SystemStatus.tsx`).

Impact:
- Invalid payloads fail late in UI logic.
- Refactors are fragile because type safety is bypassed at parse boundaries.

Recommendation:
- Introduce parse/validation adapters at ingress boundaries (stream events + diagnostics payloads).
- Emit typed unions for stream events (e.g., `ChatStreamEvent`, `MapStreamEvent`).

### 5) Type ownership is duplicated for import flow contracts (`P2`)
Evidence:
- `packages/frontend/src/components/Import/ImportModal.tsx` redefines interfaces already exported by `packages/frontend/src/components/Import/types.ts` (`TrackPreview`, `PreviewResponse`, `EditableTrack`, etc.).

Impact:
- Two local sources of truth can drift without compiler errors.

Recommendation:
- Enforce single contract source (`Import/types.ts`) and import types in `ImportModal.tsx`.

## Decision-Ready Next Actions
1. Create missing API clients for chat, missing-tracks, import-session, diagnostics logs, and map stream.
2. Migrate component/store direct HTTP calls to those clients, leaving documented exceptions only.
3. Define typed stream event unions and parser helpers for chat + map SSE/event payloads.
4. Tighten `admin` and `backup` API contracts by replacing broad `Record<string, unknown>` payloads with explicit DTOs.
5. Add lint guardrail: forbid `fetch/getApiUrl` in `components/**` and `stores/**` except approved allowlist paths.
6. Remove duplicate import types from `ImportModal.tsx` and consume shared import types module.

## Reproducibility Commands
Run from repo root:

```bash
# Direct transport usage outside api/*
rg -n "\bfetch\(|\bnew EventSource\(|\bxhr\.open\(" packages/frontend/src/components packages/frontend/src/stores packages/frontend/src/services --glob '*.{ts,tsx}'

# Permissive contract shapes in api layer
rg -n "Record<string, unknown>|\bunknown\b|Promise<Record<string, unknown>>" packages/frontend/src/api --glob '*.{ts,tsx}'

# Ad hoc JSON parse/cast hotspots
rg -n "JSON\.parse\(|as Record<string, unknown>|as .*Response" packages/frontend/src/components packages/frontend/src/services --glob '*.{ts,tsx}'
```
