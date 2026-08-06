# ADR-0035: Weighted Shuffle Is a Preset the Server Applies

Status: proposed

Date: 2026-08-06

Extends [ADR-0027](ADR-0027-shuffle-and-repeat-are-listener-modes.md) and
[ADR-0029](ADR-0029-the-server-stores-no-listener-preferences.md).

## Context

The web app has four named shuffle modes and the Apple clients have none. Unusually for this set,
the server half is not merely designed but finished and tested, and nothing needs to be added to the
generated surface to use it.

`backend/app/services/taste_weighting.py` (145 lines) holds
`VALID_SHUFFLE_PRESETS = {"rediscover", "fresh_finds", "comfort_zone", "deep_dive"}` and a
`ShufflePresetWeights` over five axes — `play_count_dir`, `recency_dir`, `newness_dir`,
`favorites_boost`, `variety_strength`:

| preset | play count | recency | newness | favourites | variety |
|---|---|---|---|---|---|
| `rediscover` | +1.0 | −1.0 | 0 | 1.0 | 0.5 |
| `fresh_finds` | −1.0 | 0 | +1.0 | 1.0 | 0.7 |
| `comfort_zone` | +1.0 | +0.5 | 0 | 3.0 | 0.2 |
| `deep_dive` | −1.0 | −1.0 | 0 | 1.0 | 0.8 |

`GET /api/v1/tracks/ids` takes `shuffle_preset` as a query parameter
(`backend/app/api/routes/tracks/listing.py:51`), outer-joins `ProfilePlayHistory` and
`ProfileFavorite`, computes a weight per track and draws the order by Efraimidis–Spirakis weighted
sampling (`:133` onward), then spaces same-artist runs with `apply_artist_variety`.

**The endpoint is tagged `tracks`, and `tracks` is already in
`Sources/FamiliarAPI/openapi-generator-config.yaml`.** So there is no new tag, no lint burn-down,
no `openapi.json` re-vendor and nothing for
[ADR-0014](ADR-0014-the-generated-surface-widens-to-management.md) to widen. The Swift client can
call this today. That makes it the cheapest thing in the current set of proposals, and worth saying
plainly so it is not scheduled as though it were large.

The gap is already recorded on the Apple side. `PlaybackSessionSnapshot`'s own comment:

> ADR-0003 point 8 records what losing `queue_source` costs — listening-event context and the
> weighted shuffle preset — and the Apple client has never had it.

**The part that is not obvious is where the weighting happens, and it is not a free choice.** The
weights read play counts, last-played timestamps, date-added and favourites *across the whole
library*, normalised against the maximum play count. The Apple client holds none of that: it pages
tracks at 50 ([ADR-0021](ADR-0021-track-lists-on-the-mac-are-sortable-tables.md)) and its local
snapshot deliberately omits the reservoir. A preset is therefore **not a permutation the client can
compute**. It is an order the client asks for.

That distinguishes it cleanly from what ADR-0027 governs. `isShuffled` permutes a queue the client
already holds; `QueueShuffle.enabling` shuffles `order[(cursor+1)...]` in memory. A preset chooses
*which tracks are in the queue at all, and in what order*, before any of that runs. Two mechanisms,
both called shuffle, and conflating them is how the ADR-0027 defect would arrive in a new place.

## Decision

1. **A weighted shuffle preset is a listener preference, held locally.** Per ADR-0029 the server
   stores none, so the preset lives beside the ADR-0027 modes on this device. It reaches the server
   only as a query parameter on a request, never as state.

2. **The preset selects the queue; `isShuffled` permutes it. They are different mechanisms and
   both can be on at once.** When a queue is built with a preset, `QueueShuffle.enabling` is
   **not** then applied on top of it. Permuting a weighted order discards the weighting and leaves
   a control that appears to work and does nothing — the exact shape of the defect ADR-0027 exists
   to fix.

3. **`logicalQueue` holds the weighted order as given.** `QueueShuffle.disabling` therefore
   straightens out to the order the server returned, which is an order that really existed. This is
   ADR-0027 point 2's split honoured rather than re-collapsed: the mode is what the listener chose,
   the order is a fact about the queue.

