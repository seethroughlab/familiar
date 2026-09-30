# ADR-0124: Generated API Types Stop at the Apple Client's Repositories

Status: accepted

Date: 2026-09-17

Implementation:
- **2026-09-19, `familiar-apple` #197 — the vocabulary, and casting as the first slice.** The
  follow-up's inventory and one vertical slice with mapping tests. By point:
  1. `ServerCastOutputsSource` no longer builds errors from `String(describing: output)`; each
     operation is a call plus a static mapping from the generated output to a domain result.
  3. The protocol is still `CastOutputsSource` in `FamiliarKit`, owned by `CastController`.
  4. `RepositoryError` (`Sources/FamiliarKit/RepositoryError.swift`): `unreachable(URLError.Code)`,
     `rejected(status:code:message:)`, `notFound`, `serverFailed(status:)`, `unavailable`,
     `malformed`. In `FamiliarKit`, beside the consumer-owned protocols it is thrown through.
     `ServerErrorCode` mirrors ADR-0129's stable names as a `String` enum so no generated type
     crosses in. `ServerErrorMessage.describe` words every case, reusing the transport sentences
     for `unreachable`. `Sources/FamiliarAppCore/GeneratedResponses.swift` is the one mapping: a
     thrown `ClientError` by its cause, a documented error case by its typed envelope, an
     undocumented status by number with the raw envelope read for `code` and `message`. 503 is
     `unavailable` — that is what `ServiceUnavailableError` means on this server, which
     `MusicMapStore` had been matching by number.
  5. `CastRepositoryTests` (14) construct generated outputs directly, no transport stub — the
     `ContractCompatibilityTests` shape. `RepositoryErrorMessageTests` (5) cover the wording.
  6. Inventory at the time: 21 files switch on generated outputs; `RowActions.swift` (12) is not
     one capability and should split by what it does before it moves; the other three
     `Server*Source` adapters (radio, ambient, metadata) still carry a private
     `unexpectedResponse(String)` and are the next slices.
  **Recorded, not fixed:** the generated `ErrorCode` is a closed `String` enum, so a server
  naming a code this build does not know fails the typed envelope's decode and the call reads as
  `malformed`, status lost. The fix is on the schema side (an open enum); until then a new code
  ships to the app before the server.

Extends [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md) and
[ADR-0122](ADR-0122-the-apple-client-has-explicit-module-boundaries.md).

## Context

ADR-0007 correctly chose `swift-openapi-generator`: the schema is the contract, operations and
wire models are generated, and backend changes become compile errors. The generated surface has
since widened from the original listening path to management, casting, ambient and other native
features under later decisions.

Generation solves wire-contract drift; it does not define the application API. Today many Apple
stores, services and views call generated methods directly and independently switch over generated
`.ok` and `.undocumented` output cases. The pattern appears in browse stores, detail stores,
library views, row actions, smart playlists, music-map stores, metadata sources, casting sources,
ambient sources and setup. Each call decides separately how a non-200 response becomes `nil`, a
literal sentence, a logged failure or an error shown to the listener.

This has three costs. A schema change ripples through presentation and feature code; equivalent
failures receive different treatment; and tests have to construct generated `Operations.*` and
`Components.Schemas.*` values even when the behavior under test is a domain decision. It also makes
the generated client look like the domain boundary, encouraging features to depend on the server's
current response shape.

The answer is not to hand-write HTTP calls. ADR-0007's generated transport and models remain the
only implementation of the JSON contract. The missing layer is an adapter from that contract to the
terms the Apple application uses.

## Decision

1. **Generated OpenAPI operations and schema types stop at repository implementations in
   `FamiliarAppCore`.** SwiftUI views, feature controllers and domain policy do not switch over
   generated output enums or expose generated models in their public APIs.

