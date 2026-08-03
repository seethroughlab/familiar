# ADR-0004: Listening Feedback Is Event-Sourced

Status: accepted

Date: 2026-07-26

Implementation:
- Decision points 4–7 were revised before acceptance, after investigating the client. The original
  point 5 named `player/useAudioEngine.ts` (the emission point is actually the `usePlayTracking`
  hook) and required that no new state be introduced, which turned out to be impossible — see the
  advance-reason discussion in point 5. Points 6 and 7 are new.
- Phase 1 — backend: `PlayEvent` model, migration `20260726_play_events`, and the three endpoints,
  on branch `feat/adr-0004-play-events`. Deployed to the NAS 2026-07-26 and verified against the
  live 26,462-track library: `/skipped` and `/rejected` recorded events while the library-wide
  `sum(play_count)` held at 5960 across both calls — the decision point 2 guarantee, checked rather
  than assumed. Outcome derivation confirmed end to end, including the crossfade case (ratio 0.90
  with `reason=natural` resolving to `completed`, where ratio alone would have said `skipped`) and
  the error case resolving to `errored`. Probe rows were reverted afterwards; the table starts empty.
- Phase 2 — client emission: advance-reason threading through `queueStore`, the `usePlayTracking`
  rewrite, and the outbox `listen_event` type, on branch `feat/adr-0004-client-emission`.
  Deliberately split from phase 1 so a DB migration did not land together with changes to the
  player's most delicate code path.

  Three additions the decision above did not anticipate:
  - **A sixth reason, `system`, that emits nothing.** Offline queue rebuilds, hydration and profile
    switches replace `currentTrack` without the listener acting; without it every reconnect would
    log a phantom skip.
  - **Error advances take three paths, not the two named in point 6.** Beyond the two `playNext()`
    sites, `advanceToNextDownloadedTrack` goes through `jumpToQueueIndex` and a crossfade failure
    rolls back via `setQueueByTrackId`.
  - **The reason is written inside the same `setState` that changes `currentTrack`.** `playNext` has
    five early-returns that change no track, so a reason set before the branch would leak into the
    next advance.

  Two latent bugs surfaced and were fixed: `PlayerBar`/`FullPlayer` used bare `onClick={playNext}`,
  which would have passed React's `MouseEvent` into the options slot; and React Testing Library's
  automatic cleanup was never running (no `globals: true`, no setup file), so hooks from earlier
  tests stayed mounted and polluted assertions.

## Context

Familiar has no equivalent of Spotify's behaviour of inserting tracks it expects you to like into a
playing queue. Building one ([ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md))
requires a taste signal, and the schema does not currently carry one that can learn.

`ProfilePlayHistory` (`backend/app/db/models/profiles.py:95`) is **aggregate only**:

```
(profile_id, track_id) PK
play_count: int
last_played_at: datetime
total_play_seconds: float
```

There is no per-event log. There is **no skip tracking anywhere in the schema** — no `Listen`,
`PlayEvent`, `Skip`, or thumbs-down model exists. `POST /tracks/{track_id}/played`
(`backend/app/api/routes/tracks/playback.py:44`) accepts an optional `duration_seconds` and *adds* it
to `total_play_seconds`.

That summing is the crux. A track played to completion once and a track skipped at three seconds
twenty times are indistinguishable in aggregate. The negative signal is not merely absent — it is
**destroyed at write time** and cannot be recovered retroactively.

`ProfileFavorite` provides an explicit positive signal, but it is sparse and deliberate; it says
nothing about the far larger set of tracks a listener quietly tolerates or quietly rejects.

This matters for sequencing. A recommender launched with no feedback history is cold, and the data
can only accumulate in wall-clock time. Recording events must start well before the feature that
consumes them.

## Decision

Record listening as **events**, and derive aggregates from them rather than only storing aggregates.

1. **Add a `PlayEvent` model** in `backend/app/db/models/profiles.py`:
   `profile_id`, `track_id`, `started_at`, `played_seconds`, `track_duration`, `completion_ratio`,
   `context` (`playlist | radio | album | search | ambient`), `source_track_id` (the track a radio
   insertion was seeded from, null otherwise), `outcome` (`completed | skipped | rejected`).

