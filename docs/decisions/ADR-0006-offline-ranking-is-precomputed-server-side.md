# ADR-0006: Offline Ranking Is Precomputed Server-Side

Status: proposed

Date: 2026-07-26

Extends [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md).

## Context

[ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md) puts candidate ranking on the
server. That is correct when connected — and useless offline, which is one of the three symptoms
motivating this whole effort.

The existing answer to that problem is the one this ADR exists to avoid repeating. Ambient mode
already supports offline operation, and it does so by **reimplementing the scorer on the client**:

- `packages/frontend/src/player/ambient/offlineScoring.ts` — 158 lines
- `packages/frontend/src/player/ambient/compatibilityScoring.ts` — 156 lines, containing a second
  copy of the Camelot key-compatibility table and `parseKey()`

So the harmonic-mixing logic exists twice today: once in Python (`backend/app/services/ambient.py`)
and once in TypeScript. The file header of `compatibilityScoring.ts` even notes it is shared between
`offlineScoring.ts` and `transitionRecipes.ts` — the duplication is deliberate and understood, but it
is duplication nonetheless.

[ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) adds a Swift client. A future
Windows client adds a fourth. Four independent implementations of a scoring function that must agree
will not agree. They will drift silently, and the failure mode — subtly worse transitions on one
platform when offline — is close to undetectable.

The insight that dissolves the problem: **when offline, the candidate pool is small and known in
advance.** It is exactly the set of tracks the profile has downloaded. That set changes only when a
download completes or is removed. There is no reason to rank it at playback time on the device;
it can be ranked once, on the server, ahead of time.

## Decision

The server precomputes offline ranking. Clients carry **no ranking code on any platform, ever**.

1. **An offline neighbour manifest.** For each track in a profile's offline set, the server computes
   its top-N most compatible neighbours **drawn only from that same offline set**, with scores,
   using the identical `score_candidate()` path as
   [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md).

2. **Clients perform lookup, not computation.** Given the current track, an offline client reads its
   neighbour list and filters against anything already played recently. That is the whole client-side
   algorithm.

3. **The manifest is recomputed when the offline set changes** — a download completing, a track
   removed, an auto-download playlist refreshing — and delivered alongside existing offline metadata.

4. **`offlineScoring.ts` and `compatibilityScoring.ts` are retired** once ambient mode consumes the
   manifest, removing the second copy of the Camelot table rather than adding a third and fourth.

5. **The manifest is generated per weight profile**, so `AMBIENT` and `RADIO` both work offline
   without the client knowing what a weight is.

## Alternatives Considered

- **Port the scorer to Swift, and later C#.** Rejected. Four implementations of the same function
  that must agree, with silent drift as the failure mode. This is the specific outcome the ADR
  prevents.
- **Compile the scorer once to WebAssembly and embed it everywhere.** Rejected as disproportionate.
  It solves drift but adds a toolchain, a build step, and a binary artefact to every client for a
  function whose inputs are known ahead of time.
- **No offline radio at all.** Rejected. Offline reliability is a stated primary symptom; shipping a
  headline feature that silently stops working in airplane mode is the wrong trade.
- **Cache the last N online responses and replay them.** Rejected. It only covers tracks already
  played and degrades to nothing on a long offline session — precisely when it is most needed.
- **Ship raw features and let clients score.** Rejected. That is the port option with extra steps;
  the scoring function still lives on every client.

## Consequences

- **Positive:** This is the single largest reduction in future per-platform work in the whole
  programme. Adding Windows later requires no ranking code whatsoever.
- **Positive:** Offline and online ranking are guaranteed identical, because they are the same code
  path. Today they are two implementations that merely intend to agree.
- **Positive:** Net deletion of 314 lines of TypeScript rather than addition of a Swift equivalent.
- **Tradeoff:** Manifest size grows with the offline set — O(tracks × N). Bounded by keeping N small;
  needs measuring against a large offline library before assuming it is free.
- **Tradeoff:** Recomputation must be reliable. A stale manifest degrades transition quality
  invisibly. It should be versioned so a client can detect staleness.
- **Tradeoff:** A newly downloaded track is unusable as a seed until the manifest updates.
- **Follow-up:** Choose N, and measure manifest size against a realistic offline set before
  finalising.
- **Follow-up:** Decide the delivery mechanism — bundled with the offline metadata sync, or a
  dedicated endpoint.
