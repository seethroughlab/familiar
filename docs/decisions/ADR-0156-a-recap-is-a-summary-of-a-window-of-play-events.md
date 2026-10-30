# ADR-0156: A Recap Is a Summary of a Window of Play Events

Status: accepted

Date: 2026-10-30

Implementation:
- **Accepted 2026-10-30.**
- **Built 2026-10-30 on `feature/recap`, ahead of acceptance.** `backend/app/services/recap.py`
  (`compute_recap`, `recap_window`, `RECAP_MIN_PLAYS`), `backend/app/api/routes/recap.py`, and
  `tests/test_recap.py`, which has 18 tests. Removing the cutoff or the `errored` filter fails 7 of
  them. The change is additive and the contract stays at version 1.

Extends [ADR-0004](ADR-0004-listening-feedback-is-event-sourced.md)

## Context

The listener asked for something like Spotify Wrapped: a year in review that ends as a video they
can post. [ADR-0157](ADR-0157-the-recap-video-is-rendered-on-the-client.md) decides where that video
is made. This ADR decides what it summarises, and where the summary is computed.

The original premise was "summarise the listener's year". **The data does not support that for 2026.**
There are two listening records, and only one has dates:

- `ProfilePlayHistory` (`backend/app/db/models/profiles.py:100-117`) has one row per profile and
  track, holding `play_count`, `last_played_at` and `total_play_seconds`. It goes back furthest, but
  it cannot say *when* any play happened, so it cannot be scoped to a year.
- `PlayEvent` (`profiles.py:120-172`) has one row per play, with `started_at`, `played_seconds` and
  `outcome`, indexed on `(profile_id, started_at)`. The table began on 2026-07-26. Its rows are
  trustworthy only from **2026-08-01** (`FEEDBACK_TRUSTWORTHY_SINCE` and `trustworthy_feedback_only()`,
  `backend/app/services/listening_feedback.py:49-59`), because before `familiar` #57 the web client
  reported about 0.5 as the completion ratio whatever had been heard, and under-counted skips.

So the first recap covers about five months, and it has to say so. 2027 is the first full year.

The only stats endpoint today, `GET /tracks/stats/plays` (`backend/app/api/routes/tracks/plays.py:394-430`),
reads the all-time aggregate and has no date range. Nothing groups `PlayEvent` by hour or month, or
joins it to `TrackAnalysis` to describe what the listening sounded like. That last part is what
Familiar can say and a streaming service can't: every track has typed `bpm`, `energy`, `valence`,
`danceability`, `key` and CLAP `mood_tags` (`backend/app/db/models/tracks.py:226-314`).

## Decision

1. **`GET /api/v1/recap/{year}` returns the summary, computed by the server on request.** It requires
   a profile (`RequiredProfile`) and has the `plays` tag: it summarises the event stream that tag
   already owns, and the Apple generator already includes `plays`. The path names its own resource,
   because a recap is a thing of its own rather than a property of a track (ADR-0072 point 1).

2. **Only `play_events` is read, never `ProfilePlayHistory`.** The aggregate has no dates. A recap that
   mixed the two would put all-time plays on a card that says "this year".

3. **The window is the year in the listener's time zone, starting no earlier than
   `FEEDBACK_TRUSTWORTHY_SINCE` and ending no later than now. The response states the window.** `tz`
   is an IANA name (default `UTC`). The window's bounds are converted to the naive UTC that
   `started_at` holds, and `window_start`/`window_end` are returned, so a client can label the 2026
   recap "since August 1" from the data rather than from a hard-coded date. The one cutoff is used
   for counts as well as ratios. Counts from 2026-07-26 to 07-31 would be roughly usable, but a
   second boundary for five days is a rule the next reader has to rediscover.

4. **A play is a `completed` event, and time listened counts everything except `errored`.** Rankings
   (top tracks, artists and albums) count completed events, breaking ties by time listened and then
   by name, so the order is stable. Minutes listened sum `played_seconds` over completed, skipped and
   rejected events, because a skip is still time spent listening. `errored` is excluded everywhere:
   playback failed, so nothing was heard (ADR-0004).

5. **Below a minimum the answer is `insufficient`, not a thin recap.** With fewer than
   `RECAP_MIN_PLAYS` (50) completed plays in the window, `insufficient` is true. Clients do not show
   the destination at all (ADR-0022 point 3: absent, not disabled). The body is still complete, so a
   client can show the counts in a "come back later" state if it chooses to.

6. **The summary describes the sound as well as the counts.** `sound` is the median `bpm`, `energy`,
   `valence` and `danceability` over completed plays (weighted by play, so a track played twenty
   times counts twenty times), the most common `key`, and the three most frequent mood tags. The
   rest of the summary:
   - `listening_clock`: completed plays by local hour, plus `peak_hour`
   - `top_month`
   - `first_listens`: tracks whose first-ever event falls inside the window
   - `favorites_added`: count of `ProfileFavorite.favorited_at` in the window

7. **Nothing is stored.** Each request computes the summary from the indexed range. At about 400
   events a month, one profile's year is a few thousand rows.

## Alternatives Considered

- **Compute the recap on each client from raw events.** Rejected: no endpoint lists events, and adding
  one would ship thousands of rows to compute about thirty numbers. The Mac and the phone would also
  each carry a copy of the ranking and windowing rules, and those copies would drift. That is the
  divergent-subset shape `NativeAudioEngine` has already shown twice.
- **Read `ProfilePlayHistory` and label it "all time".** Rejected for the video: "your year" is the
  whole premise, and the aggregate cannot be scoped. It would also double-count
  `/played` calls made before the event table existed.
- **Precompute in December with the scheduler** (`backend/app/services/background/manager.py`).
  Rejected for now: it adds a table and a job, and makes the recap stale the moment more listening
  happens. Computing on request is cheap at this volume, as point 7 shows. Revisit if a recap is ever
  shown to many profiles at once.
- **Use 2026-07-26, the first day of data, as the boundary for counts.** Rejected in point 3: it gains
  five days at the cost of a second boundary.

## Consequences

- **Positive:** every client gets the same numbers, and the window is stated rather than implied, so
  "since August 1" is a fact the server reports.
- **Positive:** the sound summary uses analysis Familiar already has, and no streaming service can say it.
- **Tradeoff:** the 2026 recap covers about five months. That is the honest scope, and point 3 makes it visible.
- **Tradeoff:** one more endpoint on the `plays` tag, and the generated clients change. In
  `familiar-apple`, run `scripts/vendor-schema.sh --fetch` after this merges.
- **Follow-up:** a `client` column on `play_events` (ADR-0004's open follow-up) would allow
  "you listened on your phone 70% of the time". It is not needed for the first recap.