2. **Repositories are capability-oriented and domain-facing.** Initial capabilities include
   library browsing, playlists, favourites, playback reporting, radio suggestions, casting,
   ambient candidates and account/configuration checks. A repository may implement several closely
   related operations; there is no requirement for one protocol per endpoint or one omnibus client
   protocol.

3. **Repository protocols are owned by their consumers.** A feature states the smallest operations
   it needs in domain terms, and a generated-client adapter conforms. This keeps a feature test from
   mocking the whole server and prevents the adapter layer becoming a second generated client.

4. **Repositories return domain values and one normalized error vocabulary.** Transport failures,
   documented server errors, incompatible contracts, unavailable optional capabilities and decode
   failures are mapped once. The vocabulary preserves distinctions a caller can act on; it does not
   flatten every failure into a display string. User-facing wording remains at the presentation
   boundary through the existing `ServerErrorMessage` policy
   (`Sources/FamiliarKit/ServerErrorMessage.swift`) or its successor.

5. **The generated client remains reachable only where its shape is the behavior being tested.**
   `FamiliarAPITests` continues to test schema generation, middleware, transcoding and live slices
   against generated types. Repository contract tests test each mapping from generated output to
   domain result. Feature tests use repository doubles and domain values.

6. **Migration is operation by operation.** New generated API use enters through a repository.
   Existing direct calls move when their feature changes or when repeated response/error handling is
   consolidated. No flag-day conversion of the current call sites is required.

7. **ADR-0007's deliberate exceptions remain exceptions.** Audio range streaming, SSE and file
   transfer continue to use the transports their existing decisions require. They may conform to a
   domain-facing capability, but they are not forced through the generated client merely for
   uniformity.

8. **Repositories do not cache by default.** Storage and offline behavior remain decisions of their
   existing owners. A repository coordinates the server contract; combining it with a cache requires
   an explicit policy so “network answer,” “cached answer” and “merged answer” stay distinguishable.

## Alternatives Considered

- **Continue calling the generated client directly.** This is type-safe at the wire boundary and
  simple for the first call. At the current feature count it duplicates output switching and makes
  generated transport details part of every feature API.

- **Add generic helpers for `.ok` extraction and status handling.** A helper removes syntax but
  cannot decide whether a 404 means absent, stale, incompatible or erroneous for a particular
  capability. It would make semantically different operations look uniform without producing a
  domain boundary.

- **Wrap every generated operation one-for-one.** Rejected as a handwritten shadow client: the
  generator already supplies that surface. Repositories group operations by what the application
  is trying to do and translate only at the boundary.

- **Expose generated DTOs through repository protocols.** This improves mocking but keeps schema
  changes coupled to every consumer and leaves domain policy phrased in wire types. The adapter must
  perform the translation to earn its existence.

- **Replace the generated client with handwritten networking.** Rejected by ADR-0007's evidence.
  It restores silent contract drift and duplicates a surface the schema already describes.

- **Put repositories in `FamiliarKit` and make it depend on `FamiliarAPI`.** Rejected because it
  reverses the current useful property that domain and playback code do not know the server exists.
  AppCore is the composition boundary where both may meet.

## Consequences

- **Positive:** server-schema changes are absorbed at one adapter boundary instead of rippling into
  views and feature policy.
- **Positive:** equivalent failures are classified consistently while presentation retains control
  of wording.
- **Positive:** feature tests become smaller and describe domain behavior rather than generated
  enum construction.
- **Positive:** future clients can reuse domain contracts conceptually without copying Swift's
  generated surface.
- **Tradeoff:** every server-backed capability gains an interface and mapping code in addition to
  the generated operation.
- **Tradeoff:** careless repository design can become a large “API service”; consumer-owned narrow
  protocols and capability grouping are the guardrails.
- **Tradeoff:** generated and repository-facing call styles coexist during migration.
- **Follow-up:** inventory direct `Client` use in `familiar-apple` and migrate one vertical slice
  first, including mapping tests, before naming the rest of the repository set permanently.
