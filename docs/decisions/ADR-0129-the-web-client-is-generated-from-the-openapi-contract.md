# ADR-0129: The Web Client Is Generated from the OpenAPI Contract

Status: proposed

Date: 2026-09-17

Extends [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md), whose point 7 deliberately deferred
the TypeScript client migration, and [ADR-0113](ADR-0113-the-api-declares-a-contract-version.md), which
makes compatibility an explicit server promise.

## Context

The backend's Pydantic models generate a committed OpenAPI schema, and the Apple clients generate their
API surface from it. The web client is the exception: `packages/frontend/src/api/` hand-writes request
paths, payloads and 173 exported TypeScript types. A field can therefore exist in three forms — Pydantic,
OpenAPI and TypeScript — with only the first two checked against each other.

The frontend also derives control flow from prose. Its response interceptor
(`packages/frontend/src/api/base.ts:197-198`) distinguishes a missing server token from an invalid profile
by searching the error detail for `X-Familiar-Token`, `re-register` or `Invalid profile`. A copy edit can change whether the user sees a credential prompt or is returned to
profile selection without changing a status code or failing a build.

Generation alone does not make a useful frontend API. Components currently import transport modules
directly, and generated operation names and wire shapes are not necessarily the vocabulary a screen
should use. The missing layer is a small domain adapter, not another hand-written copy of the contract.

## Decision

1. **The committed `backend/openapi.json` generates the web transport client and DTOs.** The generator is
   `@hey-api/openapi-ts`, pinned to an exact version in the workspace. Generated output lives in a
   dedicated workspace package and is never edited by hand. Its TanStack Query plugin is what point 5's
   feature queries are built from; it is not used to generate hooks that components call directly.

2. **Generation is deterministic and checked.** CI regenerates the package from the committed schema and
   fails on a diff. Updating an API contract, its lock and its generated clients is one reviewable change.

3. **The generated client owns transport facts only:** paths, methods, parameters, headers, request and
   response bodies, media types and typed error envelopes. It does not own React Query, presentation
   models, notifications or navigation.

4. **Feature adapters own application vocabulary.** A feature may wrap generated calls in functions such
   as `libraryStatus`, `startLibrarySync` or `rotateServerToken`, and may convert wire DTOs into UI models.
   It may not redeclare the wire response by hand.

5. **Screens and components do not import the generated client directly.** They consume feature queries,
   mutations or domain adapters. This keeps cache keys, retries, invalidation and user-visible error
   behavior beside the feature rather than scattered through presentation components.

6. **Every actionable error carries a stable machine-readable `code`.** Codes use a documented enum-like
   namespace such as `SERVER_TOKEN_REQUIRED`, `INVALID_PROFILE` and `SYNC_ALREADY_RUNNING`. `message` and
   `detail` remain human-readable and may change without changing client behavior.

7. **The shared transport installs origin, server-token and profile-header behavior once.** Generated
   operations do not each learn authentication. Explicit per-request profile selection remains possible
   for replay or administrative operations, and an explicit value wins over the selected profile.

8. **Special transports stay hand-written at a named boundary.** Range audio/video, SSE, downloads and
   browser media elements are not forced through a generator that models them poorly. Their DTOs come
   from generated schema components where useful, and each exception is listed beside the generator
   configuration rather than discovered by call sites.

9. **Migration is vertical, not a flag day.** One feature moves at a time; its old types and wrapper leave
   in the same change. New JSON API work uses the generated path from acceptance onward.

## Alternatives Considered

**Keep the hand-written web API because TypeScript is close to JSON.** Rejected. Runtime permissiveness is
why drift survives: the browser accepts a changed payload until the particular field is read.

**Generate types but keep every request wrapper hand-written.** Better than the present state, but
rejected as the target. Paths, parameters, methods and response cases drift too; DTOs are only part of the
contract.

**Let components call the generated client directly.** Rejected. It replaces one kind of coupling with
another and spreads cache and error policy through the component tree.

**Adopt GraphQL or a new RPC protocol.** Rejected. The existing OpenAPI contract is already mature,
versioned and consumed by shipped clients.

## Consequences

- **Positive:** backend contract changes become compile-time or generated-diff events in the web client.
- **Positive:** English error text stops being control flow.
- **Positive:** future clients share one transport contract while retaining platform-specific application
  models.
- **Tradeoff:** generated code enters the web build, and `@hey-api/openapi-ts` becomes a pinned build
  dependency whose upgrades are their own reviewable diff.
- **Tradeoff:** old and new wrappers coexist during migration.
- **Tradeoff:** loosely typed endpoints become visible debt because generation cannot make an honest type
  from an unspecified response.
- **Follow-up:** route-local Pydantic schemas move into domain schema modules only when reuse or generator
  naming requires it; this ADR does not move 256 classes for cosmetic uniformity.
