# ADR-0004: Listening Feedback Is Event-Sourced

Status: proposed

Date: 2026-07-26

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

4. **Add `POST /tracks/{track_id}/rejected`** for an explicit thumbs-down on a radio insertion. This
   is a stronger signal than a skip and must be distinguishable from one.

5. **Clients emit from the point where play and skip already resolve** —
   `packages/frontend/src/player/useAudioEngine.ts` — so no new state tracking is introduced to do
   it.

6. **The migration follows the project convention:** a file in `backend/migrations/versions/` named
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
- **Follow-up:** Decide the completion-ratio threshold for `skipped` empirically once data exists,
  rather than fixing it by convention now.
- **Follow-up:** Consider backfilling `PlayEvent` from `ProfilePlayHistory` as low-confidence
  synthetic rows, or explicitly decide not to. Synthetic events with no real timestamps may be worse
  than none.
