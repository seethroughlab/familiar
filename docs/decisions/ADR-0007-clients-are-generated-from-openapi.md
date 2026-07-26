# ADR-0007: Clients Are Generated from the OpenAPI Schema

Status: proposed

Date: 2026-07-26

Extends [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md).

## Context

The backend exposes 241 route handlers across `backend/app/api/routes/`. The web client reaches them
through **hand-written axios wrappers** — 26 modules and 4,326 lines in
`packages/frontend/src/api/`, with roughly 195 call sites covering about 170 distinct path
templates, and request/response types declared by hand alongside each module (34 exported interfaces
in `api/library.ts` alone).

This works because there has been exactly one client. [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md)
adds a Swift client, and a future Windows client would be a third. Hand-writing that surface in
Swift — and then again in C# — is both a large amount of tedious work and a guarantee of silent
drift: a backend response field renamed in Python fails at runtime on a client nobody rebuilt.

The infrastructure to avoid this already exists and is unused. FastAPI generates OpenAPI for free,
and `/openapi.json`, `/docs`, and `/redoc` are live — `backend/app/main.py:450` explicitly excludes
them from the SPA catch-all. There is no customisation: no `openapi_url=`, no `custom_openapi()`, no
`generate_unique_id_function`. There is also no codegen pipeline anywhere in the repository.

The schema is in decent but not sufficient shape. Most handlers declare `response_model=`, shared
schemas live in `backend/app/api/schemas/tracks.py` and `common.py`, router `tags` are consistent, and
the error envelope is normalised globally in `main.py` with contract tests behind it
(`test_contract_error_shapes.py`, `test_contract_envelope_parity.py`). But a number of handlers
return a bare `dict`, which generates as an untyped `object` and defeats the purpose:

- `tracks/streaming.py::report_playback_error`
- `smart_playlists.py::get_available_fields`
- the status endpoints in `download.py`
- most of the action endpoints in `outputs.py`

Authentication imposes no complexity here. There is none — profile selection is a single
`X-Profile-ID` header (`backend/app/api/deps.py`), applied by an interceptor at
`packages/frontend/src/api/base.ts:167-172`.

## Decision

Native clients consume a **generated** API client, not a hand-written one.

1. **Generate from `/openapi.json`.** Swift now, for the `familiar-apple` repo; C# later, from the
   same schema, if and when Windows happens.

2. **Harden the schema first.** Replace bare `dict` returns with Pydantic response models in the
   handlers listed above. Untyped fields in a generated client are worse than no generation, because
   they look typed.

3. **Add `generate_unique_id_function`** to the FastAPI app so generated method names are readable
   rather than derived from paths.

4. **Generation is a checked-in build step, not a one-time scaffold.** The generated client is
   regenerated from the schema, and drift between schema and client must fail a build rather than
   surface at runtime.

5. **The existing TypeScript client is explicitly *not* migrated by this ADR.** It works, it is
   heavily used, and replacing ~195 call sites is unrelated risk. It may be migrated later on its own
   merits; that is a separate decision.

6. **Handlers deliberately outside the generated client:** audio streaming
   (`/tracks/{id}/stream` — range requests, handled by `URLSession` directly), SSE endpoints
   (`/chat`, map streams), and file downloads. Generated clients handle these badly; they are written
   by hand on each platform, which is a small and bounded set.

## Alternatives Considered

- **Hand-write the Swift client.** Rejected. Around 170 paths, and it drifts silently from the
  backend with no mechanism to detect it.
- **Adopt GraphQL.** Rejected. A wholesale backend rewrite to solve a problem that stock FastAPI
  already solves for free.
- **Share types via a hand-maintained schema document.** Rejected. That is the OpenAPI schema, except
  worse, because it can disagree with the implementation.
- **Migrate the TypeScript client at the same time.** Rejected as scope. It couples a risky
  ~195-site refactor to unblocking native work. Sequence them.
- **Generate only DTOs, hand-write the calls.** Rejected. DTO drift is the dangerous half; call-site
  ergonomics are the cheap half. Generating only the cheap half is backwards.

## Consequences

- **Positive:** The Swift client is generated rather than written, removing a large chunk of
  [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md)'s effort.
- **Positive:** Backend changes surface as client compile errors instead of runtime failures.
- **Positive:** A future Windows client gets its API layer for free, reinforcing
  [ADR-0006](ADR-0006-offline-ranking-is-precomputed-server-side.md)'s goal of making new platforms
  UI plus audio engine.
- **Positive:** Hardening the bare-`dict` handlers improves `/docs` for anyone reading the API.
- **Tradeoff:** The OpenAPI schema becomes a real contract. Loose typing that is currently harmless
  becomes a client-facing defect, and casual route changes get more expensive.
- **Tradeoff:** A generator dependency and build step enter the toolchain.
- **Tradeoff:** Two API client styles coexist — generated on native, hand-written on web — until and
  unless the web client migrates.
- **Follow-up:** Choose the Swift generator and verify its output against the profile-header
  interceptor pattern and the normalised error envelope.
- **Follow-up:** Audit for other loosely typed handlers beyond the four named here; the list came
  from a survey, not an exhaustive pass.
