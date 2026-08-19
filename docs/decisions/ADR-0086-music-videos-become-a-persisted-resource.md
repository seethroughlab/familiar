# ADR-0086: Music Videos Become a Persisted Resource

Status: proposed

Date: 2026-08-18

Extends [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md), whose vendored surface this adds
one tag to, and whose point 8 it leans on for the one handler that stays outside. Prerequisite for
[ADR-0085](ADR-0085-music-videos-are-a-mac-function-not-a-visualizer.md) — **this one executes
first**, on the principle that server-side work every client inherits comes before client work.

## Context

Music video support has been in the product since Phase 5 and was never removed. That is worth
stating because it has already been got wrong once:
[ADR-0055](ADR-0055-the-site-is-restructured-around-five-things.md) lines 50–55 record an audit that
concluded the support had been deleted, on a grep that used the wrong term. What was removed is a
row on the website's comparison table (`docs/SITE-CLAIMS.md:101`), not the feature. The router is
mounted at `app/main.py:515`.

What exists, verified at write time:

- `app/api/routes/videos.py` (254 lines) — five operations under `/videos`, all keyed by track:
  `search`, `status`, `download`, `stream`, `delete`.
- `app/services/video.py` (280 lines) — yt-dlp search and download, one file per track at
  `settings.videos_path` (`app/config.py:41`, default `data/videos`), already in the S3 backup set
  (`app/services/s3_backup.py:312`).
- `TrackVideo`, table `track_videos` (`app/db/models/tracks.py:339`) — `source`, `source_id`,
  `source_url`, `file_path`, `is_audio_only`, `file_size_bytes`, `video_metadata`,
  `match_confirmed_by`, `downloaded_at`, `last_played_at`, with a unique constraint on
  `(track_id, source, source_id)`.

Three findings make this ADR necessary rather than optional, and all three were checked rather than
assumed:

1. **`videos` is not in the generated surface.** `scripts/lint_openapi.py:59` lists eleven vendored
   tags and `videos` is not among them, so a generated client cannot reach these operations at all.
2. **`track_videos` is orphaned.** It is declared and exported (`app/db/models/__init__.py:39`), and
   the table does exist — the baseline builds fresh databases with `Base.metadata.create_all()`
   (`migrations/versions/20241231_000000_baseline.py`), so it is created without a named migration
   ever mentioning it. **Nothing in the application reads or writes it.** No migration file in
   `migrations/versions/` contains the string `video` at all. The service's own
   `VideoDownloadStatus` is an unrelated in-memory dataclass whose similar name is the reason this
   is easy to miss.
3. **The stream handler advertises range support it does not implement.** It sets
   `Accept-Ranges: bytes` and then reads the file from byte 0 on every request; the `Range` request
   header is not parsed anywhere in the file. A player that seeks gets the whole file again from the
   start.

A fourth fact shapes the scope: **download state lives only in process memory.**
`VideoService._downloads` is a `dict` (`app/services/video.py:43`) populated by `set_pending` and
the download coroutine, and the download itself runs in FastAPI `BackgroundTasks`. A restart loses
every in-flight download and every record of which YouTube video a file came from — `has_video()`
is a check that `{track_id}.mp4` exists on disk, and nothing more.

The consequence that matters for `ADR-0085` is that **there is no way to ask which tracks have
videos.** Every operation is keyed by a track id you already have. A destination that lists them has
nothing to call.

There are **no functional tests for this feature** on either side. The only test that mentions
`/videos/` is `tests/test_contract_error_shapes.py`, which asserts an error envelope.

## Decision

1. **`track_videos` becomes the record of what was downloaded.** A completed download writes a
   `TrackVideo` row — `source` (`youtube`), `source_id`, `source_url`, `file_path`,
   `file_size_bytes`, `downloaded_at`, and the yt-dlp metadata worth keeping in `video_metadata`.
   The columns already exist and are adequate; this is a service that starts using its table, not a
   schema change. `delete_video` removes the row with the file.

2. **`has_video` and `get_download_status` resolve against the database first.** The in-memory dict
   stays as the progress cache for a download that is currently running — that is what it is good
   at — but a restart no longer erases the fact that a video exists, and "which video" becomes
   answerable. Where the two disagree, the file on disk wins for existence and the row wins for
   identity; a row whose `file_path` is gone is deleted rather than reported.

