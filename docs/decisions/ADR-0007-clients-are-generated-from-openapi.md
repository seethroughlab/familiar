# ADR-0007: Clients Are Generated from the OpenAPI Schema

Status: accepted

Date: 2026-07-26

Implementation:
- Decision points 1–4 and 6 were revised before acceptance, after measuring the live schema. The
  original point 1 said "Swift now, for the `familiar-apple` repo", which contradicts
  [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) — that repo begins *after* this
  ADR is stable. Points 2 and 3 are new; the Context's estimate of four loose handlers was an
  undercount, as its own follow-up predicted.
- Phase 1 — schema hardening, operationIds and `scripts/lint_openapi.py`, on branch
  `feat/adr-0007-openapi-schema`. Longest operationId 95 → 45 characters; seven endpoints stopped
  advertising `application/json` for audio, images, zips and SSE; two handlers and four model fields
  typed; `SimilarArtistInfo` de-duplicated into `app/api/schemas/artists.py`. The lint was verified
  to fail by deliberately adding an untyped in-scope handler.
- Phase 2 — generating the Swift client — is not started, and waits on `familiar-apple`.
- Burn-down remaining: 50 out-of-scope untyped operations and one collision-mangled schema name
  (`ImportPreviewResponse`, declared in two modules), allowlisted in the lint.

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

1. **Generate from `/openapi.json`**, in two phases. Swift for the `familiar-apple` repo, then C#
   later from the same schema if Windows happens.

   The original wording said "Swift now", which was not achievable:
   [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) places the creation of
   `familiar-apple` *after* this ADR is stable, so 0007 cannot deliver into a repo it must precede.
   - **Phase 1 — the schema.** Readable operationIds, honest media types, typed responses across the
     generated surface, and a lint that stops it regressing. Independently verifiable with no client.
   - **Phase 2 — the client.** Generation itself, once `familiar-apple` exists and its structure can
     inform the generator choice.

2. **The generated surface is the native v1 listening path, not the whole API** — tags `tracks`,
   `library`, `playlists`, `smart-playlists`, `profiles`, `favorites`, `chat`, `mixtapes`, `ambient`.
   Management surfaces stay web-only under
   [ADR-0002](ADR-0002-web-app-is-the-management-surface.md) and will never need a Swift client,
   which is fortunate: they are where the untyped responses concentrate.

3. **Non-JSON endpoints must declare their real media type.** Excluding them is not enough. Seven
   endpoints — audio streaming, artwork, avatars, mixtape downloads and two SSE streams — declared
   `application/json`, so a generated client would have tried to JSON-decode an MP3. A schema that
   misdescribes an endpoint is worse than one that leaves it untyped, because it looks correct.

4. **Harden the schema first.** Replace bare `dict` returns with Pydantic response models, and type
   model fields that would otherwise generate as `Any`. Untyped fields in a generated client are
   worse than no generation, because they look typed.

   Fields that are genuinely free-form — arbitrary LLM tool-call payloads, opaque render progress
   read back from Redis, polymorphic smart-playlist rule values — are recorded as exceptions with a
   reason rather than modelled speculatively.

5. **Add `generate_unique_id_function`** to the FastAPI app so generated method names are readable
   rather than derived from paths.

6. **Regressions must fail a build.** Until a client exists there is nothing to diff against, so the
   check is a schema lint (`backend/scripts/lint_openapi.py`): no new untyped response, no missing
   tag, no duplicate or over-long operationId, no endpoint claiming JSON while returning binary.
   Existing out-of-scope looseness is allowlisted as a burn-down list, so adding to it is a visible
   decision in review. Once the client is generated, the same principle extends to schema-vs-client
   drift.

7. **The existing TypeScript client is explicitly *not* migrated by this ADR.** It works, it is
   heavily used, and replacing ~195 call sites is unrelated risk. It may be migrated later on its own
   merits; that is a separate decision.

8. **Handlers deliberately outside the generated client:** audio streaming
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
