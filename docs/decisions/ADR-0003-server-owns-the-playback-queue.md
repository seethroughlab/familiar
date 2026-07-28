# ADR-0003: The Server Owns the Playback Queue

Status: accepted

Date: 2026-07-26

Extends [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md).

Implementation:
- Decision points 1, 3, 5 and 6 were revised before acceptance, after investigating the client, and
  points 8 and 9 are new. The original point 5 asserted that the logical/playable queue split already
  existed and would be "preserved, not replaced"; it does not exist, and building it is now the first
  phase of work. The original point 3 named the `pendingActions` outbox as an append log, which is the
  wrong shape for state. Point 1 gained `position_seconds` and `reservoir_hash`, and lost `device_id`.
- Both follow-ups from the original draft are resolved at acceptance — see **Resolved** under
  Consequences. `PlaybackSession` is keyed by **profile alone**.
- Execution order, each phase its own branch: (1) the logical/playable split, client-only, no server
  involved; (2) `PlaybackSession`, migration and endpoints; (3) client sync behind a flag. Phase 1 is
  deliberately separate — it fixes existing data loss, and without it phase 3 would upload an
  offline-filtered queue and overwrite the logical one on every other device.

## Context

The playback queue exists only on the client. `packages/frontend/src/player/queueStore.ts` is 1,092
lines holding the queue, history, shuffle order, repeat/consume, lazy ID-only queues, and hydration.
There is **no server-side queue model at all** — the LLM's `_queue_tracks` handler
(`backend/app/services/llm/handlers/playback.py:22`) returns an ephemeral payload of track IDs and
the client assembles the queue itself.

Three consequences follow:

1. **Cross-device sync does not exist.** Starting a queue on the phone and continuing on the desktop
   is not possible, because neither device knows what the other is playing.
2. **Every new platform reimplements 1,092 lines.** [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md)
   adds a Swift client; a future Windows client would be a third implementation of shuffle-order
   bookkeeping, consume semantics, and lazy hydration. Three implementations will diverge.
3. **"Offline/sync unreliable" is partly this.** Queue state persists to IndexedDB
   (`playerState` table, keyed by profile ID) with no server reconciliation, so any inconsistency is
   permanent and invisible.

The obvious objection to a server-owned queue is that it breaks offline playback. It does not, but
only if the design is explicit about it — which is the substance of this ADR. Two of the pieces the
original draft called proven are proven; two are not, and are recorded here so nobody re-derives them.

**What is proven:**

- **An outbox exists and has been extended once.** `packages/frontend/src/services/syncService.ts`
  queues `scrobble | now_playing | favorite_toggle | listen_event` actions into the `pendingActions`
  table and replays them on reconnect. `listen_event` was added by
  [ADR-0004](ADR-0004-listening-feedback-is-event-sourced.md) after this was drafted.
- **Connectivity state.** `packages/frontend/src/stores/connectivityStore.ts` (320 lines) models
  `browserOnline` / `reachabilityState` / `forcedOffline` with consecutive-failure debouncing, and
  derives a single `offlineModeActive` flag that every consumer reads.

**Four premises in the original draft were wrong:**

1. **The logical/playable queue split does not exist.** The draft said `useAudioEngine.ts` "already
   rebuilds the queue down to downloaded tracks when connectivity drops and restores the full queue
   on reconnect," and that this ADR would preserve that behaviour. What the code actually does is
   destructive: the rebuild effect calls `setQueue(filteredTracks, …)`
   (`packages/frontend/src/player/useAudioEngine.ts:545`), which replaces the queue outright, and
   `setQueue` also nulls `lazyQueueIds` / `lazyQueueIndex` (`queueStore.ts:517-518`). The pre-filter
   queue survives only in `preOfflineQueueRef` (`useAudioEngine.ts:119`) — an in-memory React ref.

   Two failures follow, both present today:

   - **A reload while offline loses the logical queue permanently.** The ref is gone and the
     persisted copy is the filtered one, so there is nothing left to restore from.
   - **A reconnect restores a non-lazy queue.** The reservoir was nulled going in and the ref holds
     only materialised tracks, so a library queue silently stops at the end of the ~50-track window —
     the same failure PR #20 fixed for reloads, still live for the offline round trip.

   So the split must be **built**, not preserved. That is decision point 5 and the first phase of
   work, and it is the single most valuable part of this ADR independent of any server.