2. **`ProfilePlayHistory` stays and keeps its current semantics.** Many call sites read it —
   `library_artists.py`, `smart_playlists.py`, `playlists/crud.py`, `library_discover.py`,
   `favorites.py`, `tracks/listing.py`, and the export/import paths. Breaking it to introduce events
   would be gratuitous. `POST /tracks/{track_id}/played` writes both.

3. **`outcome` is derived at write time from `completion_ratio`,** with the threshold as a named
   constant rather than a magic number scattered across the codebase.

4. **Three endpoints, each named for its effect.** `record_play` increments `play_count`
   unconditionally, so skips cannot ride on `/played` without inflating the aggregate that decision
   point 2 promises to leave alone.
   - `POST /tracks/{track_id}/played` — contract unchanged; bumps the aggregate **and** writes a
     `completed` event.
   - `POST /tracks/{track_id}/skipped` — writes an event only; the aggregate is untouched.
   - `POST /tracks/{track_id}/rejected` — writes an event only. An explicit thumbs-down on a radio
     insertion is a stronger signal than a skip and must be distinguishable from one.

5. **Clients emit from the existing play-tracking hook,**
   `packages/frontend/src/hooks/usePlayTracking.ts` (mounted at `hooks/useAppBootstrap.ts:35`), which
   already accumulates forward-progress play time and ignores backward seeks.

   This does require **one piece of new state**: an advance reason. Nothing currently tells the
   client *why* the current track changed — `usePlayTracking` only observes `currentTrack?.id`
   flipping, so a natural end and a hard skip are indistinguishable. The queue store must expose why
   it advanced (`ended`, `crossfade`, `native-auto`, `user`, `error`). Completion ratio alone is not
   sufficient: the crossfade path advances at roughly `duration - crossfadeDuration`, so a
   fully-played track reads as ~0.9, and iOS background auto-advance can leave the accumulated time
   stale.

6. **Error-driven skips are recorded as `errored` and excluded from ranking.**
   `packages/frontend/src/player/useAudioEngine.ts:358` and `:835` call `playNext()` when a track
   fails to load. A track with a broken file is not a track the listener dislikes; feeding those into
   [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md)'s negative term would train the
   recommender against unplayable files. They are logged for diagnostics and must never reach the
   taste signal.

7. **Events queue through the existing offline outbox** — the `pendingActions` table and
   `packages/frontend/src/services/syncService.ts`. Offline plays are currently lost silently
   (`usePlayTracking` swallows errors), and offline listening is exactly where skipping is most
   frequent.

8. **The migration follows the project convention:** a file in `backend/migrations/versions/` named
   `YYYYMMDD_slug.py`, a revision ID of 32 characters or fewer, and `table_exists` / `column_exists`
   guards from `migrations.helpers` for idempotency.

## Alternatives Considered

- **Derive skips from `total_play_seconds`.** Rejected — it is summed across plays, so per-play
  completion is unrecoverable. This is the reason the ADR exists.
- **Add a `skip_count` column to `ProfilePlayHistory`.** Rejected. Cheaper, but it repeats the
  original mistake at a smaller scale: no timestamps, no context, no way to ask "what did they skip
  *from radio* last month." Events answer questions not yet posed.
- **Rely on Last.fm scrobbles.** Rejected. Scrobbling is optional (`LastfmProfile` may not exist),
  the data is external, and the scrobble protocol has no skip semantics.
- **Log to `FrontendLog` and mine it later.** Rejected. That table is diagnostic, unstructured, and
  not intended as a durable product data source.

## Consequences

- **Positive:** [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md) gains a negative
  signal, which is what makes a recommender improve rather than merely function.
- **Positive:** Landing this first means feedback accumulates during the months of native work in
  [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md), so the radio is not cold at
  launch. This is the reason it is first in the execution order.
- **Positive:** Per-event history enables things currently impossible — time-of-day patterns, session
  reconstruction, "played once and never again."
- **Tradeoff:** Unbounded table growth, one row per play. Needs a retention policy or periodic
  rollup; at personal-library scale this is not urgent but should not be ignored forever.
