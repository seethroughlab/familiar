# ADR-0163: The Server Resolves Lyrics and Reports a Status

Status: accepted

Date: 2026-11-06

Implementation:

- **Built 2026-11-07 in `familiar` #433**, every point but 9: the reject endpoint is not built yet.
  On the same 400 tracks, synced went from 105 to 132, plain from 67 to 40 (29 upgraded to synced),
  53 instrumentals were named as such, and misses fell from 222 to 167. Two baseline hits were lost:
  one was transient on that run, and the other is mistagged with the mix name as its title. LRCLIB's
  free-text search found 0 of 30 sampled misses.

Extends [ADR-0051](ADR-0051-edited-metadata-outranks-file-tags.md).

## Context

`GET /tracks/{id}/lyrics` asks LRCLIB's `/get`, then `/search`, and takes `data[0]`. Every failure
inside it is `except Exception: return None`, so a rate limit, an outage and a track with no lyrics
all reach the client as the same empty 200.

**Measured on 2026-11-06:** a fixed uniform sample of 400 tracks from a 27,366-track library, run
through the existing service by `scripts/measure_lyrics.py`, with every request recorded.

| Outcome | Tracks |
|---|---|
| Synced | 105 (26%) |
| Plain only | 67 (17%) |
| Miss | 222 (56%) |
| Skipped, no title or artist | 6 |
| Transient failure | 0 |

What those numbers settle:

- **Most misses are not matching failures on this library.** 45 of the 222 are tracks LRCLIB itself
  marks instrumental, and it is a heavily electronic collection. The service discards that answer and
  calls `/search` anyway. **Hit rate is a property of the library, so this ADR sets no target for it.**
- **Plain-only results are thrown away.** The 67 would reach a client that discards anything unsynced
  (`useSyncedLyrics.ts`), and only synced results are cached, so each is re-fetched on every request.
- **`data[0]` is not safe.** Of 35 hits that came from `/search`, 11 were more than 3 s from the track's
  length. Some are the right song (`Beatles` "I'll Follow the Sun", 4 s) and some are not (`Jupiter`
  "Saké (Blackjoy Version)", 224 s). Four plain results were chosen while a synced one was in the
  same response.
- **Library metadata shapes the misses.** The sample has `Cardigans, The` and `14-Too Long`, and 41 of
  the misses have a parenthesis, bracket, `feat`, `remaster` or ` - ` in the title.

**Contradicted premise: embedded lyrics were assumed to be unavailable.** The tag reader already reads
ID3 `USLT`, Vorbis `lyrics`/`unsyncedlyrics` and MP4 `©lyr`. The scanner keeps only
`lyrics_language` and discards the text, and `Track.lyrics` is populated on 0 of 27,366 rows. The route
also never reads that column, so a hand-edited value would be ignored too.

**Writing the cache has a cost nobody has paid yet.** `Track.updated_at` has `onupdate=func.now()`
(`tracks.py:171`) and is the delta cursor (`listing.py`). Today only 167 rows have `synced_lyrics`.
Once clients really call this route, an ordinary ORM write would re-send each looked-up track to every
phone.

LRCLIB's published rules also apply, and the service breaks them: identify the client, honour
`Retry-After`, and space requests out.

## Decision

1. **The first synced source wins, otherwise the first plain.** In order: edited `Track.lyrics`, a `.lrc`
   sidecar, `SYLT`, embedded text containing LRC timestamps, LRCLIB, embedded plain text. Local sources
   are read at lookup time, read-only, so no re-scan is needed and zero-touch is unaffected.

2. **LRCLIB is asked in a ladder of at most four calls, stopping at a definite answer.** `/get` exact;
   `/get` with normalised title and artist; `/get` with the album or primary artist; `/search`.
   Normalising strips `feat.`, remaster suffixes and track-number prefixes, and turns `X, The` into
   `The X`. **It never strips `live`, `remix`, `version` or `instrumental`**, because those name
   different recordings.

3. **`/search` results are matched, not trusted.** A candidate must match normalised title and artist.
   Synced within 5 s of the track's length beats plain within 5 s, and then the closer length wins.
   **A length further out rules out the timing, not the words:** the right title and artist at the wrong
   length is usually another edit of the same song, so it is shown as plain lyrics. A title with a
   parenthetical gloss, such as `Прогноз (Prognoz, Forecast)`, is believed only within 2 s. No acceptable
   candidate is a miss.

4. **Instrumental is an answer.** It ends the lookup, and is stored and reported.

5. **The response gains an optional `status`:** `found`, `plain_only`, `instrumental`, `not_found` or
   `unavailable`. A plain string, because generated enums are closed and an unknown value would fail the
   whole decode. The contract version is not bumped, since no shipped client reads this route.

6. **`unavailable` is never remembered.** A 429, 5xx or timeout returns it, with no miss written. A
   `Retry-After` stops all calls for that long, and requests are paced globally.

7. **Misses are cached in kv for 14 days plus jitter,** because LRCLIB's data is user-contributed and
   grows. No migration.

8. **Positive results are stored with an identity hash,** of title, artist, album, rounded duration and
   sidecar mtime, compared on read. A retag or an edit re-resolves with no hooks on any of the write
   paths. **Writes do not move `updated_at`.**

9. **A wrong match can be rejected,** through `POST /tracks/{id}/lyrics/reject`. Its source id is excluded
   and the track re-resolves.

## Alternatives Considered

**Add a second provider.** The obvious response to a 56% miss rate. Rejected for now: the measurement
says many of those are instrumentals and obscure electronic tracks, which no provider would have. A
provider also means another third party receiving what people play, and the commercial lyrics APIs are
licensed products. Revisit if, after this ADR, hand-checking shows the misses are real songs LRCLIB
lacks.

**Harvest lyrics for the whole library during sync.** Everything instant and available offline.
Rejected: at LRCLIB's rate limits it is hours of requests, for tracks nobody may ever play, sent by
default on an install that has not opened lyrics. ADR-0160's prefetch covers what is about to be used.

**Fix only `/search` and leave embedded text out.** Much less code. Rejected because the maintainer asked
for everything reasonable, and a listener's own tags are the most accurate source there is, sent nowhere.

**Scan embedded lyrics into `Track.lyrics` during library sync.** Faster at lookup and queryable. Rejected
for this decision: it needs a re-scan of every file to populate, and a sidecar's text would still need
reading at lookup. Nothing here prevents it later.

**A migration for a lookup table or a `lyrics_checked_at` column.** Queryable and tidy. Rejected: kv already
has the TTL semantics a miss needs, and it works on both Redis and Postgres under ADR-0133.

## Consequences

- **Positive:** a client can finally tell "no lyrics exist" from "couldn't ask".
- **Positive:** plain lyrics and instrumental tracks get an honest result.
- **Positive:** the server follows LRCLIB's rules.
- **Tradeoff:** the same 400 tracks may lose some hits, because accepting fewer `/search` results is the
  point. Each lost hit is audited as a false positive rather than counted as a regression.
- **Tradeoff:** a lookup can take several seconds at the top of the ladder.
- **Follow-up:** what a user sees for each status is ADR-0160's point 5.