2. **The cited regression guard guards something else.** `packages/web/e2e/offline-invariant.spec.ts`
   asserts that the Downloads view agrees with IndexedDB; it never builds a queue and never varies
   connectivity. The actual coverage is two unit tests at
   `packages/frontend/src/player/__tests__/playerStore.test.ts:273-292` and the PR #20 reservoir suite
   in `queuePersistence.test.ts`. The e2e claim should not be used when judging how much risk this
   change carries.

3. **The outbox is an event log, not a state channel.** It is proven for events and unsuited to
   state as built: no dedupe, no backoff, an action dropped after four attempts
   (`syncService.ts:111-119`), global millisecond-resolution `createdAt` ordering across all profiles
   and action types (`:75`), and `executeAction` ignoring `action.profileId` entirely (`:173-201`) —
   the profile comes from the `X-Profile-ID` interceptor at request time (`api/base.ts:167-172`), so
   an action queued under one profile replays against whichever profile is selected when the drain
   runs. [ADR-0006](ADR-0006-offline-ranking-is-precomputed-server-side.md) reached the same
   conclusion from the other direction and recorded it as a resolved follow-up: "`syncService` was the
   wrong vehicle; it is an outbound `pendingActions` replay queue with no inbound path."

4. **Device identity is greenfield, not merely unsettled.** The draft's follow-up treated
   `Profile.device_id` as a starting point. It is a nullable column with **zero readers** anywhere in
   `backend/app/` (`db/models/profiles.py:33`), the IndexedDB `deviceProfile.deviceId` is written as
   the empty string (`services/profileSelection.ts:56`), and no endpoint reads any device header. So
   keying by device is not "use the field that exists" — it is inventing the concept.

## Decision

The server becomes the source of truth for the durable queue; every client holds an **authoritative
local replica** and never blocks playback on the network.

1. **A `PlaybackSession` model server-side, keyed by profile alone**: `track_ids[]`, `cursor`,
   `shuffle_order[]`, `shuffle_index`, `shuffle`, `repeat`, `consume`, `queue_source`,
   `reservoir_ids[]`, `reservoir_cursor`, `reservoir_hash`, `position_seconds`, `version`,
   `updated_at`.

   **There is no `device_id`.** One live queue per profile, so handoff needs no explicit transfer
   action and the device identity that does not exist stays uninvented — see Context point 4 and the
   alternative below.

   Three fields were added after the ADR was drafted and are not optional detail. The first two
   concerns were found missing from client persistence in PR #20, each causing a distinct silent
   failure:

   - **`queue_source`** — without it, listening events lose their context, which
     [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md)'s ranking depends on, and
     `toggleShuffle` silently stops using the server-side weighted preset.
   - **`reservoir_ids` / `reservoir_cursor`** — a library queue is a *lazy reservoir*: the full ID
     list with only a ~50-track window materialised. Without them the queue silently truncates to
     that window and **playback simply ends after the 50th track**, with no error and nothing in the
     UI to explain it.
   - **`position_seconds`** — without it a handoff resumes at the top of the track rather than where
     the listener left off, which is most of what handoff is for. The client already persists this
     (`PersistedPlayerState.currentTime`); the original field list simply omitted it.

   A server-owned queue that omitted the first two would reproduce that bug on every client,
   including the Swift one, and it would be materially harder to diagnose there than it was on the web.

2. **Local-first mutation.** Every queue mutation applies to the local replica immediately and
   synchronously. Playback, reordering, and skipping never wait on a request. This is
   non-negotiable — a queue that stutters on a slow network is worse than no sync at all.

3. **Mutations coalesce into a single outbox row per profile, replaced rather than appended.** Reuse
   `pendingActions` as the *transport* — inventing a second sync path is still the wrong move — but
   not its append semantics. A queue is state, not an event: appending a snapshot per mutation would
   replay hundreds of stale queues on reconnect, all but the last one pointless, and the four-attempt
   drop (`syncService.ts:111-119`) would strand the server mid-history, contradicting point 6's
   promise that nothing is destroyed. One row per profile, always current, is both cheaper and
   correct under last-writer-wins.

   Three defects in the outbox must be fixed for this to be safe, and all three are latent bugs
   today rather than new requirements: `executeAction` must honour the captured `action.profileId`
   instead of letting the interceptor choose (Context point 3); the drain needs an in-flight guard,
   because the `window 'online'` handler and `components/PWA/OfflineIndicator.tsx` can currently run
   it concurrently; and the drain must also fire on `connectivityStore`'s probe-driven
   `forcedOffline → reachable` recovery, which emits no browser `online` event.