- **Tradeoff:** Dual writes to `PlayEvent` and `ProfilePlayHistory` must stay consistent. They should
  share a transaction.
- **Tradeoff:** The advance reason in decision point 5 is new state in the queue store — the most
  heavily tested code in the repo. It is unavoidable: without it, outcomes are wrong for the
  crossfade and iOS background-advance paths, and error-skips would be indistinguishable from real
  ones.
- **Tradeoff:** Three endpoints rather than one. Accepted so that each endpoint's name matches its
  effect and `/played`'s existing contract is untouched.
- **Resolved:** Backfilling `PlayEvent` from `ProfilePlayHistory` — **no.** Synthetic rows would need
  invented timestamps and have no real completion data, so they would pollute exactly the signal
  [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md) depends on. History starts at
  the migration.
- **Follow-up:** Decide the completion-ratio threshold for `skipped` empirically once data exists,
  rather than fixing it by convention now. **Blocked until roughly 2026-09-01 — see below.**

**The data did not start accumulating when this shipped.** Until `familiar` #57 the web client
delivered a play the moment listening crossed `min(duration / 2, 4 min)` and sent
`completion_ratio` as measured at that instant, never revising it. A web play therefore landed at
almost exactly 0.5 whether the listener heard half the track or all of it. Measured on the live
database on 2026-08-01: **289 of 357 completed events sat in the 0.5–0.6 bucket**, against native
rows correctly reading 0.95–1.00.

Verified again on 2026-08-02, by day and context. Every context before 2026-08-01 shows completions
averaging 0.42–0.50 — including `library`, because the web derives `context` from the queue source
and sends `library` for a library queue exactly as the native app does. From 2026-08-01 the same
context reads 0.972 and 1.000, and skips cluster at ≤0.1. Of 823 rows, **795 predate the fix**.

Three consequences worth stating plainly, because the first is the one that would have gone
unnoticed:

1. **The clock restarted on 2026-08-01, not 2026-07-27.** A month of trustworthy data lands around
   2026-09-01. This follow-up, ADR-0005's weight tuning, and `familiar` #53 all inherit that date.
2. **The contaminated rows are excluded, not deleted** (`services/listening_feedback.py`:
   `FEEDBACK_TRUSTWORTHY_SINCE`, `trustworthy_feedback_only`). `play_events` records no client and
   `context` does not stand in for one, so the good native rows cannot be separated from the bad web
   rows beside them; selecting on the ratio would be circular, since that is the variable being
   measured. A date is the only separator that does not assume the answer, and it costs those native
   rows. Deleting would also throw away rows that are still useful — see 3.
3. **`outcome` is unreliable before the cutoff too, and skips are under-counted.** A track abandoned
   at 55% was recorded as a completion at ~0.5 rather than as a skip. What survives is that rows
   marked `skipped` or `rejected` describe real abandonments; they are an incomplete census rather
   than a wrong one. `ambient._negative_signal` counts exactly those two outcomes over a rolling
   90-day window, so **the live recommender was never poisoned** — it has been running on a slightly
   weak negative signal, which heals as the window passes the cutoff (around 2026-10-30).

Volume in the clean window, as of 2026-08-02: **28 events across 26 distinct tracks over two days**.
At that rate a month yields roughly 400 events — enough to place a completion-ratio threshold, thin
for ADR-0005's weight tuning, which may want longer or a narrower first pass.

- **Follow-up:** `play_events` records no client, which is the only reason the good native rows from
  before the cutoff had to be discarded with the bad web ones. A nullable `client` column, sent by
  all three clients, would make the next contamination separable instead of fatal to a whole window.
  Cheap now, worthless applied retroactively.
- **Follow-up:** Whether the web client still reports at all is **unverified**. Every row since the
  cutoff carries `context = 'library'`, which is what the native app hardcodes; the web's other
  contexts (`other`, `null`, `playlist`) stop on 2026-07-31. That is equally consistent with nobody
  having used the web app since, and cannot be told apart from the rows alone — which is the
  preceding follow-up restated as a live question. Settle it by playing one track in the web app and
  looking for a non-`library` context, not by reasoning about the data.
