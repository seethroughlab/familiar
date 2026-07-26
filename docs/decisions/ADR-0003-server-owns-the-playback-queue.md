# ADR-0003: The Server Owns the Playback Queue

Status: proposed

Date: 2026-07-26

Extends [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md).

## Context

The playback queue exists only on the client. `packages/frontend/src/player/queueStore.ts` is 1,021
lines holding the queue, history, shuffle order, repeat/consume, lazy ID-only queues, and hydration.
There is **no server-side queue model at all** — the LLM's `_queue_tracks` handler
(`backend/app/services/llm/handlers/playback.py:22`) returns an ephemeral payload of track IDs and
the client assembles the queue itself.

Three consequences follow:

1. **Cross-device sync does not exist.** Starting a queue on the phone and continuing on the desktop
   is not possible, because neither device knows what the other is playing.
2. **Every new platform reimplements 1,021 lines.** [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md)
   adds a Swift client; a future Windows client would be a third implementation of shuffle-order
   bookkeeping, consume semantics, and lazy hydration. Three implementations will diverge.
3. **"Offline/sync unreliable" is partly this.** Queue state persists to IndexedDB
   (`playerState` table, keyed by profile ID) with no server reconciliation, so any inconsistency is
   permanent and invisible.

The obvious objection to a server-owned queue is that it breaks offline playback. It does not, but
only if the design is explicit about it — which is the substance of this ADR. The necessary pieces
already exist and are proven:

- **An outbox pattern.** `packages/frontend/src/services/syncService.ts` already queues
  `scrobble | now_playing | favorite_toggle` actions into the `pendingActions` table with retry
  counts and replays them on reconnect.
- **Offline queue filtering.** `packages/frontend/src/player/useAudioEngine.ts` already rebuilds the
  queue down to downloaded tracks when connectivity drops and restores the full queue on reconnect.
- **A regression guard.** `packages/web/e2e/offline-invariant.spec.ts` already asserts this
  behaviour.
- **Connectivity state.** `packages/frontend/src/stores/connectivityStore.ts` (320 lines) already
  models `browserOnline` / `reachabilityState` / `forcedOffline` with consecutive-failure debouncing.

## Decision

The server becomes the source of truth for the durable queue; every client holds an **authoritative
local replica** and never blocks playback on the network.

1. **A `PlaybackSession` model server-side**, keyed by profile and device: `track_ids[]`, `cursor`,
   `shuffle_order[]`, `shuffle_index`, `repeat`, `consume`, `version`, `updated_at`.

2. **Local-first mutation.** Every queue mutation applies to the local replica immediately and
   synchronously. Playback, reordering, and skipping never wait on a request. This is
   non-negotiable — a queue that stutters on a slow network is worse than no sync at all.

3. **Mutations append to an outbox.** Reuse the `pendingActions` mechanism in
   `packages/frontend/src/services/syncService.ts` rather than inventing a second sync path. On
   reconnect the outbox replays and the server increments `version`.

4. **The server queue is the *logical* queue; clients derive a *playable* queue.** When offline, a
   client filters the logical queue to locally-available tracks for playback, and restores the full
   logical queue on reconnect. This is exactly what `useAudioEngine.ts` does today; the behaviour is
   preserved, not replaced.

5. **Conflict rule: later `updated_at` wins, and nothing is destroyed.** If two devices diverged
   while offline, the later one becomes current and the loser's queue is retained as a restorable
   entry. A user must never lose a queue they built to a silent merge.

6. **Land it behind a flag, in the web app, before Swift depends on it.** The native client consumes
   this only once it is proven against the existing test suite.

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

## Consequences

- **Positive:** Cross-device handoff becomes possible for the first time.
- **Positive:** The Swift client and any future Windows client carry queue *rendering*, not queue
  *logic*. This is the single largest reduction in per-platform work available.
- **Positive:** Queue state becomes inspectable and repairable server-side, rather than trapped in
  per-device IndexedDB.
- **Tradeoff:** This touches the most heavily tested code in the repository —
  `packages/frontend/src/player/__tests__/queueStore.test.ts` (672 lines) and `playerStore.test.ts`
  (1,059 lines). Those tests are the safety net and must keep passing unchanged where behaviour is
  unchanged.
- **Tradeoff:** A new class of bug — replica divergence — becomes possible. The conflict rule must be
  tested explicitly, not assumed.
- **Follow-up:** Decide whether `queueStore.ts` becomes a thin replica adapter or is substantially
  rewritten. Prefer adapter: its shuffle-order and consume semantics are correct and well covered.
- **Follow-up:** Define device identity. `Profile.device_id` exists as a legacy field and
  `deviceProfile` exists in IndexedDB; neither is currently authoritative.