4. **The reservoir syncs separately from the queue, and not on every mutation.** For this library
   `reservoir_ids` is 26,462 UUIDs — roughly 1 MB. Shipping that with each cursor advance would be
   absurd, and it is a different problem from syncing a 50-track queue, which the original draft did
   not distinguish.

   The reservoir changes only on `setLazyQueue`, `toggleShuffle` and a refill, so it is **sent when it
   changes and referenced by `reservoir_hash` otherwise**: a write may omit `reservoir_ids`, meaning
   "unchanged, and it hashes to this"; a hash the server does not hold is rejected so the client
   resends in full. The same reasoning already applies client-side: PR #20 stores it in its own
   IndexedDB row precisely so a 500 ms `setCurrentTime` throttle does not rewrite a megabyte twice a
   second, and skips the write by reference equality when the array has not been replaced.

5. **The server queue is the *logical* queue; clients derive a *playable* queue — and this must be
   built.** When offline, a client filters the logical queue to locally-available tracks for playback
   and restores the full logical queue on reconnect. Today the filter is destructive and the logical
   queue survives only in memory (Context point 1), so the first phase of work makes the logical queue
   real persisted state: the pre-filter track IDs and the reservoir both survive a reload while
   offline, and the reconnect path restores a lazy queue rather than a truncated one.

   Only the logical queue is ever synced. Uploading a filtered queue would overwrite every other
   device's copy with whatever this device happened to have downloaded — the worst failure this ADR
   could introduce, and the reason phase 1 comes first.

6. **Conflict rule: later `updated_at` wins, and the loser is archived rather than dropped.** If two
   devices diverged while offline, the later one becomes current and the loser is written to an
   archive table as a restorable entry. A user must never lose a queue they built to a silent merge.
   Because `updated_at` uses ORM-level `onupdate=func.now()`, the conflict path must go through ORM
   updates and never a bulk `update()` statement, which would not bump it.

7. **Land it behind a flag, in the web app, before Swift depends on it.** The native client consumes
   this only once it is proven against the existing test suite. The flag is per-device
   (`localStorage`) so rollout can be staged, paired with a server-side setting so an unflagged server
   rejects writes rather than silently accepting them.

8. **`queue_source` uses the client's queue-source vocabulary, stored whole.** `QueueSourceType`
   (`player/playerStore.types.ts:1`) is `library | album | playlist | artist | ephemeral | other`.
   The server's `PlayContext` (`routes/tracks/playback.py:51-53`) adds `radio` and `ambient`, which
   are listening *contexts*, not queue *sources* — the sets differ deliberately and must not be
   conflated. The whole object is stored as JSONB rather than decomposed into columns, because
   `toggleShuffle` (`queueStore.ts:897`) replays `filters` verbatim against `tracksApi.getIds`.

9. **`history` stays device-local and is not synced.** It is not persisted even locally today
   (`queueStore.ts:124` is absent from the persist getter at `:1081-1092`), it is capped at 50 entries,
   and "previous track" is a per-device navigation affordance rather than shared queue state. Syncing
   it would mean deciding whose history wins on handoff, for no benefit.

## Alternatives Considered

- **Each client owns its queue; port `queueStore.ts` to Swift.** Rejected. Simpler in the short term,
  but it writes the logic a third time for Windows, guarantees divergence, and leaves cross-device
  sync permanently broken.
- **Server-only queue with no local replica.** Rejected outright. It breaks offline playback, which
  is one of the three symptoms motivating this whole effort.
- **CRDT-based merge.** Rejected as disproportionate. The realistic conflict is "two devices played
  while apart," which last-writer-wins plus retention handles. A CRDT adds substantial complexity for
  a case that resolves fine with a timestamp.
- **Sync only the *current track*, not the queue.** Rejected. It solves the handoff case but not the
  duplicated-logic case, which is the larger long-term cost.
