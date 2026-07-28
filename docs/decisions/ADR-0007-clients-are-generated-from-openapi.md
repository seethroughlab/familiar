# ADR-0007: Clients Are Generated from the OpenAPI Schema

Status: accepted

Date: 2026-07-26

Extends [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md).

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
- Phase 1.5 — the schema was made to describe the *contract*, not just response bodies, on branch
  `feat/adr-0007-schema-contract`. Phase 1 had hardened bodies and stopped; three things a
  generated client needs were still undescribed, and each would have made it wrong on its first
  request:
  - **The profile header did not appear in the schema at all.** `deps.py` reads `X-Profile-ID` off
    the raw request, and a search for `Header(` across `app/api/` returned nothing, so FastAPI
    emitted no parameter and no security scheme. This ADR's Context says "Authentication imposes no
    complexity here" — true of the model, and beside the point, because generation consumes the
    schema rather than the model. Now an `APIKeyHeader` depended on by both profile dependencies;
    102 operations carry the requirement and behaviour is unchanged.
  - **Errors were undocumented, and the one documented error was wrong.** Only 200 and FastAPI's
    automatic 422 appeared, and that 422 described `HTTPValidationError` while the overridden
    handler returns the Familiar envelope — so the single error shape a client would have modelled
    is the one shape the server never sends. `ErrorEnvelope` is now a component, attached at the 32
    `include_router` calls.
  - **Control flow was invisible**, including the 409 that `PUT /queue/session` returns to mean
    "resend the reservoir in full" ([ADR-0003](ADR-0003-server-owns-the-playback-queue.md) point 4).
- Phase 1.6 — the surface was reconciled with ADR-0001's v1 scope, and three published facts turned
  out to be stale. `ambient`, `mixtapes` and `outputs` were removed; that also restored the
  invariant ADR-0001's readiness audit claimed, since the five allowlisted untyped operations that
  had drifted *inside* the surface were all `outputs/zones/*`.

  **The schema was also not deterministic.** Two modules declared `ImportPreviewResponse`, and
  which one FastAPI fully qualified varied between runs — so consecutive builds produced different
  schemas and a generated client would have had a type renamed under it. Renaming the
  export-import twin to `ProfileImportPreviewResponse`, matching its sibling
  `LibraryImportPreviewResponse`, removed the collision; the schema now hashes identically across
  runs. This had to be found before pinning an artifact, and would not have been visible without
  one.

- Phase 2 — **the generator is swift-openapi-generator**, resolving the first follow-up below. It
  runs as a SwiftPM build plugin in `familiar-apple`, so no generated Swift is committed and a
  backend change surfaces as a compile error. The schema is pinned to `backend/openapi.json` by
  `scripts/dump_openapi.py`, with `make openapi-check` failing in CI if it drifts — a separate
  repo with a different toolchain cannot import the app the way the lint does.

  Proven on one tag first (`favorites`, seven operations) against the live NAS rather than
  designed in the abstract. Three defects surfaced that no amount of planning would have found,
  and all three were invisible from the Python side:

  - **35% of the schema would have been silently dropped.** The generator discards any property
    whose `anyOf` contains a bare `{"type": "null"}` — exactly how Pydantic v2 spells `X | None`.
    487 of 1,374 properties, including `title`, `artist` and `duration_seconds`. The client
    compiled and looked complete. `dump_openapi.py` now normalises those to the canonical 3.1
    form.
  - **Timestamps were not RFC 3339.** Naive UTC datetimes serialised without an offset, because
    the columns are TIMESTAMP WITHOUT TIME ZONE. Swift rejected them; **JavaScript accepted them
    and parsed them as local time**, so the web app had been displaying every server timestamp
    shifted by the viewer's UTC offset for as long as those fields existed. Fixed at the API
    boundary with `to_rfc3339` and a `UTCDateTime` annotated type.
  - **Foundation is stricter than RFC 3339.** Neither of its ISO-8601 option sets accepts both
    fractional and whole-second timestamps, so the client carries a small transcoder. That one is
    a client accommodation, not a server defect.

  The second follow-up — verifying against the profile-header pattern and the error envelope — is
  what the slice tests assert, and both required phase 1.5 to exist first.
- Widening from eight tags to the remaining 108 operations is now a config change, not a design
  question.
- Burn-down remaining: 50 untyped operations, all outside the generated surface, allowlisted in the
  lint. The mangled-schema allowlist is now empty — see phase 1.5.

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
   `library`, `playlists`, `smart-playlists`, `profiles`, `favorites`, `chat` and `queue`: eight
   tags, 108 operations. Management surfaces stay web-only under
   [ADR-0002](ADR-0002-web-app-is-the-management-surface.md) and will never need a Swift client,
   which is fortunate: they are where the untyped responses concentrate.

   `ambient`, `mixtapes` and `outputs` are **not** generated, and the lint records why next to the
   surface definition. The first two are out of v1 by
   [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) point 5; casting does not
   appear in its point 4 scope. All three were in the surface for a time — see the phase 1.5 note
   in the Implementation block.

   `library` stays whole even though it mixes roughly 18 listening operations with 17 management
   ones. Tags cannot express that split, and the cost of the extra 17 is dead generated code
   rather than a defect.

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
- **Resolved:** ~~Choose the Swift generator and verify its output against the profile-header
  interceptor pattern and the normalised error envelope~~ — swift-openapi-generator, verified
  against a live server on the `favorites` slice. See the Implementation block.
- **Follow-up:** The 49 timestamp fields still declared as plain `string` rather than
  `format: date-time` now carry a `Z`, but a generated client models them as strings. Typing them
  would let clients decode dates, at the cost of a wire-compatible schema change.
- **Follow-up:** Audit for other loosely typed handlers beyond the four named here; the list came
  from a survey, not an exhaustive pass.
