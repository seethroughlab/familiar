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
| Backend | `SCANNER_THREADS` is read from the environment at import in `backend/app/services/scanner.py`; ADR-0130 point 6 says environment enters through `Settings` | ADR-0130 Implementation, point 6 | The library-sync domain migrates under ADR-0130 |
| Web admin | The web app cannot set the library path or the API keys; both are environment variables. The Server → Health and Providers pages say so and name the variable | `backend/app/api/routes/settings.py` pops `music_library_paths`; ADR-0126 point 10 | A decision to accept `PUT /settings` for them, or an explicit decision that they stay environment-only |
| Tests | Backend pure tests are not labelled, so every `pytest` run needs `TEST_DATABASE_URL` even for tests that never connect | ADR-0128 Implementation, point 7 | ADR-0130's factory makes "does not import the assembled app" checkable, and pure tests get a marker |
| Security | Media is exempt from the token gate (`MEDIA_ROUTES`, ADR-0045), so a stream or artwork URL works for anyone who holds it, for ever, and rotating the token does not stop it. The header, a media cookie and signed URLs are accepted and the clients send them (ADR-0176 Phases 2–3), but none is required while App Store builds that send nothing are offered. The derivable album-hash oracle is closed (Phase 1); the main API is protected by default (ADR-0171). Existing tokenless installations still serve everyone, and warn | `MEDIA_ROUTES` in `backend/app/api/auth.py`; `MEDIA_ENFORCED` in `backend/app/api/media_credentials.py`; `backend/app/exposure.py` | ADR-0176 Phase 4: once no offered App Store build lacks the media header, turn on `MEDIA_ENFORCED`, make media `Cache-Control: private`, remove this row |
| Process | A clean-container pass reaches `make check` from CONTRIBUTING alone (ADR-0175, 2026-11-09), but no person unfamiliar with the project has yet set up from it | ADR-0175 point 7 | A developer new to the project reaches `make check` with no undocumented step |