3. **`GET /videos` lists tracks that have a video**, paged, ordered, returning enough to draw a row
   — track id, title, artist, the source id, and `downloaded_at`. This is the operation
   `ADR-0085`'s destination is built on, and it is the one thing the current surface cannot do.

4. **`GET /videos/{track_id}/stream` honours `Range`.** Parse the header, return `206` with a
   correct `Content-Range` and only the requested bytes, and return `200` with the whole file when
   there is no header. `Accept-Ranges: bytes` then stops being a claim the handler cannot keep.
   **`release_connection(db)` stays exactly where it is** — the comment above it records why, and it
   is the fix for a defect that turned 834 downloads into 83-byte error bodies: a `yield` dependency
   otherwise holds a database connection for the length of the video.

5. **The `videos` tag joins `VENDORED_TAGS`** (`scripts/lint_openapi.py:59`) — **except the stream
   handler, which stays out under ADR-0007 point 8.** That point already excludes
   `/tracks/{id}/stream` for exactly this reason: range requests are handled by `URLSession`
   directly, and generated clients handle them badly. The video stream is the same kind of thing and
   `AVPlayer` is the caller, so it is written by hand on the client. Search, status, download, list
   and delete are ordinary JSON and are generated.

6. **The video stream is media, and inherits ADR-0045's media exemption.** That ADR decided on
   2026-08-09 that artwork and audio streams are exempt from the authentication gate, because a
   media element cannot send a header and a cast target holds no credential. A video element is the
   same case. This is recorded so it is not re-litigated when point 5 of that ADR ships, and so
   nobody adds a profile header to an `AVURLAsset` to work around a gate that does not apply.

7. **Every point above gets a test.** The feature has none today, which is why three of the findings
   in `## Context` survived this long: range correctness (a `206` with the right `Content-Range` and
   the right bytes, and a `200` without the header), the list endpoint's shape, and a download that
   writes its row. The lint script already fails if the vendored tag set and the schema disagree, so
   point 5 tests itself.

## Alternatives Considered

**Leave the endpoints un-vendored and hand-write all five calls in Swift.** Tempting because the
stream has to be hand-written anyway, so the split feels like an inconsistency. Rejected because
ADR-0007's carve-out is specifically about *bodies generated clients handle badly* — range requests
and SSE — and search results, status and a paged list are ordinary JSON. Hand-writing them buys a
false tidiness and gives up the schema check that catches a response shape changing underneath the
client.

**Move the download to the Redis worker system** (`app/services/background.py`, `tasks.py`) instead
of `BackgroundTasks`. Genuinely better for a long download that should survive a deploy, and
rejected here on scope: it is a decision about where background work runs, it would apply to more
than videos, and `BackgroundTasks` is adequate for one user-initiated download of a few minutes.
Making the record durable (point 1) removes the sharp edge — a lost in-flight download is now
visibly incomplete rather than invisibly forgotten.

**Keep file existence as the source of truth and answer `GET /videos` with a directory scan.**
Cheapest possible list endpoint, and it works, since the filenames are track ids. Rejected because
it cannot answer *which* video is attached, which is what a re-match needs, and because it makes the
orphaned table permanent — a schema that describes something the code refuses to use is worse than
no schema at all.

**Add `has_video` to the track model's serialisation instead of a list endpoint.** Would let any
existing list filter on it with no new operation. Rejected: it puts a per-track filesystem or join
cost on every track response in the app to serve one screen, and the filter belongs where the
question is asked.

## Consequences

- **Positive** — the Mac can ask what has a video, which is the single blocker on `ADR-0085`'s
  destination.
- **Positive** — `AVPlayer` can seek, and so can any browser `<video>` element; the header stops
  being a promise the handler breaks.
- **Positive** — a table that has been declared, exported and unused becomes load-bearing, and the
  `(track_id, source, source_id)` unique constraint starts doing the job it was written for.
- **Positive** — the first functional tests this feature has ever had.
- **Tradeoff** — existence is now answered from two places (a row and a file) and they can disagree.
  Point 2 states which wins for which question rather than leaving it to be discovered.
- **Tradeoff** — a download that dies with the process still leaves no row, so it looks like a
  download that never started. Better than the current behaviour, but not the same as durable.
- **Follow-up** — moving the download to the worker system, if a video that survives a deploy turns
  out to matter.
- **Follow-up** — `is_audio_only`, `match_confirmed_by` and `last_played_at` stay unused after this
  ADR. They are not removed, because `ADR-0085`'s match-and-download action is the natural caller
  for `match_confirmed_by`; if it ships without one, they should go.