4. **The preset applies where a queue is drawn from the library, and nowhere else.** That is
   `LibraryView.shuffleLibrary()` (`:159`) and `widenQueueToLibrary(startedWith:)` (`:262`), plus
   the Home row from [ADR-0032](ADR-0032-the-apple-clients-get-a-home-destination.md) point 4.
   Explicitly **not** playing an album or a playlist: a twelve-track album has nothing to weight,
   and `LibraryView`'s own comment already gives this reasoning for keeping "shuffle everything" on
   Tracks only — *"it has an obvious meaning for a list of tracks and none for a list of albums."*

5. **A preset survives a queue change, exactly as the ADR-0027 modes do.** It is a property of the
   listener. Where ADR-0027 point 6 clears the modes — `clear()` — this clears with them.

6. **With no server there is no weighted order, and the control says so.** The preset is
   unavailable offline rather than falling back to a plain shuffle, because a plain shuffle looks
   exactly like the feature working. This is ADR-0032 point 5's rule and the answer to the three
   silently-failing affordances ADR-0017 records.

7. **The control lives on the transport's shuffle affordance, on both platforms**, mirroring the
   web app's `ShuffleWeightPopover`. A long-press or a disclosure on the shuffle button, not a
   Settings pane — a preference nobody finds does not help, which is the reasoning ADR-0005 point 8
   already used about the insertion interval.

## Alternatives Considered

**Compute the weighting on the client from downloaded metadata.** It would work offline, which is
the one thing point 6 gives up. Rejected on two counts. The client holds neither the play history
nor the whole library — the weights normalise against a library-wide maximum play count that a
50-track page cannot produce. And it would be a second copy of a tuned scorer in a second language,
which is precisely the outcome [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md)
exists to prevent; that ADR rejected forking `ambient.py` for the same reason.

**Send the preset to the server as part of the playback session, in `queue_source`.** It is the
field designed to carry exactly this, and `PlaybackSessionSnapshot`'s comment names it as what was
lost. Rejected by ADR-0029 — the server stores no listener preferences — and by
[ADR-0028](ADR-0028-the-apple-clients-playback-session-is-local.md), which took these clients out
of the server session entirely. Reintroducing one field would reopen a decision made three ADRs
ago for one query parameter.

**Model the presets as cases on `FamiliarPlayer` beside `repeatMode` and `isShuffled`.** Tidy, and
it would make the persistence question answer itself. Rejected because they are not playback
modifiers: they select a queue before playback starts and have no meaning once one exists. Putting
them on the player would invite the same category error point 2 is written to prevent.

**Ship one preset — `rediscover` — rather than four.** Defensible: `ambient.py:469` already sets
`RADIO_TASTE_PRESET = "rediscover"`, so it is the one the product already leans on, and one row is
easier to place than four. Rejected because the four exist, are tuned, cost nothing extra to
expose, and differ in ways a listener can actually feel — `comfort_zone` and `deep_dive` are close
to opposites.

**Wait for [ADR-0006](ADR-0006-offline-ranking-is-precomputed-server-side.md)'s offline manifest so
the feature works offline from the start.** Rejected as the wrong order: the manifest's variants
are a larger piece of work, the online path is finished today, and point 6 degrades honestly in
the meantime.

## Consequences

- **Positive.** Four tuned modes reach the Apple clients with no server change, no schema change
  and no generator change — the whole cost is client-side.
- **Positive.** The distinction in point 2 gives the app a defensible answer to "what does shuffle
  do when a preset is on", which the web app has never had to state because both live in one store.
- **Positive.** `shuffleLibrary()` and the Home rows share one mechanism, so a preset chosen in the
  transport is the preset Home uses.
- **Tradeoff.** The presets do not work offline, making them the second thing after embedded
  Discover with no offline story. Unlike Discover, this one has a known route to fixing it.
- **Tradeoff.** Two controls now sit on one button — a mode and a preset — and the difference
  between them is real but not obvious. Whether one affordance can carry both is a design question
  this ADR does not settle.
- **Tradeoff.** `GET /tracks/ids` with a preset does per-track weight computation over the library
  on every request. It is what the web app already does, but the Apple client will call it from
  Home, which is a more frequent trigger than a popover.
- **Follow-up.** ADR-0006's offline manifest carries `variants[]`, each a `(weight profile, filter
  preset)` combination. Wiring the four presets to those variants is the offline answer to point 6
  and is its own piece of work.
- **Follow-up.** ADR-0003 point 8's `queue_source` remains unimplemented on these clients, and now
  for a second reason. Worth annotating there so nobody reads the gap as an oversight.