- **Key `PlaybackSession` by profile *and* device.** Rejected, and this is the closest alternative to
  the original draft. It is the more flexible model — each device keeps its own queue and handoff
  becomes an explicit "transfer to here" action — but it requires inventing a device identity the
  codebase does not have (Context point 4) and plumbing a new header through every client, and
  [ADR-0006](ADR-0006-offline-ranking-is-precomputed-server-side.md) rejected exactly that for exactly
  that reason. Profile keying also makes handoff the default rather than a feature someone has to
  find. The cost is real and accepted: two devices playing simultaneously under one profile contend
  over the cursor, and last-writer-wins means the one that stops later overwrites the other's
  position. That is a single-listener application behaving as a single listener.
- **Append one outbox row per mutation, and let the server collapse them by `version`.** Rejected.
  Literal to the original point 3, but it makes reconnect O(mutations) instead of O(1), and the
  existing four-attempt drop can discard a row from the middle of the history — leaving the server on
  a state no device ever held. Coalescing makes the drop harmless because the surviving row is always
  the current one.
- **Drive sync from the existing `persistCombinedState()` funnel.** Rejected, despite being the
  obvious seam — it is the single choke point 23 of the store's mutation sites already flow through
  (`exitLazyMode` at `queueStore.ts:735` is the one that forgets to, which phase 1 fixes). But it also
  fires on every `setCurrentTime` tick, throttled only to 500 ms, so hanging sync off it would mean a
  request twice a second for the whole of playback. Structural changes and position changes need
  different cadences, so they get separate triggers.

## Consequences

- **Positive:** Cross-device handoff becomes possible for the first time, and with profile keying it
  needs no user action — the other device is simply already there.
- **Positive:** The Swift client and any future Windows client carry queue *rendering*, not queue
  *logic*. This is the single largest reduction in per-platform work available.
- **Positive:** Queue state becomes inspectable and repairable server-side, rather than trapped in
  per-device IndexedDB.
- **Positive, and not in the original draft:** phase 1 fixes two live data-loss bugs on its own,
  before any server work — a reload while offline no longer discards the logical queue, and a
  reconnect no longer truncates a library queue at the materialised window. That value lands whether
  or not the sync ever ships.
- **Positive:** Three latent outbox bugs get fixed as a precondition (decision point 3), one of which
  — `executeAction` ignoring the captured profile — currently misroutes offline favourite toggles
  after a profile switch.
- **Tradeoff:** This touches the most heavily tested code in the repository —
  `packages/frontend/src/player/__tests__/queueStore.test.ts` (672 lines) and `playerStore.test.ts`
  (1,059 lines), plus `queuePersistence.test.ts` (278) and `persistence.test.ts` (177). Those tests
  are the safety net and must keep passing unchanged where behaviour is unchanged.
- **Tradeoff:** A new class of bug — replica divergence — becomes possible. The conflict rule must be
  tested explicitly, not assumed.
- **Tradeoff:** One session per profile means simultaneous playback on two devices contends over the
  cursor. Accepted deliberately; see the device-keying alternative.
- **Tradeoff:** `queueId` values come from an in-memory counter (`queueStore.ts:23`), so queue item
  identity is positional rather than stable across devices or reloads. Last-writer-wins does not need
  stable identity, but any future per-item merge would.
- **Resolved:** ~~Decide whether `queueStore.ts` becomes a thin replica adapter or is substantially
  rewritten~~ — **adapter.** Its shuffle-order and consume semantics are correct and well covered, and
  the persist getter at `queueStore.ts:1081-1092` already exposes almost exactly the `PlaybackSession`
  field set. Phase 1 adds two fields to it rather than restructuring the store.
- **Resolved:** ~~Define device identity~~ — **not needed.** `PlaybackSession` is keyed by profile, so
  this ADR does not have to solve what
  [ADR-0006](ADR-0006-offline-ranking-is-precomputed-server-side.md) avoided. `Profile.device_id`
  stays vestigial; if a later ADR needs device identity, it starts from nothing, and that should be
  stated plainly rather than discovered.
- **Follow-up:** The archive from decision point 6 needs a retention policy. Bounded per profile is
  enough to start; unbounded growth of superseded queues is not urgent at personal-library scale but
  should not be ignored forever.
- **Follow-up:** `position_seconds` syncs on a coarse cadence, so a handoff can resume a few seconds
  behind where the other device actually was. Decide empirically whether that is worth tightening
  once it is possible to feel it.
