# ADR-0173: Transports Share Operations and Generated Contracts

Status: accepted

Date: 2026-11-08

Implementation:

- **Backend pilot built 2026-11-09** (Phase 1). `app/operations/playlists.py` (`list_playlists`,
  `get_playlist`, `add_tracks`) and `app/operations/favorites.py` (`add`, `remove`) hold the five
  use cases the LLM/MCP tools shared with REST; `app/operations/errors.py` has the transport-free
  `PlaylistNotFound` and `TrackNotFound`, since rule 1 of `lint_boundaries.py` forbids
  `app.api.exceptions` there. The routes and `app/services/llm/handlers/playlists.py` are adapters,
  and `KNOWN` in `lint_boundaries.py` is empty. The handler's two workarounds went with it: passing
  `include_auto` explicitly because the route's `Query(...)` default arrived as a FastAPI object, and
  reading the playlist before and after an append to count what was added.
  `tests/test_playlist_operations.py` tests the behaviour once; route and tool tests keep their own
  concerns. **Two route defects surfaced while extracting:** `max(position) or -1` treated a
  playlist whose last position was 0 as empty, so the next track also got position 0; and an id
  repeated in one request was added twice. The operation fixes both, with tests.
- **Not done:** Phases 2–4, the frontend's 74 handwritten response types in `library.ts`,
  `discovery.ts`, `tracks.ts` and `playlists.ts`, and the check that stops new ones.

Extends [ADR-0129](ADR-0129-the-web-client-is-generated-from-the-openapi-contract.md) and
[ADR-0130](ADR-0130-the-backend-is-assembled-from-explicit-dependencies.md)

## Context

The backend boundary checker has one known exception:
`app/services/llm/handlers/playlists.py` calls functions in `app.api.routes.playlists` and
`app.api.routes.favorites`. An LLM adapter therefore depends on HTTP adapter signatures and
response choices.

The generated `@familiar/api-client` package is current, but the frontend still owns large
handwritten API modules and response interfaces. The undefined `RediscoverySuggestion` found by the
audit demonstrates how generated and handwritten contract ownership drift independently.

The answer is not a service class around every CRUD call. A shared operation earns its place when a
use case has multiple adapters or meaningful orchestration.

## Decision

1. Business use cases called by more than one transport live in an application operation layer.
   Operations accept domain inputs and explicit dependencies; they do not accept FastAPI requests,
   return HTTP responses, or import routes.
2. REST routes, LLM handlers, MCP tools, and jobs are adapters over those operations. HTTP schemas
   and LLM prose stay in their adapters.
3. Playlists and favorites are the pilot. Move use cases called by the LLM handler, then remove the
   sole `KNOWN` entry from `backend/scripts/lint_boundaries.py`.
4. Operation tests cover behavior once. Adapter tests cover authorization, serialization,
   validation, and transport-specific presentation.
5. Generated request, response, and error types own the browser transport contract. Handwritten
   types may model UI state or an intentional transformed view, but do not duplicate a response.
6. Thin handwritten adapters remain for cancellation, query defaults, authentication, URL
   construction, or stable UI transformations. Their signatures use generated types and their
   transformations are tested.
7. Frontend migration proceeds by domain: discovery/library, tracks, then playlists. A boundary
   check prevents new handwritten response contracts; existing domains may be temporarily
   allowlisted with removal conditions.
8. A second caller or meaningful orchestration triggers the next backend migration. Empty layers
   are not added preemptively.

## Phased Delivery

1. **Backend pilot:** extract playlist/favorites operations and remove the exception.
2. **Drift point:** migrate discovery/library to generated transport types.
3. **Broaden:** migrate tracks and playlists, shrinking the allowlist.
4. **Document:** add one worked example to the architecture guide.

**Exit condition:** boundary checking has zero known exceptions; playlists are tested at operation
and adapter levels; the three frontend domains have one transport contract; and new duplicate
response interfaces fail a check.

## Alternatives Considered

**Let LLM handlers call REST internally.** Rejected because HTTP is an adapter, not a domain API.

**Create a service layer for every resource.** Rejected because wrappers without shared behavior
add navigation without a meaningful boundary.

**Rewrite the frontend API layer at once.** Rejected because it mixes broad mechanical churn with
behavior changes.

**Use the generated SDK directly from components.** Rejected because query defaults, cancellation,
authentication, and view transformations are legitimate frontend policy.

## Consequences

- **Positive:** new transports reuse behavior without importing another transport.
- **Positive:** OpenAPI becomes the single browser wire-contract owner.
- **Positive:** handwritten modules have a clear behavioral purpose.
- **Tradeoff:** generated and handwritten modules coexist during migration.
- **Tradeoff:** operation and adapter tests overlap intentionally at different boundaries.
