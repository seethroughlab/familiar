# Health register

What is known to be wrong, unfinished or fragile **right now**, and what closes each item. This is
the current-state counterpart of the ADRs: they record decisions, this records debt. An item earns a
row by naming three things — the boundary that owns it, evidence that can be checked, and the
condition under which the row is deleted. Struck-through rows are not kept; history is in git.

Closed rows leave. Aspirations without an owner do not enter (see `docs/archive/` for the backlog
this replaced, and what was retired from it).

| Boundary | What | Evidence | Closes when |
|---|---|---|---|
| Web admin | Pending review and proposed changes have no web screen. Library has no Review section on purpose rather than a link to nowhere | `UNBUILT_DESTINATION_ITEMS` in `packages/frontend/src/app/routes.ts`; ADR-0126 point 4 | A Library → Review section exists, or ADR-0058's claim that the web app has one is superseded |
| Web admin / API | The Overview cannot show a duplicates count: it comes from a `POST` preview that takes ~40 s against 26k tracks | `packages/frontend/src/screens/DuplicatesPage.tsx` header; ADR-0126 follow-ups | A persisted count exists and the Overview lists it |
| API | `analysis_progress` on `GET /health/workers` is untyped in the schema (`{[key: string]: unknown}`) and narrowed by hand in the Analysis page | `packages/frontend/src/screens/analysis/StatusSection.tsx`; `packages/api-client/src/generated/types.gen.ts` | The Pydantic response model declares its four fields and the cast is deleted |
| Analysis | `GET /health/system` and `GET /library/stats` disagree on how many tracks are pending analysis (52 against 0 on the NAS on 2026-09-17). The web app reads the worker phase queues and neither of them | ADR-0126 Context | One source is authoritative and the other reads it, or the disagreement is documented as two different questions |
| Backend | `SCANNER_THREADS` is read from the environment at import in `backend/app/services/scanner.py`; ADR-0130 point 6 says environment enters through `Settings` | ADR-0130 Implementation, point 6 | The library-sync domain migrates under ADR-0130 |
| Backend | `backend/app/services/llm/handlers/playlists.py` calls route functions directly — a service reaching into `app.api.routes` | The one entry in `KNOWN` in `backend/scripts/lint_boundaries.py`, which fails if it stops being needed | The playlists domain migrates to an operation and the entry is removed |
| Web admin | The web app cannot set the library path or the API keys; both are environment variables. The Server → Health and Providers pages say so and name the variable | `backend/app/api/routes/settings.py` pops `music_library_paths`; ADR-0126 point 10 | A decision to accept `PUT /settings` for them, or an explicit decision that they stay environment-only |
| Frontend | `packages/frontend`'s own `tsc` reports errors that nothing gates on: `src/api/library.ts` names a type that does not exist and `src/audio/__tests__/engineContract.test.ts` predates the engine's capability shape. `vite build` strips types without checking | `cd packages/frontend && pnpm exec tsc -p tsconfig.json --noEmit` | Both are fixed and the type-check joins `make check` and CI |
| Tests | Backend pure tests are not labelled, so every `pytest` run needs `TEST_DATABASE_URL` even for tests that never connect | ADR-0128 Implementation, point 7 | ADR-0130's factory makes "does not import the assembled app" checkable, and pure tests get a marker |
| Tests | Playlist E2E specs skip when the fixture library has no playlists, so a run can pass by testing nothing | `test.skip(true, …)` in `packages/web/e2e/playlists.spec.ts` | The E2E fixture seeds the playlists the specs need and the skips are deleted |
| Security | The server token is off by default, and media cannot carry it. A reachable port is a public server | ADR-0045; `backend/app/api/auth.py` passes every request through when no token is configured | ADR-0045 point 5 is switched on with the media exemption decided, or the record is amended to say it will not be |
| Process | `AGENTS.md` and `CLAUDE.md` are two exhaustive agent guides that can disagree | ADR-0127 follow-up | One shared current source, included by both |
