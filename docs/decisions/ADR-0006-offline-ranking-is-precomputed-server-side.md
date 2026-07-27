# ADR-0006: Offline Ranking Is Precomputed Server-Side

Status: accepted

Date: 2026-07-26

Extends [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md).

## Context

[ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md) puts candidate ranking on the
server. That is correct when connected — and useless offline, which is one of the three symptoms
motivating this whole effort.

Ambient mode already supports offline operation. **Three premises in the original draft of this
Context were wrong**, found while planning implementation and recorded here so nobody re-derives
them:

1. **The offline path does not reimplement the scorer.**
   `packages/frontend/src/player/ambient/offlineScoring.ts` (158 lines) imports only `db`, types and
   `suggestSnippetWindow`. It has no key table and no `parseKey`. Its entire scoring is a base of
   `0.5`, `-0.25` for a recently-heard artist, `+0.05` for a differing one, over a random shuffle —
   `cachedTrackToDescriptor` nulls every analysis feature. Offline ambient does not attempt harmonic
   matching, energy proximity or embedding similarity at all.

2. **The duplicated scorer that does exist is dead code.**
   `packages/frontend/src/player/ambient/compatibilityScoring.ts` (156 lines) does contain a faithful
   port of `score_candidate()` and its key-compatibility table — but `scoreCandidate` and
   `keyCompatibility` have **zero call sites** anywhere in the repository. Only `parseKey`,
   `keyToMidiNote` and `getScaleNotes` are live.

3. **`compatibilityScoring.ts` cannot be retired by this ADR.** Its own header claims it is shared
   between `offlineScoring.ts` and `transitionRecipes.ts`; the import graph shows only
   `transitionRecipes.ts` uses it, and for *audio synthesis* — `computeDroneTarget()` takes a root
   and fifth, `buildMotifRecipe()` takes scale degrees. That is not ranking and cannot be replaced by
   a neighbour manifest.

So the deduplication argument is weaker than drafted, and the real case is stronger: **offline
ranking today is barely ranking.** This ADR does not merely remove a duplicate scorer, it gives
offline listening the same ranking quality as online for the first time.

Drift is nonetheless already present and worth recording as evidence for the general argument: the
TypeScript `parseKey` accepts `"Am"` and `"A minor"` but rejects `"A min"` and `"A maj"`, which the
Python `_build_key_aliases()` accepts. Two implementations that merely intend to agree have already
diverged on input handling. `offlineScoringHelpers.ts` is a third copy — a self-described mirror of
`suggest_snippet_window`.

A latent bug points the same way: `offlineScoring.ts` reads `db.cachedTracks` — all cached
metadata — rather than `db.offlineTracks`, so offline ambient can select a track whose audio was
never downloaded.

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
   [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md). **N = 10**, chosen against
   measured size: a 1,719-track offline set yields roughly 4 MB across all profile/preset
   combinations.

2. **Clients perform lookup, not computation.** Given the current track, an offline client reads its
   neighbour list and filters against anything already played recently. That is the whole client-side
   algorithm.

3. **The client supplies the offline set; the server holds no record of it.** The original draft
   assumed the server knew which tracks a device had downloaded. It does not — there is no such
   model, `Profile.device_id` is marked legacy, and downloads are indistinguishable from plays
   because both hit `GET /tracks/{id}/stream`. So the manifest is **requested, not pushed**: the
   client posts its offline track IDs and receives a manifest, triggered by the existing
   `offline-tracks-updated` event that already refreshes `connectivityStore.offlineTrackIds`.

   A server-side record of downloads was rejected: it needs a device identity that does not exist,
   and it would drift from reality whenever a download fails or storage evicts a track — leaving the
   server confidently wrong about what is playable offline.

4. **`offlineScoring.ts` is retired** once ambient mode consumes the manifest.
   `compatibilityScoring.ts` **stays** — see Context point 3; `transitionRecipes.ts` needs it for
   synthesis. Its dead `scoreCandidate` and `keyCompatibility` are removed separately, as they are
   unreferenced today and do not depend on this ADR.

5. **The manifest is generated per weight profile and per filter preset.** `AMBIENT` and `RADIO`
   both work offline without the client knowing what a weight is. Presets change the eligible pool
   (`_build_filter_conditions`) and the client already passes one, so the matrix is four ambient
   presets plus radio. The manifest also carries an eligible-seed list per preset, since
   `pickOfflineSurpriseSeed` needs one.

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
- **Record each profile's downloaded tracks server-side, and precompute on a schedule.** Rejected,
  and this is the alternative closest to the original draft of decision point 1. It needs a device
  identity the codebase does not have — `Profile.device_id` is marked legacy and one profile on three
  devices has three different offline sets — plus a new model and a reporting path. Worse, the
  server's record would drift from reality whenever a download fails or storage evicts a track, and a
  server confidently wrong about what is playable offline is a harder failure to notice than one that
  simply asks.
- **Derive the offline set from auto-download playlists and favourites.** Rejected. The server does
  know that intent (`Playlist.auto_download`, `profile.settings["favorites_auto_download"]`), but it
  is intent rather than state: it covers tracks that never downloaded and misses albums downloaded by
  hand, so offline ranking would degrade invisibly — the exact failure mode this ADR exists to
  prevent.

## Consequences

- **Positive:** This is the single largest reduction in future per-platform work in the whole
  programme. Adding Windows later requires no ranking code whatsoever.
- **Positive:** Offline and online ranking are guaranteed identical, because they are the same code
  path. Today they are two implementations that merely intend to agree.
- **Positive:** Offline ambient gains real ranking — harmonic compatibility, energy, embeddings —
  where today it is a shuffle with an artist penalty. This is the larger benefit, and it was not the
  one originally drafted.
- **Positive:** Deletes 158 lines (`offlineScoring.ts`), not the 314 originally claimed;
  `compatibilityScoring.ts` stays for synthesis. A further ~90 dead lines inside it can go
  independently. The Swift and Windows clients still inherit no ranking code, which is the point.
- **Tradeoff:** Manifest size grows with the offline set — O(tracks × N × profiles × presets).
  Measured at ~4 MB for a 1,719-track set at N = 10; remeasure before assuming it holds at 5,000.
- **Tradeoff:** Recomputation must be reliable. A stale manifest degrades transition quality
  invisibly. It should be versioned so a client can detect staleness.
- **Tradeoff:** A newly downloaded track is unusable as a seed until the manifest updates.
- **Follow-up:** ~~Choose N, and measure manifest size~~ — resolved at acceptance: N = 10, ~4 MB for
  a 1,719-track set across all profile/preset combinations.
- **Follow-up:** ~~Decide the delivery mechanism~~ — resolved at acceptance: a dedicated endpoint
  the client posts its offline set to. `syncService` was the wrong vehicle; it is an outbound
  `pendingActions` replay queue with no inbound path.
- **Follow-up:** Fix `offlineScoring.ts` reading `db.cachedTracks` rather than `db.offlineTracks`.
  Building the manifest from genuinely-downloaded IDs resolves this incidentally, but it should be
  asserted by a test rather than assumed.
- **Follow-up:** Decide whether the manifest should carry `root_midi` and `scale_notes` per track, so
  `transitionRecipes.ts` stops parsing keys and `compatibilityScoring.ts` can be deleted entirely.
  That would deliver the "no key-parsing code on any client" outcome this ADR gestures at but does
  not reach.
